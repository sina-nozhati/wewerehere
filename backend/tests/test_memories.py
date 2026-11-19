"""Disposable-camera / night memories API tests."""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["WW_DISABLE_MIGRATE"] = "1"

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Event, MemoryItem, MemorySession, SiteSetting
from app.services import memory_gate
from app.services.events import FEATURED_KEY
from app.services.memory_gate import hash_session_token
from app.services.tickets import issue_ticket

# Valid JPEG / PNG blobs (must open via Pillow after media_guard sanitize)
def _make_jpeg() -> bytes:
    from io import BytesIO as _BIO
    from PIL import Image as _Image

    buf = _BIO()
    _Image.new("RGB", (8, 8), (200, 40, 80)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_png() -> bytes:
    from io import BytesIO as _BIO
    from PIL import Image as _Image

    buf = _BIO()
    _Image.new("RGB", (8, 8), (20, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


_JPEG = _make_jpeg()
_PNG = _make_png()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    memory_gate._gate_attempts.clear()
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "memory_gate_max_attempts", 5)
    monkeypatch.setattr(settings, "memory_max_files_per_ticket", 3)
    monkeypatch.setattr(settings, "memory_max_files_per_request", 2)
    monkeypatch.setattr(settings, "memory_photo_max_mb", 1)
    monkeypatch.setattr(settings, "memory_session_ttl_hours", 12)
    (tmp_path / "memories").mkdir(parents=True, exist_ok=True)

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="night-test",
        title="شب تست",
        episode_number=1,
        event_at=datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="سالن",
        capacity=20,
        ticket_price=0,
        status="sales_open",
        sales_status="open",
    )
    other = Event(
        slug="other-night",
        title="رویداد دیگر",
        episode_number=2,
        event_at=datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="",
        capacity=10,
        ticket_price=0,
        status="sales_open",
        sales_status="open",
    )
    db.add(ev)
    db.add(other)
    db.commit()
    db.refresh(ev)
    db.refresh(other)
    db.add(SiteSetting(key=FEATURED_KEY, value=str(ev.id)))
    issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="مهمان",
        phone="09121112222",
        public_code="1234",
        group_name="A",
    )
    issue_ticket(
        db,
        event_id=other.id,
        order_id=None,
        holder_name="دیگر",
        phone="09123334444",
        public_code="7777",
        group_name="A",
    )
    revoked, _ = issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="لغو",
        phone="09125556666",
        public_code="9999",
        group_name="B",
    )
    revoked.status = "revoked"
    db.commit()
    db.close()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._TestingSession = TestingSession  # type: ignore[attr-defined]
        c._mem_root = tmp_path / "memories"  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    memory_gate._gate_attempts.clear()
    engine.dispose()
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _auth(client: TestClient) -> dict:
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _gate(client: TestClient, serial: str = "1234", slug: str = "night-test"):
    return client.post(f"/api/events/{slug}/memories/gate", json={"serial": serial})


def test_page_route(client: TestClient):
    r = client.get("/events/night-test/memories")
    assert r.status_code == 200
    assert "شبی که اینجا بودیم" in r.text
    assert "گالری شب" in r.text
    assert "آرشیو اجرا" in r.text
    assert "مال من" in r.text
    assert "serial-input" in r.text
    assert "session-bar" in r.text
    assert "change-code-btn" in r.text
    assert "uploads-left-num" in r.text


def test_gate_valid_and_scoped(client: TestClient):
    ok = _gate(client, "1234")
    assert ok.status_code == 200
    body = ok.json()
    assert body["sessionToken"]
    assert body["event"]["slug"] == "night-test"

    # Serial that only exists on another event
    cross = _gate(client, "7777", slug="night-test")
    assert cross.status_code == 403
    assert cross.json()["detail"]["error"] == "code_rejected"

    # Revoked ticket
    rev = _gate(client, "9999")
    assert rev.status_code == 403


def test_gate_invalid_format(client: TestClient):
    r = _gate(client, "12")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_code"


def test_gate_rate_limit(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "memory_gate_max_attempts", 3)
    memory_gate._gate_attempts.clear()
    for _ in range(3):
        r = _gate(client, "0000")
        assert r.status_code == 403
    blocked = _gate(client, "0000")
    assert blocked.status_code == 429


def test_upload_requires_session_and_consent(client: TestClient):
    bare = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("a.jpg", BytesIO(_JPEG), "image/jpeg"))],
    )
    assert bare.status_code == 401

    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    no_consent = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "false"},
        files=[("files", ("a.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    assert no_consent.status_code == 400
    assert no_consent.json()["detail"]["error"] == "consent_required"


def test_upload_pending_not_in_gallery_then_approve(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("shot.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    assert up.status_code == 200
    assert up.json()["accepted"] == 1
    item_id = up.json()["results"][0]["id"]

    gal = client.get("/api/events/night-test/memories/gallery")
    assert gal.status_code == 200
    assert gal.json()["count"] == 0

    assert client.get(f"/api/memories/file/{item_id}").status_code == 404
    assert client.get(f"/api/memories/file/{item_id}", headers=headers).status_code == 200

    admin = _auth(client)
    mod = client.post(
        "/api/admin/memories/moderate",
        json={"ids": [item_id], "status": "approved"},
        headers=admin,
    )
    assert mod.status_code == 200
    assert mod.json()["updated"] == 1

    gal2 = client.get("/api/events/night-test/memories/gallery")
    assert gal2.json()["count"] == 1
    assert gal2.json()["items"][0]["id"] == item_id
    assert client.get(f"/api/memories/file/{item_id}").status_code == 200


def test_reject_hides_from_gallery(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("a.png", BytesIO(_PNG), "image/png"))],
        headers=headers,
    )
    item_id = up.json()["results"][0]["id"]
    admin = _auth(client)
    client.post(
        "/api/admin/memories/moderate",
        json={"ids": [item_id], "status": "rejected"},
        headers=admin,
    )
    assert client.get("/api/events/night-test/memories/gallery").json()["count"] == 0
    assert client.get(f"/api/memories/file/{item_id}").status_code == 404


def test_admin_only_moderation_and_delete(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("a.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    item_id = up.json()["results"][0]["id"]

    assert client.get("/api/admin/memories?status=pending").status_code == 401

    admin = _auth(client)
    listing = client.get("/api/admin/memories?status=pending", headers=admin)
    assert listing.status_code == 200
    assert any(i["id"] == item_id for i in listing.json()["items"])

    db = client._TestingSession()  # type: ignore[attr-defined]
    row = db.get(MemoryItem, item_id)
    stored = row.stored_name
    db.close()
    path = settings.memories_dir / stored
    assert path.is_file()

    deleted = client.delete(f"/api/admin/memories?id={item_id}", headers=admin)
    assert deleted.status_code == 200
    assert not path.is_file()
    assert client.get(f"/api/admin/memories/file/{item_id}", headers=admin).status_code == 404


def test_ticket_quota(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(3):
        r = client.post(
            "/api/events/night-test/memories/upload",
            data={"consentPublish": "true"},
            files=[("files", (f"a{i}.jpg", BytesIO(_JPEG), "image/jpeg"))],
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["accepted"] == 1
    over = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("over.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    assert over.status_code == 403
    assert over.json()["detail"]["error"] == "ticket_quota_exceeded"


def test_session_expired(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    db = client._TestingSession()  # type: ignore[attr-defined]
    row = db.get(MemorySession, hash_session_token(token))
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    db.close()

    sess = client.get(
        "/api/events/night-test/memories/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sess.status_code == 401


def test_reject_svg(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    r = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("x.svg", BytesIO(svg), "image/svg+xml"))],
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 0
    assert r.json()["results"][0]["ok"] is False


def test_gate_returns_archive_session(client: TestClient):
    body = _gate(client).json()
    assert body["sessionToken"]
    assert body.get("archiveSession")
    assert "archiveMedia" in body
    assert isinstance(body["archiveMedia"], list)


def test_mine_lists_own_uploads(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("mine.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    item_id = up.json()["results"][0]["id"]
    mine = client.get("/api/events/night-test/memories/mine", headers=headers)
    assert mine.status_code == 200
    ids = [i["id"] for i in mine.json()["items"]]
    assert item_id in ids
    row = next(i for i in mine.json()["items"] if i["id"] == item_id)
    assert row["status"] == "pending"
    assert "title" in row

    assert client.get("/api/events/night-test/memories/mine").status_code == 401


def test_like_toggle_and_comment_with_display_name(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("like.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    item_id = up.json()["results"][0]["id"]
    admin = _auth(client)
    client.post(
        "/api/admin/memories/moderate",
        json={"ids": [item_id], "status": "approved"},
        headers=admin,
    )
    title = client.put(
        f"/api/admin/memories/title?id={item_id}",
        json={"title": "شب اول"},
        headers=admin,
    )
    assert title.status_code == 200
    assert title.json()["title"] == "شب اول"

    gal = client.get("/api/events/night-test/memories/gallery", headers=headers)
    item = gal.json()["items"][0]
    assert item["title"] == "شب اول"
    assert item["likeCount"] == 0
    assert item["likedByMe"] is False

    like1 = client.post(
        f"/api/events/night-test/memories/{item_id}/like",
        headers=headers,
    )
    assert like1.status_code == 200
    assert like1.json()["liked"] is True
    assert like1.json()["likeCount"] == 1

    like2 = client.post(
        f"/api/events/night-test/memories/{item_id}/like",
        headers=headers,
    )
    assert like2.json()["liked"] is False
    assert like2.json()["likeCount"] == 0

    bad = client.post(
        f"/api/events/night-test/memories/{item_id}/comments",
        json={"displayName": "ا", "body": "سلام"},
        headers=headers,
    )
    assert bad.status_code == 400

    ok = client.post(
        f"/api/events/night-test/memories/{item_id}/comments",
        json={"displayName": "مینا", "body": "چه شبی بود"},
        headers=headers,
    )
    assert ok.status_code == 200
    assert ok.json()["comment"]["displayName"] == "مینا"

    listed = client.get(f"/api/events/night-test/memories/{item_id}/comments")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["comments"][0]["body"] == "چه شبی بود"


def test_ticket_api_includes_event_slug(client: TestClient):
    r = client.get("/api/ticket?serial=1234")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["eventSlug"] == "night-test"
    assert body.get("eventId")

    # Serial that only exists on the non-featured event still resolves with that event's slug
    other = client.get("/api/ticket?serial=7777")
    assert other.status_code == 200
    assert other.json()["found"] is True
    assert other.json()["eventSlug"] == "other-night"


def test_admin_delete_with_likes_and_comments(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("del.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    item_id = up.json()["results"][0]["id"]
    admin = _auth(client)
    client.post(
        "/api/admin/memories/moderate",
        json={"ids": [item_id], "status": "approved"},
        headers=admin,
    )
    client.post(f"/api/events/night-test/memories/{item_id}/like", headers=headers)
    client.post(
        f"/api/events/night-test/memories/{item_id}/comments",
        json={"displayName": "علی", "body": "عالی"},
        headers=headers,
    )
    deleted = client.delete(f"/api/admin/memories?id={item_id}", headers=admin)
    assert deleted.status_code == 200
    assert client.get("/api/events/night-test/memories/gallery").json()["count"] == 0

    listing = client.get("/api/admin/memories?status=all", headers=admin)
    assert listing.status_code == 200
    assert all(i["id"] != item_id for i in listing.json()["items"])


def test_admin_attribution_and_audit(client: TestClient):
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("attr.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    item_id = up.json()["results"][0]["id"]
    admin = _auth(client)
    listing = client.get("/api/admin/memories?status=pending", headers=admin)
    row = next(i for i in listing.json()["items"] if i["id"] == item_id)
    assert row["serial"] == "1234"
    assert row["holderName"]
    assert row.get("uploadedAt")
    assert row.get("source") == "guest"

    client.post(
        "/api/admin/memories/moderate",
        json={"ids": [item_id], "status": "approved"},
        headers=admin,
    )
    audit = client.get("/api/admin/memories/audit?limit=20", headers=admin)
    assert audit.status_code == 200
    actions = [a["action"] for a in audit.json()["items"]]
    assert "upload" in actions
    assert "approve" in actions


def test_publish_archive_to_gallery_and_leaderboard(client: TestClient):
    admin = _auth(client)
    # Multipart archive upload
    up = client.post(
        "/api/admin/media/upload",
        data={"caption": "از آرشیو", "eventId": "1"},
        files={"file": ("arch.jpg", BytesIO(_JPEG), "image/jpeg")},
        headers=admin,
    )
    assert up.status_code == 200
    media_id = up.json()["id"]

    pub = client.post(
        f"/api/admin/media/publish-to-gallery?id={media_id}",
        headers=admin,
    )
    assert pub.status_code == 200
    mem_id = pub.json()["memoryId"]
    assert pub.json()["already"] is False

    gal = client.get("/api/events/night-test/memories/gallery")
    assert gal.status_code == 200
    assert any(i["id"] == mem_id for i in gal.json()["items"])

    again = client.post(
        f"/api/admin/media/publish-to-gallery?id={media_id}",
        headers=admin,
    )
    assert again.status_code == 200
    assert again.json()["already"] is True

    # Like the published item → leaderboard
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    liked = client.post(
        f"/api/events/night-test/memories/{mem_id}/like",
        headers=headers,
        content=b"{}",
    )
    assert liked.status_code == 200
    board = client.get("/api/events/night-test/memories/leaderboard")
    assert board.status_code == 200
    items = board.json()["items"]
    assert len(items) >= 1
    assert items[0]["id"] == mem_id
    assert items[0]["likeCount"] >= 1
    assert items[0]["rank"] == 1

    # Admin row for archive-sourced item
    listing = client.get("/api/admin/memories?status=approved", headers=admin)
    row = next(i for i in listing.json()["items"] if i["id"] == mem_id)
    assert row["source"] == "admin_archive"
    assert row["holderName"] == "آرشیو ادمین"


def test_holder_slug_and_ticket_folder():
    from app.services.memory_media import holder_slug, ticket_folder_name

    assert "عرفان" in holder_slug("عرفان راد") or "راد" in holder_slug("عرفان راد")
    assert ".." not in holder_slug("a/../b")
    assert "/" not in holder_slug("a/b")
    folder = ticket_folder_name(65, "عرفان راد")
    assert folder.startswith("t65_")
    assert " " not in folder


def test_gate_limits_include_video_max_sec(client: TestClient):
    body = _gate(client).json()
    assert "limits" in body
    assert body["limits"]["videoMaxSec"] == settings.memory_video_max_sec
    assert body["limits"]["videoMaxMb"] == settings.memory_video_max_mb


def test_store_memory_file_uses_ticket_folder(client: TestClient):
    from app.services import memory_media as mm
    from app.models import MemoryItem

    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("shot.jpg", BytesIO(_JPEG), "image/jpeg"))],
        headers=headers,
    )
    assert up.status_code == 200
    item_id = up.json()["results"][0]["id"]
    db = client._TestingSession()  # type: ignore[attr-defined]
    try:
        item = db.get(MemoryItem, item_id)
        assert item is not None
        assert "/t" in item.stored_name
        parts = item.stored_name.split("/")
        assert len(parts) == 3
        assert parts[1].startswith("t")
        path = mm.absolute_memory_path(item.stored_name)
        assert path is not None and path.is_file()
    finally:
        db.close()


def test_video_too_long_rejected(client: TestClient, monkeypatch):
    from app.services import memory_media as mm

    # Minimal ftyp/isom so sniff accepts as mp4
    fake_mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2mp41" + (b"\x00" * 64)

    monkeypatch.setattr(mm, "probe_video_duration_sec", lambda path: 90.0)
    monkeypatch.setattr(mm, "transcode_video_720p", lambda path: None)

    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("long.mp4", BytesIO(fake_mp4), "video/mp4"))],
        headers=headers,
    )
    assert up.status_code == 200
    body = up.json()
    assert body["accepted"] == 0
    assert body["results"][0]["error"] == "video_too_long"


def test_video_ok_duration_skips_transcode_gracefully(client: TestClient, monkeypatch):
    from app.services import memory_media as mm

    fake_mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2mp41" + (b"\x00" * 64)
    monkeypatch.setattr(mm, "probe_video_duration_sec", lambda path: 12.0)
    monkeypatch.setattr(mm, "transcode_video_720p", lambda path: None)

    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("ok.mp4", BytesIO(fake_mp4), "video/mp4"))],
        headers=headers,
    )
    assert up.status_code == 200
    assert up.json()["accepted"] == 1
    assert up.json()["results"][0]["durationMs"] == 12000


def test_video_transcode_parameters_and_preserve_original(tmp_path, monkeypatch):
    """Verify video bitrate target >= 12 Mbps tuning, libx264 CRF 18-20, faststart, and preservation."""
    from app.services import memory_media as mm
    from pathlib import Path

    orig_video = tmp_path / "orig_clip.mp4"
    orig_video.write_bytes(b"dummy_original_video_data_12345678")

    captured_cmds = []

    def fake_which(bin_name):
        return "fake_ffmpeg" if "ffmpeg" in bin_name else "fake_ffprobe"

    def fake_probe_meta(path):
        return {"width": 1920, "height": 1080, "duration": 10.0, "fps": 30.0}

    def fake_subprocess_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        # Create output file
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"encoded_web_video_data_high_quality_test" * 10)
        class DummyProc:
            returncode = 0
            stdout = ""
            stderr = ""
        return DummyProc()

    monkeypatch.setattr(mm, "_which", fake_which)
    monkeypatch.setattr(mm, "probe_video_meta", fake_probe_meta)
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    res = mm.transcode_video_high_quality(orig_video)
    assert res is not None
    web_path, mime, size = res
    assert mime == "video/mp4"
    assert web_path.name == "orig_clip_web.mp4"
    # Original file is preserved!
    assert orig_video.is_file()
    assert orig_video.read_bytes() == b"dummy_original_video_data_12345678"

    # Verify command line arguments
    assert len(captured_cmds) == 1
    c = captured_cmds[0]
    assert "-c:v" in c and c[c.index("-c:v") + 1] == "libx264"
    assert "-crf" in c and c[c.index("-crf") + 1] in ("18", "19", "20")
    # Minimum 12 Mbps target for 1080p
    assert "-b:v" in c and c[c.index("-b:v") + 1] == "12M"
    assert "-maxrate" in c and c[c.index("-maxrate") + 1] == "16M"
    assert "-bufsize" in c and c[c.index("-bufsize") + 1] == "24M"
    assert "-pix_fmt" in c and c[c.index("-pix_fmt") + 1] == "yuv420p"
    assert "+faststart" in c
    assert "-c:a" in c and c[c.index("-c:a") + 1] == "aac"
    assert "-b:a" in c and c[c.index("-b:a") + 1] == "192k"

    # Test low-res sensible bitrate adjustment (avoid bloat on small clips)
    captured_cmds.clear()
    monkeypatch.setattr(mm, "probe_video_meta", lambda p: {"width": 640, "height": 360, "duration": 5.0})
    res_low = mm.transcode_video_high_quality(orig_video)
    assert res_low is not None
    c_low = captured_cmds[0]
    assert c_low[c_low.index("-b:v") + 1] == "4M"


def test_image_thumbnail_generation(tmp_path):
    """Verify WebP image thumbnail generation: max dim <= 720px, quality 78-82, compact size."""
    from app.services import memory_media as mm
    from PIL import Image

    src_img = tmp_path / "high_res_photo.jpg"
    img = Image.new("RGB", (2400, 1600), color=(120, 40, 200))
    img.save(src_img, format="JPEG", quality=95)

    dest_thumb = tmp_path / "high_res_photo_thumb.webp"
    res = mm.generate_image_thumbnail(src_img, dest_thumb, max_dim=720, quality=80)
    assert res is not None
    assert dest_thumb.is_file()
    assert dest_thumb.stat().st_size > 0

    with Image.open(dest_thumb) as thumb:
        assert thumb.format == "WEBP"
        w, h = thumb.size
        assert max(w, h) == 720
        assert w == 720
        assert h == 480  # Aspect ratio preserved!


def test_video_poster_thumbnail_extraction(tmp_path, monkeypatch):
    """Verify video poster thumbnail extraction: extracts frame to compact WebP."""
    from app.services import memory_media as mm
    from PIL import Image

    orig_video = tmp_path / "sample_video.mp4"
    orig_video.write_bytes(b"dummy_video_bytes")
    dest_thumb = tmp_path / "sample_video_thumb.webp"

    # Generate a real 1280x720 frame to return via pipe
    frame_buf = BytesIO()
    fimg = Image.new("RGB", (1280, 720), color=(20, 80, 150))
    fimg.save(frame_buf, format="PNG")
    frame_bytes = frame_buf.getvalue()

    def fake_run(cmd, *args, **kwargs):
        class DummyProc:
            returncode = 0
            stdout = frame_bytes
            stderr = ""
        return DummyProc()

    monkeypatch.setattr(mm, "_which", lambda b: "fake_ffmpeg")
    monkeypatch.setattr("subprocess.run", fake_run)

    res = mm.generate_video_thumbnail(orig_video, dest_thumb, max_dim=720, quality=80)
    assert res is not None
    assert dest_thumb.is_file()
    with Image.open(dest_thumb) as thumb:
        assert thumb.format == "WEBP"
        assert max(thumb.size) == 720


def test_gallery_and_mine_expose_thumb_urls_and_serve_thumbnails(client: TestClient):
    """Verify thumbUrl / thumb_url exposed on /api/memories responses and endpoints serve 200 WebP."""
    from PIL import Image

    # 1. Gate and upload image
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}

    img_buf = BytesIO()
    Image.new("RGB", (1600, 1200), color=(50, 100, 150)).save(img_buf, format="JPEG")
    img_bytes = img_buf.getvalue()

    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("mem1.jpg", BytesIO(img_bytes), "image/jpeg"))],
        headers=headers,
    )
    assert up.status_code == 200
    item_id = up.json()["results"][0]["id"]

    # In "mine" list (pending)
    mine = client.get("/api/events/night-test/memories/mine", headers=headers)
    assert mine.status_code == 200
    mine_item = next(x for x in mine.json()["items"] if x["id"] == item_id)
    assert "thumbUrl" in mine_item
    assert "thumb_url" in mine_item
    assert mine_item["thumbUrl"] == f"/api/memories/file/{item_id}/thumb"
    assert mine_item["thumb_url"] == f"/api/memories/file/{item_id}/thumb"

    # Pending item thumbnail accessible by owner ticket
    thumb_resp = client.get(f"/api/memories/file/{item_id}/thumb", headers=headers)
    assert thumb_resp.status_code == 200
    assert "image/webp" in thumb_resp.headers["content-type"]

    # Also test /api/memories/thumb/{id} alias
    thumb_resp_alias = client.get(f"/api/memories/thumb/{item_id}", headers=headers)
    assert thumb_resp_alias.status_code == 200
    assert "image/webp" in thumb_resp_alias.headers["content-type"]

    # Anonymous access to pending item is 404
    assert client.get(f"/api/memories/file/{item_id}/thumb").status_code == 404

    # 2. Approve via admin
    admin = _auth(client)
    mod = client.post(
        "/api/admin/memories/moderate",
        json={"ids": [item_id], "status": "approved"},
        headers=admin,
    )
    assert mod.status_code == 200

    # 3. Check public gallery exposes thumbUrl & thumb_url
    gal = client.get("/api/events/night-test/memories/gallery")
    assert gal.status_code == 200
    gal_item = next(x for x in gal.json()["items"] if x["id"] == item_id)
    assert gal_item["thumbUrl"] == f"/api/memories/file/{item_id}/thumb"
    assert gal_item["thumb_url"] == f"/api/memories/file/{item_id}/thumb"

    # Public anonymous access to approved thumbnail is 200
    pub_thumb = client.get(f"/api/memories/file/{item_id}/thumb")
    assert pub_thumb.status_code == 200
    assert "image/webp" in pub_thumb.headers["content-type"]


def test_legacy_memory_on_demand_thumbnail_and_backfill(client: TestClient):
    """Verify legacy memory without existing thumbnail file auto-generates on-demand and via backfill."""
    from PIL import Image
    from app.services import memory_media as mm
    from app.models import MemoryItem
    from app.db import get_db

    # Upload and approve
    token = _gate(client).json()["sessionToken"]
    headers = {"Authorization": f"Bearer {token}"}

    img_buf = BytesIO()
    Image.new("RGB", (800, 600), color=(90, 10, 40)).save(img_buf, format="JPEG")
    up = client.post(
        "/api/events/night-test/memories/upload",
        data={"consentPublish": "true"},
        files=[("files", ("legacy.jpg", BytesIO(img_buf.getvalue()), "image/jpeg"))],
        headers=headers,
    )
    item_id = up.json()["results"][0]["id"]
    admin = _auth(client)
    client.post("/api/admin/memories/moderate", json={"ids": [item_id], "status": "approved"}, headers=admin)

    # Simulate legacy item by removing its thumbnail file from disk
    db = client._TestingSession()
    try:
        item = db.get(MemoryItem, item_id)
        assert item is not None
        src_path = mm.find_existing_media_path(item.stored_name)
        assert src_path is not None
        thumb_path = src_path.with_name(f"{src_path.stem}_thumb.webp")
        if thumb_path.exists():
            thumb_path.unlink()
        assert not thumb_path.exists()
    finally:
        db.close()

    # Requesting thumbnail on-demand should re-generate it without re-upload!
    resp = client.get(f"/api/memories/file/{item_id}/thumb")
    assert resp.status_code == 200
    assert "image/webp" in resp.headers["content-type"]
    assert thumb_path.exists()

    # Test backfill endpoint
    backfill_resp = client.post("/api/admin/memories/backfill-thumbnails", headers=admin)
    assert backfill_resp.status_code == 200
    assert backfill_resp.json()["ok"] is True
    assert backfill_resp.json()["total"] >= 1

