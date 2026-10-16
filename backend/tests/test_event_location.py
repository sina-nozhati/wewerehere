"""Event venue coordinates: admin validation + track location gate."""

import os
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["WW_DISABLE_MIGRATE"] = "1"

from app.db import Base, get_db
from app.main import app
from app.models import Event, SiteSetting
from app.services.events import FEATURED_KEY
from app.services.tickets import issue_ticket


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="loc-test",
        title="رویداد نقشه",
        episode_number=1,
        event_at=datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="سالن تست",
        capacity=20,
        ticket_price=1000,
        status="sales_open",
        sales_status="open",
    )
    db.add(ev)
    db.commit()
    db.add(SiteSetting(key=FEATURED_KEY, value=str(ev.id)))
    issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="دارنده",
        phone="09121112222",
        public_code="5555",
        group_name="A",
    )
    db.commit()
    db.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


def _auth(client: TestClient) -> dict:
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _event_patch_base(client: TestClient, headers: dict) -> tuple[int, dict]:
    ev = client.get("/api/admin/events", headers=headers).json()["events"][0]
    body = {
        "slug": ev["slug"],
        "title": ev["title"],
        "episodeNumber": ev.get("episodeNumber"),
        "description": ev.get("description") or "",
        "eventAt": ev["eventAt"],
        "city": ev.get("city") or "",
        "venue": ev.get("venue") or "",
        "hostName": ev.get("hostName") or "",
        "hostVenue": ev.get("hostVenue") or "",
        "capacity": ev["capacity"],
        "ticketPrice": ev["ticketPrice"],
        "paymentCardNumber": ev.get("paymentCardNumber") or "",
        "paymentCardHolder": ev.get("paymentCardHolder") or "",
        "paymentBankName": ev.get("paymentBankName") or "",
        "paymentInstructions": ev.get("paymentInstructions") or "",
        "status": ev["status"],
        "salesStatus": ev["salesStatus"],
        "setlistJson": ev.get("setlistJson") or "[]",
        "artistsJson": ev.get("artistsJson") or "[]",
        "locationLat": None,
        "locationLng": None,
        "locationLabel": "",
        "locationPublished": False,
    }
    return ev["id"], body


def test_admin_rejects_incomplete_coords(client: TestClient):
    headers = _auth(client)
    ev_id, body = _event_patch_base(client, headers)
    body["locationLat"] = 35.7
    body["locationLng"] = None
    r = client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body)
    assert r.status_code == 400
    assert "مختصات" in r.json()["detail"]["error"]


def test_admin_rejects_out_of_range_coords(client: TestClient):
    headers = _auth(client)
    ev_id, body = _event_patch_base(client, headers)
    body["locationLat"] = 95.0
    body["locationLng"] = 51.4
    r = client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body)
    assert r.status_code == 400


def test_admin_saves_location_and_forces_unpublished_without_coords(client: TestClient):
    headers = _auth(client)
    ev_id, body = _event_patch_base(client, headers)
    body["locationLat"] = 35.6892
    body["locationLng"] = 51.389
    body["locationLabel"] = "نزدیک میدان آزادی"
    body["locationPublished"] = True
    r = client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body)
    assert r.status_code == 200
    saved = client.get("/api/admin/events", headers=headers).json()["events"][0]
    assert saved["locationLat"] == pytest.approx(35.6892)
    assert saved["locationLng"] == pytest.approx(51.389)
    assert saved["locationLabel"] == "نزدیک میدان آزادی"
    assert saved["locationPublished"] is True

    # Clearing coords unpublishes even if client sends published=true
    body["locationLat"] = None
    body["locationLng"] = None
    body["locationPublished"] = True
    r2 = client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body)
    assert r2.status_code == 200
    cleared = client.get("/api/admin/events", headers=headers).json()["events"][0]
    assert cleared["locationLat"] is None
    assert cleared["locationPublished"] is False


def test_track_hides_location_when_unpublished(client: TestClient):
    headers = _auth(client)
    ev_id, body = _event_patch_base(client, headers)
    body["locationLat"] = 35.7
    body["locationLng"] = 51.4
    body["locationLabel"] = "مخفی"
    body["locationPublished"] = False
    assert client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body).status_code == 200

    track = client.get("/api/orders/track?serial=5555").json()
    assert track["tickets"]
    assert "location" not in track["event"]


def test_track_hides_location_without_tickets(client: TestClient):
    headers = _auth(client)
    ev_id, body = _event_patch_base(client, headers)
    body["locationLat"] = 35.7
    body["locationLng"] = 51.4
    body["locationLabel"] = "منتشر"
    body["locationPublished"] = True
    assert client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body).status_code == 200

    # Phone with no tickets → orders empty, tickets empty → no location leak
    track = client.get("/api/orders/track?phone=09129998877").json()
    assert track["tickets"] == []
    assert "location" not in track["event"]


def test_track_returns_location_for_ticket_holder_when_published(client: TestClient):
    headers = _auth(client)
    ev_id, body = _event_patch_base(client, headers)
    body["locationLat"] = 35.6892
    body["locationLng"] = 51.389
    body["locationLabel"] = "سالن تست · تهران"
    body["locationPublished"] = True
    assert client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body).status_code == 200

    by_serial = client.get("/api/orders/track?serial=5555").json()
    assert by_serial["tickets"]
    loc = by_serial["event"]["location"]
    assert loc["lat"] == pytest.approx(35.6892)
    assert loc["lng"] == pytest.approx(51.389)
    assert loc["label"] == "سالن تست · تهران"
    assert loc["city"] == "تهران"
    assert loc["venue"]

    by_phone = client.get("/api/orders/track?phone=09121112222").json()
    assert by_phone["event"]["location"]["lat"] == pytest.approx(35.6892)


def test_track_serial_miss_falls_back_to_phone(client: TestClient):
    headers = _auth(client)
    ev_id, body = _event_patch_base(client, headers)
    body["locationLat"] = 35.7
    body["locationLng"] = 51.4
    body["locationLabel"] = "fallback"
    body["locationPublished"] = True
    assert client.patch(f"/api/admin/events/{ev_id}", headers=headers, json=body).status_code == 200

    # Wrong serial alone → empty tickets
    alone = client.get("/api/orders/track?serial=9999").json()
    assert alone["tickets"] == []
    assert "location" not in alone["event"]

    # Wrong serial + correct phone → phone path
    both = client.get("/api/orders/track?serial=9999&phone=09121112222").json()
    assert both["tickets"]
    assert both["tickets"][0]["serial"] == "5555"
    assert both["event"]["location"]["label"] == "fallback"

    # Correct serial wins even if phone also sent
    prefer = client.get("/api/orders/track?serial=5555&phone=09121112222").json()
    assert prefer["tickets"]
    assert prefer["tickets"][0]["serial"] == "5555"
    assert prefer["event"]["location"]
