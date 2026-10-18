"""Unit tests for shared media_guard sniff + image sanitize."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.media_guard import MediaGuardError, guard_media, sanitize_image, sniff_media


def _jpeg_bytes(size: tuple[int, int] = (32, 24), color: tuple[int, int, int] = (200, 40, 80)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _png_bytes() -> bytes:
    img = Image.new("RGBA", (16, 16), (10, 20, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_sniff_rejects_text_spoofed_as_jpeg():
    fake = b"not an image at all, just text pretending"
    with pytest.raises(MediaGuardError) as ei:
        sniff_media(fake, "photo.jpg")
    assert ei.value.code == "unsupported_type"


def test_sniff_rejects_denied_extension_even_with_jpeg_bytes():
    data = _jpeg_bytes()
    with pytest.raises(MediaGuardError) as ei:
        sniff_media(data, "payload.php")
    assert ei.value.code == "file_type_denied"


def test_sniff_accepts_real_jpeg_and_png():
    kind, mime, ext = sniff_media(_jpeg_bytes(), "a.jpg")
    assert kind == "image" and mime == "image/jpeg" and ext == ".jpg"
    kind2, mime2, ext2 = sniff_media(_png_bytes(), "b.png")
    assert kind2 == "image" and mime2 == "image/png" and ext2 == ".png"


def test_guard_sanitizes_jpeg_and_returns_valid_image():
    raw = _jpeg_bytes()
    g = guard_media(raw, "shot.jpg")
    assert g.kind == "image"
    assert g.mime in ("image/jpeg", "image/png", "image/webp")
    assert len(g.data) > 20
    # Round-trip: sanitized bytes must open
    with Image.open(io.BytesIO(g.data)) as im:
        im.load()
        assert im.size[0] > 0


def test_guard_images_only_rejects_video_magic():
    # Minimal EBML / WebM header
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 20
    with pytest.raises(MediaGuardError) as ei:
        guard_media(webm, "clip.webm", images_only=True)
    assert ei.value.code == "image_only"


def test_sanitize_strips_trailing_junk_after_valid_jpeg():
    """Polyglot-ish: JPEG + appended script — re-encode should drop the tail."""
    raw = _jpeg_bytes() + b"\n<script>alert(1)</script>\n"
    # Sniff still sees JPEG magic
    kind, mime, _ext = sniff_media(raw, "x.jpg")
    assert kind == "image"
    safe, out_mime, out_ext = sanitize_image(raw, mime)
    assert b"<script>" not in safe
    assert out_mime.startswith("image/")
    assert out_ext in (".jpg", ".png", ".webp")
    with Image.open(io.BytesIO(safe)) as im:
        im.load()


def test_guard_max_bytes():
    raw = _jpeg_bytes((800, 600))
    with pytest.raises(MediaGuardError) as ei:
        guard_media(raw, "big.jpg", max_bytes=50)
    assert ei.value.code == "file_too_large"


def _heic_bytes() -> bytes:
    pytest.importorskip("pillow_heif")
    from pillow_heif import register_heif_opener

    register_heif_opener()
    img = Image.new("RGB", (24, 16), (90, 40, 200))
    buf = io.BytesIO()
    img.save(buf, format="HEIF")
    return buf.getvalue()


def _ftyp_box(major: bytes, *compat: bytes) -> bytes:
    """Minimal ISO BMFF ftyp header (not a playable file)."""
    body = b"ftyp" + major + b"\x00\x00\x00\x00" + b"".join(compat)
    size = (4 + len(body)).to_bytes(4, "big")
    return size + body + b"\x00" * 32


def test_sniff_heic_iphone_style_brand():
    raw = _ftyp_box(b"heic", b"mif1", b"heic")
    kind, mime, ext = sniff_media(raw, "IMG_1234.HEIC")
    assert kind == "image"
    assert mime == "image/heic"
    assert ext == ".heic"


def test_sniff_heif_samsung_mif1_brand():
    # Many Android/Samsung HEIF stills use major brand mif1
    raw = _ftyp_box(b"mif1", b"mihf", b"heic")
    kind, mime, ext = sniff_media(raw, "PHOTO.heif")
    assert kind == "image" and mime == "image/heic"


def test_sniff_avif_brand():
    raw = _ftyp_box(b"avif", b"mif1", b"avif")
    kind, mime, ext = sniff_media(raw, "shot.avif")
    assert kind == "image" and mime == "image/avif" and ext == ".avif"


def test_guard_heic_converts_to_jpeg():
    raw = _heic_bytes()
    g = guard_media(raw, "from-iphone.heic")
    assert g.kind == "image"
    assert g.mime == "image/jpeg"
    assert g.ext == ".jpg"
    assert g.data.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(g.data)) as im:
        im.load()
        assert im.size[0] >= 8


def test_sniff_mov_quicktime_brand():
    raw = _ftyp_box(b"qt  ", b"qt  ")
    kind, mime, ext = sniff_media(raw, "IMG_0001.MOV")
    assert kind == "video"
    assert mime == "video/quicktime"
    assert ext == ".mov"


def test_sniff_mp4_isom_stays_mp4():
    raw = _ftyp_box(b"isom", b"isom", b"mp41")
    kind, mime, ext = sniff_media(raw, "clip.mp4")
    assert kind == "video" and mime == "video/mp4" and ext == ".mp4"


def test_guard_accepts_mov_as_video_bytes():
    raw = _ftyp_box(b"qt  ", b"qt  ")
    g = guard_media(raw, "reel.mov")
    assert g.kind == "video"
    assert g.ext == ".mov"
    assert g.data == raw
