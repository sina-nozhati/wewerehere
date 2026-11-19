"""Comprehensive QA and Verifier test suite for media revamp, thumbnails, and memories gallery.

Verifies:
1. Video bitrate target >= 12 Mbps logic and encoding parameters.
2. WebP image thumbnail generation and dimension constraints.
3. Video poster thumbnail extraction (with 1s seek and 0s fallback).
4. Legacy memory thumbnail fallback / on-demand handling and backfill.
5. Frontend memories.html and lightbox verification (zero-CLS, lazy thumbs, no download, retry).
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Event, MemoryItem, SiteSetting
from app.services import memory_gate, memory_media as mm
from app.services.events import FEATURED_KEY
from app.services.tickets import issue_ticket

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    memory_gate._gate_attempts.clear()
    monkeypatch.setattr(settings, "admin_password", "test-admin-pass")
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "memory_gate_max_attempts", 5)
    monkeypatch.setattr(settings, "memory_max_files_per_ticket", 5)
    monkeypatch.setattr(settings, "memory_max_files_per_request", 2)
    monkeypatch.setattr(settings, "memory_photo_max_mb", 5)
    monkeypatch.setattr(settings, "memory_video_max_mb", 50)
    monkeypatch.setattr(settings, "memory_session_ttl_hours", 12)
    (tmp_path / "memories").mkdir(parents=True, exist_ok=True)

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="qa-night",
        title="رویداد آزمون کیفی",
        episode_number=10,
        event_at=datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="تالار اصلی",
        capacity=50,
        ticket_price=0,
        status="sales_open",
        sales_status="open",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    db.add(SiteSetting(key=FEATURED_KEY, value=str(ev.id)))

    # Ticket for uploads
    t, _ = issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="سروش پارسا",
        phone="09120000001",
        public_code="1234",
    )
    db.commit()
    db.refresh(t)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    c._ticket = t
    c._TestingSession = TestingSession
    yield c
    app.dependency_overrides.clear()
    try:
        os.remove(path)
    except OSError:
        pass


def _admin_auth(client: TestClient) -> dict:
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _gate_session(client: TestClient) -> str:
    r = client.post(
        "/api/events/qa-night/memories/gate",
        json={"serial": "1234"},
    )
    assert r.status_code == 200
    return r.json()["sessionToken"]


# ---------------------------------------------------------------------------
# 1. Video Bitrate Target >= 12 Mbps & Encoding Parameters Tests
# ---------------------------------------------------------------------------

def test_video_transcode_1080p_high_quality_parameters(tmp_path, monkeypatch):
    """Verify >= 12 Mbps target, libx264, CRF 18-20, yuv420p, faststart, and AAC 192k for 1080p."""
    orig_file = tmp_path / "clip_1080p.mp4"
    orig_file.write_bytes(b"sample_1080p_raw_stream_bytes")

    captured_cmds = []

    def fake_which(bin_name):
        return "fake_ffmpeg" if "ffmpeg" in bin_name else "fake_ffprobe"

    def fake_probe_meta(path):
        return {"width": 1920, "height": 1080, "duration": 15.0, "fps": 30.0}

    def fake_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"web_stream_result_bytes_ok" * 10)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr(mm, "_which", fake_which)
    monkeypatch.setattr(mm, "probe_video_meta", fake_probe_meta)
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = mm.transcode_video_high_quality(orig_file)
    assert result is not None
    web_path, mime, size = result

    # Check web companion path & mime
    assert web_path.name == "clip_1080p_web.mp4"
    assert mime == "video/mp4"
    assert size > 32

    # Check original file preserved untouched
    assert orig_file.is_file()
    assert orig_file.read_bytes() == b"sample_1080p_raw_stream_bytes"

    # Command line verification
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]

    # Video codec & tuning
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "libx264"

    # CRF in 18-20 range
    assert "-crf" in cmd
    crf_val = int(cmd[cmd.index("-crf") + 1])
    assert 18 <= crf_val <= 20

    # Video bitrate >= 12 Mbps target
    assert "-b:v" in cmd
    assert cmd[cmd.index("-b:v") + 1] == "12M"
    assert "-maxrate" in cmd
    assert cmd[cmd.index("-maxrate") + 1] == "16M"
    assert "-bufsize" in cmd
    assert cmd[cmd.index("-bufsize") + 1] == "24M"

    # Pixel format & streaming flags
    assert "-pix_fmt" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "+faststart" in cmd

    # Audio encoding
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-b:a" in cmd
    assert cmd[cmd.index("-b:a") + 1] == "192k"


def test_video_transcode_4k_downscales_to_1080p(tmp_path, monkeypatch):
    """Verify 4K inputs get scaled to 1080p long edge while keeping >= 12 Mbps bitrate target."""
    orig_file = tmp_path / "clip_4k.mp4"
    orig_file.write_bytes(b"sample_4k_raw_bytes")

    captured_cmds = []

    def fake_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"web_stream_4k_to_1080p" * 10)
        proc = MagicMock()
        proc.returncode = 0
        return proc

    monkeypatch.setattr(mm, "_which", lambda b: "fake_ffmpeg")
    monkeypatch.setattr(mm, "probe_video_meta", lambda p: {"width": 3840, "height": 2160, "duration": 12.0})
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = mm.transcode_video_high_quality(orig_file)
    assert result is not None

    cmd = captured_cmds[0]
    # Check scale filter in 4K downscale
    vf_idx = cmd.index("-vf")
    vf_filter = cmd[vf_idx + 1]
    assert "1920" in vf_filter
    assert cmd[cmd.index("-b:v") + 1] == "12M"


def test_video_transcode_sensible_bitrate_for_sub_hd(tmp_path, monkeypatch):
    """Verify sensible lower bitrate scaling for 720p and 480p to prevent bloat."""
    orig_file = tmp_path / "clip_sd.mp4"
    orig_file.write_bytes(b"sample_sd_bytes")

    captured = []

    def fake_run(cmd, *args, **kwargs):
        captured.append(cmd)
        Path(cmd[-1]).write_bytes(b"sd_encoded_bytes" * 5)
        proc = MagicMock()
        proc.returncode = 0
        return proc

    monkeypatch.setattr(mm, "_which", lambda b: "fake_ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    # 1. 720p HD test
    monkeypatch.setattr(mm, "probe_video_meta", lambda p: {"width": 1280, "height": 720, "duration": 10.0})
    res_720 = mm.transcode_video_high_quality(orig_file)
    assert res_720 is not None
    assert captured[0][captured[0].index("-b:v") + 1] == "8M"

    # 2. 480p SD test
    captured.clear()
    monkeypatch.setattr(mm, "probe_video_meta", lambda p: {"width": 640, "height": 480, "duration": 10.0})
    res_480 = mm.transcode_video_high_quality(orig_file)
    assert res_480 is not None
    assert captured[0][captured[0].index("-b:v") + 1] == "4M"


def test_video_transcode_error_cleanup(tmp_path, monkeypatch):
    """Verify that failed ffmpeg execution removes partial output and returns None."""
    orig_file = tmp_path / "clip_fail.mp4"
    orig_file.write_bytes(b"sample_bytes")

    def fake_failed_run(cmd, *args, **kwargs):
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"corrupt")
        proc = MagicMock()
        proc.returncode = 1
        proc.stderr = "Encoder error"
        return proc

    monkeypatch.setattr(mm, "_which", lambda b: "fake_ffmpeg")
    monkeypatch.setattr(mm, "probe_video_meta", lambda p: {"width": 1920, "height": 1080})
    monkeypatch.setattr(subprocess, "run", fake_failed_run)

    res = mm.transcode_video_high_quality(orig_file)
    assert res is None
    # Partial out file must be deleted
    assert not (tmp_path / "clip_fail_web.mp4").exists()


# ---------------------------------------------------------------------------
# 2. WebP Image Thumbnail Generation & Dimension Constraints Tests
# ---------------------------------------------------------------------------

def test_image_thumbnail_landscape_dimensions(tmp_path):
    """Verify landscape image (1920x1080) scales to max dimension 720px maintaining aspect ratio."""
    src = tmp_path / "landscape.jpg"
    im = Image.new("RGB", (1920, 1080), color=(10, 50, 90))
    im.save(src, format="JPEG", quality=90)

    dest = tmp_path / "landscape_thumb.webp"
    res = mm.generate_image_thumbnail(src, dest, max_dim=720, quality=80)
    assert res is not None
    assert dest.is_file()

    with Image.open(dest) as thumb:
        assert thumb.format == "WEBP"
        w, h = thumb.size
        assert max(w, h) == 720
        assert w == 720
        assert h == 405  # 16:9 ratio preserved


def test_image_thumbnail_portrait_dimensions(tmp_path):
    """Verify portrait image (1080x1920) scales to max dimension 720px."""
    src = tmp_path / "portrait.png"
    im = Image.new("RGB", (1080, 1920), color=(90, 50, 10))
    im.save(src, format="PNG")

    dest = tmp_path / "portrait_thumb.webp"
    res = mm.generate_image_thumbnail(src, dest, max_dim=720, quality=80)
    assert res is not None

    with Image.open(dest) as thumb:
        assert thumb.format == "WEBP"
        w, h = thumb.size
        assert max(w, h) == 720
        assert h == 720
        assert w == 405


def test_image_thumbnail_rgba_transparency_handling(tmp_path):
    """Verify RGBA transparent images convert cleanly to WebP without crashing."""
    src = tmp_path / "alpha.png"
    im = Image.new("RGBA", (800, 800), color=(255, 0, 0, 128))
    im.save(src, format="PNG")

    dest = tmp_path / "alpha_thumb.webp"
    res = mm.generate_image_thumbnail(src, dest, max_dim=720, quality=80)
    assert res is not None

    with Image.open(dest) as thumb:
        assert thumb.format == "WEBP"
        assert thumb.size == (720, 720)


def test_image_thumbnail_auto_creates_parent_dir(tmp_path):
    """Verify destination directory is created automatically if missing."""
    src = tmp_path / "src.jpg"
    Image.new("RGB", (100, 100), color=(100, 100, 100)).save(src, format="JPEG")

    dest = tmp_path / "nested" / "subfolder" / "thumb.webp"
    assert not dest.parent.exists()

    res = mm.generate_image_thumbnail(src, dest, max_dim=720, quality=80)
    assert res is not None
    assert dest.is_file()


# ---------------------------------------------------------------------------
# 3. Video Poster Thumbnail Extraction Tests
# ---------------------------------------------------------------------------

def test_video_poster_extraction_at_one_second(tmp_path, monkeypatch):
    """Verify video poster extracts frame at 1s into compact WebP thumbnail."""
    video_path = tmp_path / "movie.mp4"
    video_path.write_bytes(b"dummy_video_stream")
    dest_thumb = tmp_path / "movie_thumb.webp"

    # Simulated 1920x1080 frame extracted via ffmpeg pipe
    buf = io.BytesIO()
    Image.new("RGB", (1920, 1080), color=(30, 60, 90)).save(buf, format="PNG")
    frame_bytes = buf.getvalue()

    executed_cmds = []

    def fake_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = frame_bytes
        return proc

    monkeypatch.setattr(mm, "_which", lambda b: "fake_ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    res = mm.generate_video_thumbnail(video_path, dest_thumb, max_dim=720, quality=80)
    assert res is not None
    assert dest_thumb.is_file()

    # Check seek parameters in first command
    cmd1 = executed_cmds[0]
    assert "-ss" in cmd1
    assert cmd1[cmd1.index("-ss") + 1] == "00:00:01.000"
    assert "-vframes" in cmd1
    assert cmd1[cmd1.index("-vframes") + 1] == "1"

    # Check resulting WebP thumbnail
    with Image.open(dest_thumb) as thumb:
        assert thumb.format == "WEBP"
        assert max(thumb.size) == 720
        assert thumb.size == (720, 405)


def test_video_poster_extraction_fallback_for_short_video(tmp_path, monkeypatch):
    """Verify fallback seek to 0s when video is shorter than 1s."""
    video_path = tmp_path / "short_clip.mp4"
    video_path.write_bytes(b"short_video_stream")
    dest_thumb = tmp_path / "short_clip_thumb.webp"

    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color=(70, 20, 40)).save(buf, format="PNG")
    valid_frame = buf.getvalue()

    executed_cmds = []

    def fake_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        proc = MagicMock()
        if "00:00:01.000" in cmd:
            # First seek fails (video too short)
            proc.returncode = 1
            proc.stdout = b""
        else:
            # Fallback to 0s succeeds
            proc.returncode = 0
            proc.stdout = valid_frame
        return proc

    monkeypatch.setattr(mm, "_which", lambda b: "fake_ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    res = mm.generate_video_thumbnail(video_path, dest_thumb, max_dim=720, quality=80)
    assert res is not None
    assert dest_thumb.is_file()

    assert len(executed_cmds) == 2
    assert executed_cmds[0][executed_cmds[0].index("-ss") + 1] == "00:00:01.000"
    assert executed_cmds[1][executed_cmds[1].index("-ss") + 1] == "00:00:00.000"


# ---------------------------------------------------------------------------
# 4. Legacy Memory Thumbnail Fallback & On-Demand Handling Tests
# ---------------------------------------------------------------------------

def test_legacy_memory_on_demand_thumbnail_creation(client: TestClient):
    """Verify legacy memory with missing thumbnail file creates thumbnail on demand when requested."""
    token = _gate_session(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Upload test image
    buf = io.BytesIO()
    Image.new("RGB", (1000, 800), color=(150, 75, 25)).save(buf, format="JPEG")
    up = client.post(
        "/api/events/qa-night/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("legacy_test.jpg", io.BytesIO(buf.getvalue()), "image/jpeg"))],
        headers=headers,
    )
    assert up.status_code == 200
    item_id = up.json()["results"][0]["id"]

    # Approve item via admin
    admin_auth = _admin_auth(client)
    mod_resp = client.post("/api/admin/memories/moderate", json={"ids": [item_id], "status": "approved"}, headers=admin_auth)
    assert mod_resp.status_code == 200

    # Delete thumbnail from disk to simulate legacy un-thumbnailed file
    db = client._TestingSession()
    try:
        item = db.get(MemoryItem, item_id)
        media_path = mm.find_existing_media_path(item.stored_name)
        assert media_path is not None
        thumb_path = media_path.with_name(f"{media_path.stem}_thumb.webp")
        if thumb_path.exists():
            thumb_path.unlink()
        assert not thumb_path.exists()
    finally:
        db.close()

    # Public request to /api/memories/file/{id}/thumb triggers on-demand generation
    resp = client.get(f"/api/memories/file/{item_id}/thumb")
    assert resp.status_code == 200
    assert "image/webp" in resp.headers["content-type"]
    assert "public, max-age=" in resp.headers.get("cache-control", "")

    # Thumbnail now exists on disk
    assert thumb_path.is_file()
    with Image.open(thumb_path) as thumb:
        assert thumb.format == "WEBP"
        assert max(thumb.size) == 720


def test_thumbnail_endpoint_security_and_permissions(client: TestClient):
    """Verify unapproved item thumbnail cannot be viewed anonymously but can by ticket owner."""
    token = _gate_session(client)
    headers = {"Authorization": f"Bearer {token}"}

    buf = io.BytesIO()
    Image.new("RGB", (400, 400), color=(30, 30, 30)).save(buf, format="JPEG")
    up = client.post(
        "/api/events/qa-night/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("pending_test.jpg", io.BytesIO(buf.getvalue()), "image/jpeg"))],
        headers=headers,
    )
    assert up.status_code == 200
    item_id = up.json()["results"][0]["id"]

    # Anonymous access to pending item thumbnail -> 404
    anon_resp = client.get(f"/api/memories/file/{item_id}/thumb")
    assert anon_resp.status_code == 404

    # Owner access with valid bearer token -> 200
    owner_resp = client.get(f"/api/memories/file/{item_id}/thumb", headers=headers)
    assert owner_resp.status_code == 200
    assert "image/webp" in owner_resp.headers["content-type"]


def test_backfill_thumbnails_service(client: TestClient):
    """Verify backfill_thumbnails function generates thumbnails for un-thumbnailed items."""
    token = _gate_session(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Upload two items
    buf = io.BytesIO()
    Image.new("RGB", (500, 500), color=(10, 80, 20)).save(buf, format="JPEG")
    up = client.post(
        "/api/events/qa-night/memories/upload",
        data={"consentPublish": "true"},
        files=[
            ("files", ("bf1.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")),
            ("files", ("bf2.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")),
        ],
        headers=headers,
    )
    assert up.status_code == 200
    item_ids = [r["id"] for r in up.json()["results"]]

    # Delete their thumbnail files
    db = client._TestingSession()
    try:
        for i_id in item_ids:
            item = db.get(MemoryItem, i_id)
            p = mm.find_existing_media_path(item.stored_name)
            t = p.with_name(f"{p.stem}_thumb.webp")
            if t.exists():
                t.unlink()
            assert not t.exists()

        # Run backfill
        stats = mm.backfill_thumbnails(db)
        assert stats["total"] >= 2
        assert stats["created"] >= 2
        assert stats["failed"] == 0

        # Verify files were created
        for i_id in item_ids:
            item = db.get(MemoryItem, i_id)
            p = mm.find_existing_media_path(item.stored_name)
            assert p.with_name(f"{p.stem}_thumb.webp").is_file()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. Frontend memories.html & Lightbox Verification
# ---------------------------------------------------------------------------

def test_memories_html_gallery_grid_loads_only_thumbnails():
    """Verify memories.html loads only thumbnails in initial grid and sets lazy loading."""
    html_path = ROOT / "memories.html"
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")

    # Uses getThumbnailUrl helper
    assert "function getThumbnailUrl(item)" in html
    assert "item.thumb_url || item.thumbUrl" in html

    # Initial grid cards use loading="lazy", decoding="async", explicit dimensions
    assert 'img.loading = \'lazy\'' in html or 'loading="lazy"' in html
    assert 'img.decoding = \'async\'' in html
    assert "img.width = 300" in html
    assert "img.height = 300" in html
    assert "img.style.aspectRatio = '1 / 1'" in html


def test_memories_html_no_download_button():
    """Verify STRICTLY NO download button exists in memories.html or wwh-lightbox.js."""
    html_path = ROOT / "memories.html"
    html = html_path.read_text(encoding="utf-8")
    js_path = ROOT / "assets" / "wwh-lightbox.js"
    js = js_path.read_text(encoding="utf-8")

    # No download attributes or buttons
    assert "download=" not in html.lower()
    assert "download=" not in js.lower()
    assert "nodownload" in js
    assert "controlsList" in js
    assert "disablePictureInPicture" in js


def test_memories_html_skeleton_loading_and_error_retry():
    """Verify 6-item skeleton loading, zero CLS, and Gothic error retry button."""
    html_path = ROOT / "memories.html"
    html = html_path.read_text(encoding="utf-8")
    css_path = ROOT / "assets" / "wwh-theme.css"
    css = css_path.read_text(encoding="utf-8")

    # Skeleton function renders 6 cards
    assert "function renderGallerySkeleton(count)" in html
    assert "count = count || 6" in html
    assert "mem-card--skeleton" in html
    assert "wwh-skeleton-fade" in html

    # Error element and retry button
    assert 'id="gallery-error"' in html
    assert 'id="gallery-retry-btn"' in html
    assert "تلاش مجدد" in html
    assert "galleryRetryBtn.addEventListener('click'" in html

    # CSS styles for skeleton and gothic error
    assert ".mem-card--skeleton" in css
    assert ".wwh-gallery-error" in css
    assert ".wwh-gallery-error__retry" in css


def test_lightbox_keyboard_and_touch_navigation():
    """Verify lightbox supports keyboard navigation (Left/Right) and mobile touch swipe."""
    js_path = ROOT / "assets" / "wwh-lightbox.js"
    js = js_path.read_text(encoding="utf-8")

    # Keyboard arrow navigation
    assert "ArrowLeft" in js
    assert "ArrowRight" in js
    assert "Escape" in js

    # Touch swipe pointer binding
    assert "function bindPointer(el)" in js
    assert "pointerdown" in js or "onDown" in js
    assert "pointermove" in js or "onMove" in js
    assert "pointerup" in js or "onUp" in js

    # Request high-res original on demand
    assert "function renderItem(" in js
    assert "slide.appendChild(v)" in js or "slide.appendChild(img)" in js
