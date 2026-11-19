"""Validate and store participant memory photos/videos."""

from __future__ import annotations

import io
import json
import logging
import re
import secrets
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.config import settings

log = logging.getLogger("wwh.memory_media")

from app.services.media_guard import MediaGuardError, guard_media, sniff_media as _guard_sniff


class MemoryMediaError(ValueError):
    """Invalid or unsupported upload."""


def sniff_media(data: bytes, filename_hint: str = "") -> tuple[str, str, str]:
    """Return (media_kind, mime, ext). Raises MemoryMediaError."""
    try:
        return _guard_sniff(data, filename_hint)
    except MediaGuardError as e:
        raise MemoryMediaError(e.code) from e


def guard_and_prepare(
    data: bytes,
    filename_hint: str = "",
    *,
    max_bytes: int | None = None,
) -> tuple[str, str, str, bytes]:
    """Sniff + sanitize images. Returns (kind, mime, ext, safe_bytes)."""
    try:
        g = guard_media(data, filename_hint, max_bytes=max_bytes)
    except MediaGuardError as e:
        raise MemoryMediaError(e.code) from e
    return g.kind, g.mime, g.ext, g.data


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


def resolve_memory_path(stored_name: str) -> Path | None:
    """Resolve destination path under memories_dir safely (even if file does not exist yet)."""
    raw = (stored_name or "").replace("\\", "/").lstrip("/")
    if not raw or ".." in raw.split("/"):
        return None
    root = settings.memories_dir.resolve()
    path = (settings.memories_dir / raw).resolve()
    if not str(path).startswith(str(root)):
        return None
    return path


def find_existing_media_path(stored_name: str) -> Path | None:
    """Find media file across memories_dir, storage_root, archive_dir, and legacy uploads."""
    p = absolute_memory_path(stored_name)
    if p and p.is_file():
        return p
    try:
        from app.services.storage.local_adapter import LocalStorageAdapter

        p_local = LocalStorageAdapter().resolve_local_path(stored_name)
        if p_local and p_local.is_file():
            return p_local
    except Exception:
        pass
    return None


def thumbnail_stored_name(stored_name: str) -> str:
    """Derive stored_name for thumbnail WebP companion."""
    p = Path(stored_name)
    return str(p.with_name(f"{p.stem}_thumb.webp")).replace("\\", "/")


def web_video_stored_name(stored_name: str) -> str:
    """Derive stored_name for web-optimized MP4 companion."""
    p = Path(stored_name)
    return str(p.with_name(f"{p.stem}_web.mp4")).replace("\\", "/")


def resolve_video_web_path(stored_name: str) -> Path | None:
    """Find web-optimized MP4 companion file if it exists."""
    src = find_existing_media_path(stored_name)
    if not src:
        return None
    web = src.with_name(f"{src.stem}_web.mp4")
    return web if web.is_file() else None


def delete_memory_file(stored_name: str) -> None:
    path = absolute_memory_path(stored_name)
    if path and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
        # Clean up companion web video and thumbnail
        web_path = path.with_name(f"{path.stem}_web.mp4")
        if web_path.is_file():
            try:
                web_path.unlink()
            except OSError:
                pass
        thumb_path = path.with_name(f"{path.stem}_thumb.webp")
        if thumb_path.is_file():
            try:
                thumb_path.unlink()
            except OSError:
                pass


def _which(bin_name: str) -> str | None:
    found = shutil.which(bin_name)
    if found:
        return found
    # Windows fallback search
    for candidate in [
        r"C:\Program Files\DownloadHelper CoApp",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ffmpeg\bin",
    ]:
        p = Path(candidate) / (bin_name if bin_name.endswith(".exe") else f"{bin_name}.exe")
        if p.is_file():
            return str(p)
    return None


def probe_video_meta(path: Path) -> dict[str, Any]:
    """Return dict with duration, width, height, bitrate, fps or empty dict."""
    probe = _which(settings.memory_ffprobe_bin) or _which("ffprobe")
    if not probe:
        return {}
    try:
        proc = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,bit_rate:format=duration,bit_rate",
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
            return {}
        data = json.loads(proc.stdout or "{}")
        meta: dict[str, Any] = {}
        fmt = data.get("format") or {}
        streams = data.get("streams") or []
        v_stream = streams[0] if streams else {}

        dur = float(fmt.get("duration") or v_stream.get("duration") or 0)
        if dur > 0:
            meta["duration"] = dur

        w = int(v_stream.get("width") or 0)
        h = int(v_stream.get("height") or 0)
        if w > 0 and h > 0:
            meta["width"] = w
            meta["height"] = h

        br = int(v_stream.get("bit_rate") or fmt.get("bit_rate") or 0)
        if br > 0:
            meta["bitrate"] = br

        fps_raw = str(v_stream.get("r_frame_rate") or "")
        if "/" in fps_raw:
            num, den = fps_raw.split("/", 1)
            try:
                num_f, den_f = float(num), float(den)
                if den_f > 0:
                    meta["fps"] = round(num_f / den_f, 2)
            except ValueError:
                pass

        return meta
    except Exception as e:
        log.warning("probe_video_meta error: %s", e)
        return {}


def probe_video_duration_sec(path: Path) -> float | None:
    """Return duration in seconds via ffprobe, or None if unavailable/failed."""
    meta = probe_video_meta(path)
    dur = meta.get("duration")
    if dur and dur > 0:
        return dur
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
        if proc.returncode == 0:
            data = json.loads(proc.stdout or "{}")
            d = float((data.get("format") or {}).get("duration") or 0)
            return d if d > 0 else None
    except Exception:
        pass
    return None


def assert_video_duration_ok(path: Path) -> float | None:
    """Raise MemoryMediaError('video_too_long') if over limit. Returns duration or None."""
    dur = probe_video_duration_sec(path)
    if dur is None:
        return None
    if dur > float(video_max_sec()) + 0.5:
        raise MemoryMediaError("video_too_long")
    return dur


def transcode_video_high_quality(path: Path) -> tuple[Path, str, int] | None:
    """Generate high visual fidelity web playback stream/file while preserving the original.

    Codec & Encoder: H.264 libx264, CRF 19, -pix_fmt yuv420p, -movflags +faststart, AAC audio 192k.
    Bitrate target: >= 12 Mbps (12,000 kbps) for 1080p+, scaled appropriately for lower resolutions.
    Preserves original file untouched.
    """
    ffmpeg = _which(settings.memory_ffmpeg_bin) or _which("ffmpeg")
    if not ffmpeg:
        log.info("ffmpeg not found; skip transcode")
        return None

    # Destination is alongside original, e.g. stem_web.mp4
    out = path.with_name(f"{path.stem}_web.mp4")

    # Probe resolution to keep bitrate sensible to input resolution/framerate
    meta = probe_video_meta(path)
    w = meta.get("width") or 0
    h = meta.get("height") or 0
    max_dim = max(w, h)
    min_dim = min(w, h)

    # Bitrate parameters:
    # Target minimum video bitrate of 12 Mbps (12,000 kbps) for high visual fidelity
    if max_dim >= 1920 or min_dim >= 1080 or (w == 0 and h == 0):
        bv = "12M"
        maxrate = "16M"
        bufsize = "24M"
    elif max_dim >= 1280 or min_dim >= 720:
        bv = "8M"
        maxrate = "12M"
        bufsize = "16M"
    else:
        # Sensible lower bitrate for low-res (e.g. 480p/360p) to avoid bloat
        bv = "4M"
        maxrate = "6M"
        bufsize = "8M"

    # Scale filter: cap 4K to 1080p, ensure even dimensions for libx264
    if max_dim > 1920:
        vf = "scale='if(gt(iw,ih),min(1920,iw),-2)':'if(gt(iw,ih),-2,min(1920,ih))':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"
    else:
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"

    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "19",
                "-b:v",
                bv,
                "-maxrate",
                maxrate,
                "-bufsize",
                bufsize,
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
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

        # Original file at `path` is preserved!
        return out, "video/mp4", int(out.stat().st_size)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("ffmpeg error: %s", e)
        try:
            if out.is_file():
                out.unlink()
        except OSError:
            pass
        return None


# Backward-compatible alias
transcode_video_720p = transcode_video_high_quality


def generate_image_thumbnail(
    src_path: Path,
    dest_path: Path,
    *,
    max_dim: int = 720,
    quality: int = 80,
) -> Path | None:
    """Generate compact WebP thumbnail (max dim 640-720px, WebP quality 78-82) from image."""
    try:
        with Image.open(src_path) as img:
            img = ImageOps.exif_transpose(img) or img
            if img.mode in ("RGBA", "LA") or ("transparency" in getattr(img, "info", {})):
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
            else:
                if img.mode != "RGB":
                    img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest_path, format="WEBP", quality=quality, method=4)
            return dest_path if dest_path.is_file() and dest_path.stat().st_size > 0 else None
    except Exception as e:
        log.warning("generate_image_thumbnail failed for %s: %s", src_path, e)
        return None


def generate_video_thumbnail(
    src_path: Path,
    dest_path: Path,
    *,
    max_dim: int = 720,
    quality: int = 80,
) -> Path | None:
    """Generate video poster thumbnail (ffmpeg frame at 1s to WebP, quality 78-82)."""
    ffmpeg = _which(settings.memory_ffmpeg_bin) or _which("ffmpeg")
    if not ffmpeg:
        log.warning("ffmpeg not found; cannot generate video thumbnail for %s", src_path)
        return None
    try:
        # Seek to 1s
        cmd = [
            ffmpeg,
            "-y",
            "-ss",
            "00:00:01.000",
            "-i",
            str(src_path),
            "-vframes",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        frame_bytes = proc.stdout
        # If seek to 1s failed (video shorter than 1s), seek to 0s
        if not frame_bytes or proc.returncode != 0:
            cmd2 = [
                ffmpeg,
                "-y",
                "-ss",
                "00:00:00.000",
                "-i",
                str(src_path),
                "-vframes",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ]
            proc2 = subprocess.run(cmd2, capture_output=True, timeout=30, check=False)
            frame_bytes = proc2.stdout

        if not frame_bytes:
            log.warning("Could not extract video frame from %s", src_path)
            return None

        with Image.open(io.BytesIO(frame_bytes)) as img:
            img = ImageOps.exif_transpose(img) or img
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest_path, format="WEBP", quality=quality, method=4)
            return dest_path if dest_path.is_file() and dest_path.stat().st_size > 0 else None
    except Exception as e:
        log.warning("generate_video_thumbnail error for %s: %s", src_path, e)
        return None


def ensure_thumbnail(
    stored_name: str,
    media_kind: str = "image",
    *,
    force: bool = False,
) -> Path | None:
    """Ensure thumbnail WebP exists alongside media file; generate on-demand if missing."""
    src = find_existing_media_path(stored_name)
    if not src or not src.is_file():
        dest_thumb = resolve_memory_path(thumbnail_stored_name(stored_name))
        if dest_thumb and dest_thumb.is_file() and not force:
            return dest_thumb
        return None

    dest_thumb = src.with_name(f"{src.stem}_thumb.webp")
    if not force and dest_thumb.is_file() and dest_thumb.stat().st_size > 0:
        return dest_thumb

    if media_kind == "image":
        return generate_image_thumbnail(src, dest_thumb)
    elif media_kind == "video":
        web_src = src.with_name(f"{src.stem}_web.mp4")
        video_input = web_src if web_src.is_file() else src
        return generate_video_thumbnail(video_input, dest_thumb)
    return None


def backfill_thumbnails(
    db,
    event_id: int | None = None,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Auto-generate thumbnails for all memories that don't have them yet."""
    from sqlalchemy import select
    from app.models import MemoryItem

    q = select(MemoryItem)
    if event_id is not None:
        q = q.where(MemoryItem.event_id == int(event_id))
    items = db.scalars(q).all()

    stats = {"total": len(items), "created": 0, "already_present": 0, "failed": 0}
    for item in items:
        src = find_existing_media_path(item.stored_name)
        if not src:
            stats["failed"] += 1
            continue
        thumb_file = src.with_name(f"{src.stem}_thumb.webp")
        if not force and thumb_file.is_file() and thumb_file.stat().st_size > 0:
            stats["already_present"] += 1
            continue
        res = ensure_thumbnail(item.stored_name, item.media_kind, force=force)
        if res and res.is_file():
            stats["created"] += 1
        else:
            stats["failed"] += 1

    return stats


def relative_stored_name(path: Path) -> str | None:
    """Turn absolute path under memories_dir into stored_name."""
    try:
        root = settings.memories_dir.resolve()
        rel = path.resolve().relative_to(root)
        return str(rel).replace("\\", "/")
    except ValueError:
        return None
