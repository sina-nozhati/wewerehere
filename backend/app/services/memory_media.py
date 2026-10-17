"""Validate and store participant memory photos/videos."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from app.config import settings

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
            # Accept common ftyp brands; reject if clearly not video
            return "video", "video/mp4", ".mp4"

    raise MemoryMediaError("unsupported_type")


def max_bytes_for_kind(kind: str) -> int:
    if kind == "image":
        return max(1, int(settings.memory_photo_max_mb)) * 1024 * 1024
    return max(1, int(settings.memory_video_max_mb)) * 1024 * 1024


def event_memories_dir(event_id: int) -> Path:
    d = settings.memories_dir / str(int(event_id))
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_memory_file(event_id: int, data: bytes, ext: str) -> str:
    """Write bytes; return relative stored_name like '{event_id}/{hex}.ext'."""
    safe_ext = ext if re.fullmatch(r"\.[a-z0-9]{2,5}", ext) else ".bin"
    name = f"{secrets.token_hex(16)}{safe_ext}"
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
