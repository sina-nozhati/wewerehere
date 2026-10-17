"""Validate and store participant memory photos/videos."""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import subprocess
import unicodedata
from pathlib import Path

from app.config import settings

log = logging.getLogger("wwh.memory_media")

# Magic-byte sniff — do not trust client Content-Type alone.
_JPEG = (b"\xff\xd8\xff", "image/jpeg", ".jpg", "image")
_PNG = (b"\x89PNG\r\n\x1a\n", "image/png", ".png", "image")
_WEBP_RIFF = b"RIFF"
_WEBP_WEBP = b"WEBP"
_FTYP = b"ftyp"
_MP4_BRANDS = (b"isom", b"iso2", b"mp41", b"mp42", b"MSNV", b"M4V ", b"avc1", b"qt  ")
_WEBM = (b"\x1a\x45\xdf\xa3", "video/webm", ".webm", "video")

_DENIED_EXT = frozenset(
    {
        ".svg",
        ".svgz",
        ".html",
        ".htm",
        ".js",
        ".mjs",
        ".exe",
        ".bat",
        ".cmd",
        ".sh",
        ".php",
        ".py",
        ".wasm",
    }
)


class MemoryMediaError(ValueError):
    """Invalid or unsupported upload."""


def sniff_media(data: bytes, filename_hint: str = "") -> tuple[str, str, str]:
    """Return (media_kind, mime, ext). Raises MemoryMediaError."""
    if not data or len(data) < 12:
        raise MemoryMediaError("file_too_small")
    hint = (filename_hint or "").lower()
    for bad in _DENIED_EXT:
        if hint.endswith(bad):
            raise MemoryMediaError("file_type_denied")

    if data.startswith(_JPEG[0]):
        return _JPEG[3], _JPEG[1], _JPEG[2]
    if data.startswith(_PNG[0]):
        return _PNG[3], _PNG[1], _PNG[2]
    if data.startswith(_WEBP_RIFF) and data[8:12] == _WEBP_WEBP:
        return "image", "image/webp", ".webp"
    if data.startswith(_WEBM[0]):
        return _WEBM[3], _WEBM[1], _WEBM[2]
    # ISO BMFF (MP4 / QuickTime)
    if len(data) >= 12 and data[4:8] == _FTYP:
        brand = data[8:12]
        if brand in _MP4_BRANDS or brand.strip():
            return "video", "video/mp4", ".mp4"

    raise MemoryMediaError("unsupported_type")


def max_bytes_for_kind(kind: str) -> int:
    if kind == "image":
        return max(1, int(settings.memory_photo_max_mb)) * 1024 * 1024
    return max(1, int(settings.memory_video_max_mb)) * 1024 * 1024


def video_max_sec() -> int:
    return max(1, int(settings.memory_video_max_sec))


def holder_slug(name: str, *, max_len: int = 40) -> str:
    """Path-safe slug from ticket holder name (keeps Persian letters)."""
    text = unicodedata.normalize("NFKC", (name or "").strip())
    out: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch.isalnum() or ("\u0600" <= ch <= "\u06ff") or ("\u0750" <= ch <= "\u077f"):
            out.append(ch)
        elif ch in (" ", "-", "_", "\u200c"):
            out.append("-")
        elif cat.startswith("L") or cat.startswith("N"):
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-{2,}", "-", "".join(out)).strip("-").lower()
    if not slug:
        slug = "guest"
    return slug[:max_len]


def ticket_folder_name(ticket_id: int, holder_name: str = "") -> str:
    return f"t{int(ticket_id)}_{holder_slug(holder_name)}"


def event_memories_dir(event_id: int) -> Path:
    d = settings.memories_dir / str(int(event_id))
    d.mkdir(parents=True, exist_ok=True)
    return d


def ticket_memories_dir(event_id: int, ticket_id: int, holder_name: str = "") -> Path:
    d = event_memories_dir(event_id) / ticket_folder_name(ticket_id, holder_name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_memory_file(
    event_id: int,
    data: bytes,
    ext: str,
    *,
    ticket_id: int | None = None,
    holder_name: str = "",
) -> str:
    """Write bytes; return relative stored_name.

    Guest uploads: '{event_id}/t{ticket_id}_{slug}/{hex}.ext'
    Legacy/admin without ticket: '{event_id}/{hex}.ext'
    """
    safe_ext = ext if re.fullmatch(r"\.[a-z0-9]{2,5}", ext) else ".bin"
    name = f"{secrets.token_hex(16)}{safe_ext}"
    if ticket_id is not None:
        folder = ticket_folder_name(ticket_id, holder_name)
        dest = ticket_memories_dir(event_id, ticket_id, holder_name) / name
        dest.write_bytes(data)
        return f"{int(event_id)}/{folder}/{name}"
    dest = event_memories_dir(event_id) / name
    dest.write_bytes(data)
    return f"{int(event_id)}/{name}"


def absolute_memory_path(stored_name: str) -> Path | None:
    """Resolve stored_name under memories_dir; reject traversal."""
    raw = (stored_name or "").replace("\\", "/").lstrip("/")
    if not raw or ".." in raw.split("/"):
        return None
    root = settings.memories_dir.resolve()
    path = (settings.memories_dir / raw).resolve()
    if not str(path).startswith(str(root)):
        return None
    return path if path.is_file() else None


def delete_memory_file(stored_name: str) -> None:
    path = absolute_memory_path(stored_name)
    if path and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def _which(bin_name: str) -> str | None:
    return shutil.which(bin_name) or None


def probe_video_duration_sec(path: Path) -> float | None:
    """Return duration in seconds via ffprobe, or None if unavailable/failed."""
    probe = _which(settings.memory_ffprobe_bin) or _which("ffprobe")
    if not probe:
        return None
    try:
        proc = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            log.warning("ffprobe failed: %s", (proc.stderr or "")[:200])
            return None
        data = json.loads(proc.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration") or 0)
        return dur if dur > 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as e:
        log.warning("ffprobe error: %s", e)
        return None


def assert_video_duration_ok(path: Path) -> float | None:
    """Raise MemoryMediaError('video_too_long') if over limit. Returns duration or None."""
    dur = probe_video_duration_sec(path)
    if dur is None:
        return None
    if dur > float(video_max_sec()) + 0.5:
        raise MemoryMediaError("video_too_long")
    return dur


def transcode_video_720p(path: Path) -> tuple[Path, str, int] | None:
    """Transcode in-place-ish to H.264 720p MP4. Returns (new_path, mime, size) or None."""
    ffmpeg = _which(settings.memory_ffmpeg_bin) or _which("ffmpeg")
    if not ffmpeg:
        log.info("ffmpeg not found; skip transcode")
        return None
    out = path.with_name(path.stem + "_720p.mp4")
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(path),
                "-vf",
                "scale=-2:720",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 32:
            log.warning("ffmpeg transcode failed: %s", (proc.stderr or "")[:400])
            try:
                if out.is_file():
                    out.unlink()
            except OSError:
                pass
            return None
        # Replace original with compressed mp4 (even if original was webm)
        final = path.with_suffix(".mp4")
        if final.resolve() != out.resolve():
            if final.exists():
                final.unlink()
            out.replace(final)
        else:
            final = out
        if path.resolve() != final.resolve() and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return final, "video/mp4", int(final.stat().st_size)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("ffmpeg error: %s", e)
        try:
            if out.is_file():
                out.unlink()
        except OSError:
            pass
        return None


def relative_stored_name(path: Path) -> str | None:
    """Turn absolute path under memories_dir into stored_name."""
    try:
        root = settings.memories_dir.resolve()
        rel = path.resolve().relative_to(root)
        return str(rel).replace("\\", "/")
    except ValueError:
        return None
