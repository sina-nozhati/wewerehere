"""Round-trip tests: admin panel APIs ↔ public landing/payment."""

import base64
import json
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


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="panel-test",
        title="رویداد تست پنل",
        episode_number=9,
        description="desc",
        event_at=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
        city="شهر تست",
        venue="محل تست",
        capacity=10,
        ticket_price=50000,
        payment_card_number="6037-1111",
        payment_card_holder="دارنده تست",
        payment_bank_name="بانک تست",
        status="sales_open",
        sales_status="open",
        setlist_json=json.dumps([{"title": "track one", "artist": "artist a", "duration": "3:30"}]),
        artists_json="[]",
    )
    db.add(ev)
    db.commit()
    db.add(SiteSetting(key=FEATURED_KEY, value=str(ev.id)))
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
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_events_list_matches_db(client: TestClient):
    headers = _auth(client)
    r = client.get("/api/admin/events", headers=headers)
    assert r.status_code == 200
    ev = r.json()["events"][0]
    assert ev["title"] == "رویداد تست پنل"
    assert ev["city"] == "شهر تست"
    assert ev["paymentCardNumber"] == "6037-1111"
    assert "track one" in ev["setlistJson"]


def test_patch_event_reflects_on_landing(client: TestClient):
    headers = _auth(client)
    ev_id = client.get("/api/admin/events", headers=headers).json()["events"][0]["id"]
    setlist = [{"title": "new song", "artist": "band", "duration": "2:00"}]
    patch = client.patch(
        f"/api/admin/events/{ev_id}",
        headers=headers,
        json={
            "slug": "panel-test",
            "title": "عنوان جدید لندینگ",
            "episodeNumber": 9,
            "description": "d",
            "eventAt": "2026-09-01T14:00:00+00:00",
            "city": "اصفهان",
            "venue": "سالن الف",
            "capacity": 10,
            "ticketPrice": 99000,
            "paymentCardNumber": "9999",
            "paymentCardHolder": "علی",
            "paymentBankName": "ملی",
            "paymentInstructions": "",
            "setlistJson": json.dumps(setlist),
            "artistsJson": "[]",
            "status": "sales_open",
            "salesStatus": "open",
        },
    )
    assert patch.status_code == 200
    landing = client.get("/api/landing").json()
    assert landing["featured"] is True
    event = landing["event"]
    assert event["title"] == "عنوان جدید لندینگ"
    assert event["city"] == "اصفهان"
    assert event["venue"] == "سالن الف"
    assert event["setlist"][0]["title"] == "new song"
    pay = client.get("/api/payment-info").json()
    assert pay["cardNumber"] == "9999"
    assert pay["price"] == 99000


def test_settings_put_syncs_payment(client: TestClient):
    headers = _auth(client)
    ev_id = client.get("/api/admin/events", headers=headers).json()["events"][0]["id"]
    put = client.put(
        "/api/admin/settings",
        headers=headers,
        json={
            "card_number": "1111222233334444",
            "card_holder": "از تنظیمات",
            "bank_name": "پاسارگاد",
            "ticket_price": "120000",
            "eventId": ev_id,
        },
    )
    assert put.status_code == 200
    s = client.get(f"/api/admin/settings?eventId={ev_id}", headers=headers).json()
    assert s["card_number"] == "1111222233334444"
    assert client.get("/api/payment-info").json()["price"] == 120000


def test_parse_event_at_keeps_tehran_wall_clock():
    from app.services.events import parse_event_at

    naive = parse_event_at("2026-10-11T20:00:00")
    offset = parse_event_at("2026-10-11T20:00:00+03:30")
    assert naive.astimezone(timezone.utc).hour == 16
    assert naive.astimezone(timezone.utc).minute == 30
    assert offset.astimezone(timezone.utc).hour == 16
    assert offset.astimezone(timezone.utc).minute == 30


def test_sales_close_blocks_landing_gate(client: TestClient):
    headers = _auth(client)
    ev_id = client.get("/api/admin/events", headers=headers).json()["events"][0]["id"]
    client.post(f"/api/admin/events/{ev_id}/close-sales", headers=headers)
    landing = client.get("/api/landing").json()["event"]
    assert landing["salesStatus"] == "closed"


def test_admin_receipt_image_with_auth(client: TestClient, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    headers = _auth(client)
    ev_id = client.get("/api/admin/events", headers=headers).json()["events"][0]["id"]
    png_head = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x00])
    created = client.post(
        f"/api/events/{ev_id}/orders",
        json={
            "phone": "09129998877",
            "names": ["رسید"],
            "receiptText": "",
            "receiptImage": {"mime": "image/png", "data": base64.b64encode(png_head).decode("ascii")},
        },
    )
    assert created.status_code in (200, 201)
    oid = created.json()["orderId"]
    assert client.get(f"/api/admin/receipts/{oid}").status_code == 401
    img = client.get(f"/api/admin/receipts/{oid}", headers=headers)
    assert img.status_code == 200
    assert img.content[:8] == png_head[:8]


def test_admin_ticket_and_orders_scope(client: TestClient):
    headers = _auth(client)
    ev_id = client.get("/api/admin/events", headers=headers).json()["events"][0]["id"]
    created = client.post(
        "/api/admin/tickets",
        headers=headers,
        json={"name": "Tester", "phone": "09121111111", "serial": "1234", "group": "A", "eventId": ev_id},
    )
    assert created.status_code == 200
    tickets = client.get(f"/api/admin/tickets?eventId={ev_id}", headers=headers).json()["tickets"]
    assert any(t["serial"] == "1234" for t in tickets)
    order = client.post(
        "/api/orders",
        json={"phone": "09122222222", "names": ["Z"], "receiptText": "ok", "eventId": ev_id},
    )
    assert order.status_code in (200, 201)
    orders = client.get(f"/api/admin/orders?eventId={ev_id}", headers=headers).json()
    assert any(o["phone"] == "09122222222" for o in orders["orders"])
