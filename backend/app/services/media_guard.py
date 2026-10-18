"""Shared media validation: magic-byte sniff + image sanitize (Pillow re-encode).

Not a commercial antivirus. Defends against Content-Type spoofing, dangerous
extensions, and script/polyglot payloads embedded in image containers.

Also accepts common phone camera formats (HEIC/HEIF/AVIF, QuickTime MOV) and
normalizes images to web-safe JPEG/PNG/WebP.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

log = logging.getLogger("wwh.media_guard")

# Magic-byte sniff — do not trust client Content-Type alone.
_JPEG = (b"\xff\xd8\xff", "image/jpeg", ".jpg", "image")
_PNG = (b"\x89PNG\r\n\x1a\n", "image/png", ".png", "image")
_WEBP_RIFF = b"RIFF"
_WEBP_WEBP = b"WEBP"
_FTYP = b"ftyp"
_WEBM = (b"\x1a\x45\xdf\xa3", "video/webm", ".webm", "video")

# HEIF family (iPhone / Samsung / modern Android still photos)
_HEIF_BRANDS = frozenset(
    {
        b"heic",
        b"heix",
        b"hevc",
        b"hevx",
        b"heim",
        b"heis",
        b"hevm",
        b"hevs",
        b"mif1",
        b"msf1",
        b"heif",
    }
)
_AVIF_BRANDS = frozenset({b"avif", b"avis", b"AVIF"})

# ISO BMFF video (MP4 / QuickTime / iPhone camera roll)
_MP4_BRANDS = frozenset(
    {
        b"isom",
        b"iso2",
        b"iso3",
        b"iso4",
        b"iso5",
        b"iso6",
        b"mp41",
        b"mp42",
        b"mp71",
        b"MSNV",
        b"M4V ",
        b"avc1",
        b"qt  ",
        b"dash",
        b"ndas",
        b"ndsc",
        b"ndsh",
        b"ndsm",
        b"ndsp",
        b"ndss",
        b"ndxc",
        b"ndxh",
        b"ndxm",
        b"ndxp",
        b"ndxs",
        b"XAVC",
        # HEVC-in-MP4 brands seen on phone exports
        b"hvc1",
        b"hev1",
    }
)
# Major brand → treat as QuickTime (.mov) rather than .mp4
_QT_MAJOR = frozenset({b"qt  "})

DENIED_EXT = frozenset(
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
        ".dll",
        ".so",
        ".jar",
        ".apk",
        ".msi",
        ".scr",
        ".com",
        ".ps1",
        ".vbs",
    }
)

_HEIF_OPENER_READY: bool | None = None


class MediaGuardError(ValueError):
    """Invalid or unsupported upload."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class GuardedMedia:
    kind: str  # "image" | "video"
    mime: str
    ext: str
    data: bytes


def _ensure_heif_opener() -> bool:
    """Register pillow-heif once so Pillow can open HEIC/HEIF/AVIF."""
    global _HEIF_OPENER_READY
    if _HEIF_OPENER_READY is not None:
        return _HEIF_OPENER_READY
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        _HEIF_OPENER_READY = True
    except Exception as e:  # ImportError or codec init failure
        log.warning("pillow-heif unavailable: %s", e)
        _HEIF_OPENER_READY = False
    return _HEIF_OPENER_READY


def _ftyp_brands(data: bytes) -> list[bytes]:
    """Major + compatible brands from the first ftyp box (best-effort)."""
    if len(data) < 12 or data[4:8] != _FTYP:
        return []
    box_size = int.from_bytes(data[0:4], "big")
    if box_size < 16 or box_size > len(data):
        # Truncated or unusual size — still read major + a short compatible list
        end = min(len(data), 64)
    else:
        end = min(box_size, len(data))
    brands = [data[8:12]]
    for i in range(16, end - 3, 4):
        brands.append(data[i : i + 4])
    return brands


def sniff_media(data: bytes, filename_hint: str = "") -> tuple[str, str, str]:
    """Return (media_kind, mime, ext). Raises MediaGuardError."""
    if not data or len(data) < 12:
        raise MediaGuardError("file_too_small")
    hint = (filename_hint or "").lower()
    for bad in DENIED_EXT:
        if hint.endswith(bad):
            raise MediaGuardError("file_type_denied")

    if data.startswith(_JPEG[0]):
        return _JPEG[3], _JPEG[1], _JPEG[2]
    if data.startswith(_PNG[0]):
        return _PNG[3], _PNG[1], _PNG[2]
    if data.startswith(_WEBP_RIFF) and data[8:12] == _WEBP_WEBP:
        return "image", "image/webp", ".webp"
    if data.startswith(_WEBM[0]):
        return _WEBM[3], _WEBM[1], _WEBM[2]

    brands = _ftyp_brands(data)
    if brands:
        brand_set = set(brands)
        # Still photo containers before video — mif1/msf1 are HEIF, not MP4
        if brand_set & _AVIF_BRANDS:
            return "image", "image/avif", ".avif"
        if brand_set & _HEIF_BRANDS:
            return "image", "image/heic", ".heic"
        if brand_set & _MP4_BRANDS:
            major = brands[0]
            if major in _QT_MAJOR or hint.endswith(".mov"):
                return "video", "video/quicktime", ".mov"
            if hint.endswith(".m4v"):
                return "video", "video/x-m4v", ".m4v"
            return "video", "video/mp4", ".mp4"

    raise MediaGuardError("unsupported_type")


def _reencode_as_jpeg(img: Image.Image) -> tuple[bytes, str, str]:
    if img.mode != "RGB":
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue(), "image/jpeg", ".jpg"


def sanitize_image(data: bytes, sniff_mime: str) -> tuple[bytes, str, str]:
    """Re-encode image via Pillow to strip polyglots / embedded scripts / odd containers.

    HEIC/HEIF/AVIF are always normalized to JPEG for browser-safe delivery.
    """
    if sniff_mime in ("image/heic", "image/heif", "image/avif"):
        if not _ensure_heif_opener():
            raise MediaGuardError(
                "heic_unsupported",
                "HEIC/HEIF requires pillow-heif on the server",
            )

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt = (img.format or "").upper()

            # Phone camera HEIF family → always JPEG
            if sniff_mime in ("image/heic", "image/heif", "image/avif") or fmt in (
                "HEIF",
                "HEIC",
                "AVIF",
            ):
                return _reencode_as_jpeg(img)

            # Normalize exotic modes
            if img.mode in ("P", "LA"):
                img = img.convert("RGBA")
            elif img.mode == "CMYK":
                img = img.convert("RGB")

            out = io.BytesIO()
            if sniff_mime == "image/png" or fmt == "PNG" or (
                img.mode in ("RGBA", "LA") and sniff_mime != "image/jpeg"
            ):
                if img.mode not in ("RGB", "RGBA", "L"):
                    img = img.convert("RGBA")
                img.save(out, format="PNG", optimize=True)
                return out.getvalue(), "image/png", ".png"
            if sniff_mime == "image/webp" or fmt == "WEBP":
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.mode else "RGB")
                img.save(out, format="WEBP", quality=85, method=4)
                return out.getvalue(), "image/webp", ".webp"
            return _reencode_as_jpeg(img)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise MediaGuardError("image_corrupt", str(e)) from e


def guard_media(
    data: bytes,
    filename_hint: str = "",
    *,
    images_only: bool = False,
    max_bytes: int | None = None,
) -> GuardedMedia:
    """Sniff + (for images) sanitize. Returns trusted bytes/mime/ext."""
    if max_bytes is not None and len(data) > max_bytes:
        raise MediaGuardError("file_too_large")

    kind, mime, ext = sniff_media(data, filename_hint)
    if images_only and kind != "image":
        raise MediaGuardError("image_only")

    if kind == "image":
        safe, mime, ext = sanitize_image(data, mime)
        if max_bytes is not None and len(safe) > max_bytes:
            raise MediaGuardError("file_too_large")
        return GuardedMedia(kind=kind, mime=mime, ext=ext, data=safe)

    # Video: sniff-only (ffmpeg transcode handled by callers)
    return GuardedMedia(kind=kind, mime=mime, ext=ext, data=data)
