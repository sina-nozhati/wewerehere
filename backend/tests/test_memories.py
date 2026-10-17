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

# Minimal JPEG / PNG blobs
_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e"
    b"\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0"
    b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00"
    b"\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01"
    b"\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01"
    b"\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04"
    b"\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15"
    b"R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZ"
    b"cdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96"
    b"\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5"
    b"\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4"
    b"\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1"
    b"\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00"
    b"?\x00\xfb\xd5o\xff\xd9"
)
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
