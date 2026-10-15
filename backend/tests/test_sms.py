"""SMS notify + admin send endpoints."""

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["WW_DISABLE_MIGRATE"] = "1"
os.environ["SMS_PROVIDER"] = "console"

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Event, SiteSetting
from app.services import notify, sms_ir
from app.services.events import FEATURED_KEY


def _enable_sms(monkeypatch):
    """Re-enable for unit tests of the parked SMS paths."""
    monkeypatch.setattr(notify, "SMS_ENABLED", True)


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="sms-test",
        title="رویداد SMS",
        episode_number=1,
        description="",
        event_at=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="تست",
        capacity=20,
        ticket_price=1000,
        payment_card_number="6037",
        payment_card_holder="تست",
        payment_bank_name="بانک",
        status="sales_open",
        sales_status="open",
        setlist_json="[]",
        artists_json="[]",
    )
    db.add(ev)
    db.commit()
    db.add(SiteSetting(key=FEATURED_KEY, value=str(ev.id)))
    db.commit()
    event_id = ev.id
    db.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.event_id = event_id
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


def test_sms_disabled_by_default():
    assert notify.SMS_ENABLED is False
    out = notify.notify_tickets_issued("09123456789", [{"name": "آنا", "serial": "0001"}])
    assert out.get("disabled") is True
    assert out["sent"] == 0


def test_send_verify_success(monkeypatch):
    class FakeResp:
        status = 200

        def read(self):
            return json.dumps(
                {"status": 1, "message": "موفق", "data": {"messageId": 99, "cost": 1}}
            ).encode()

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeOpener:
        def open(self, req, timeout=10):
            return FakeResp()

    monkeypatch.setattr(sms_ir.urllib.request, "build_opener", lambda *a, **k: FakeOpener())
    out = sms_ir.send_verify(
        mobile="09123456789",
        template_id=100,
        parameters=[{"name": "CODE", "value": "1234"}],
        api_key="k",
    )
    assert out["ok"] is True
    assert out["message_id"] == 99


def test_send_verify_api_fail(monkeypatch):
    class FakeResp:
        status = 200

        def read(self):
            return json.dumps({"status": 0, "message": "fail"}).encode()

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeOpener:
        def open(self, req, timeout=10):
            return FakeResp()

    monkeypatch.setattr(sms_ir.urllib.request, "build_opener", lambda *a, **k: FakeOpener())
    out = sms_ir.send_verify(
        mobile="09123456789",
        template_id=100,
        parameters=[{"name": "CODE", "value": "1234"}],
        api_key="k",
    )
    assert out["ok"] is False
    assert "api_status" in out["failure_kind"]


def test_format_fa_name_list_join_and_truncate():
    assert notify.format_fa_name_list(["آنا"]) == "آنا"
    assert notify.format_fa_name_list(["آنا", "هستی"]) == "آنا و هستی"
    assert notify.format_fa_name_list(["آنا", "هستی", "امیرعلی"]) == "آنا، هستی و امیرعلی"
    long = notify.format_fa_name_list(
        ["نام‌خیلی‌بلندبرایتست", "دوم", "سوم", "چهارم"],
        max_len=25,
    )
    assert len(long) <= 25
    assert "نفر دیگر" in long


def test_approve_sends_one_sms_with_names_and_phone(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    object.__setattr__(settings, "sms_provider", "console")
    object.__setattr__(settings, "sms_ir_template_id_ticket_notify", 12345)
    calls = []

    def fake_dispatch(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "message_id": "console", "provider": "console"}

    monkeypatch.setattr(notify, "send_verify_dispatch", fake_dispatch)
    headers = _auth(client)
    order = client.post(
        "/api/orders",
        json={
            "phone": "09123456789",
            "names": ["آنا", "هستی", "امیرعلی"],
            "receiptText": " رسید تست",
            "eventId": client.event_id,
        },
    )
    assert order.status_code in (200, 201)
    oid = order.json()["orderId"]
    approved = client.post(f"/api/admin/orders/approve?id={oid}", headers=headers)
    assert approved.status_code == 200
    body = approved.json()
    assert body["sms"]["sent"] == 1
    assert body["sms"]["skipped"] is False
    assert len(calls) == 1
    assert calls[0]["mobile"] == "09123456789"
    params = {p["name"]: p["value"] for p in calls[0]["parameters"]}
    assert params["PHONE"] == "09123456789"
    assert params["NAMES"] == "آنا، هستی و امیرعلی"
    assert len(params["NAMES"]) <= 25


def test_sms_send_requires_auth(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    r = client.post("/api/admin/sms/send", json={"phone": "09123456789", "presetId": "ticket", "value": "1"})
    assert r.status_code == 401


def test_sms_send_invalid_phone(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    headers = _auth(client)
    r = client.post(
        "/api/admin/sms/send",
        headers=headers,
        json={"phone": "123", "presetId": "ticket", "value": "hi"},
    )
    assert r.status_code == 400


def test_sms_send_unknown_preset(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    object.__setattr__(settings, "sms_provider", "console")
    monkeypatch.setattr(notify, "list_admin_presets", lambda: [{"id": "ticket", "label": "t", "paramName": "CODE", "templateId": 1}])
    headers = _auth(client)
    r = client.post(
        "/api/admin/sms/send",
        headers=headers,
        json={"phone": "09123456789", "presetId": "nope", "value": "hi"},
    )
    assert r.status_code == 400


def test_sms_presets_ok(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    headers = _auth(client)
    r = client.get("/api/admin/sms/presets", headers=headers)
    assert r.status_code == 200
    assert "presets" in r.json()


def test_sms_endpoints_disabled_without_flag(client: TestClient):
    headers = _auth(client)
    assert client.get("/api/admin/sms/presets", headers=headers).status_code == 503
    assert client.post(
        "/api/admin/sms/send",
        headers=headers,
        json={"phone": "09123456789", "presetId": "ticket", "value": "x"},
    ).status_code == 503


def test_ticket_resend_sms_groups_same_phone(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    object.__setattr__(settings, "sms_provider", "console")
    object.__setattr__(settings, "sms_ir_template_id_ticket_notify", 12345)
    calls = []

    def fake_dispatch(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "message_id": "console", "provider": "console"}

    monkeypatch.setattr(notify, "send_verify_dispatch", fake_dispatch)
    headers = _auth(client)
    phone = "09121112233"
    created_ids = []
    for name in ("آنا", "هستی", "امیرعلی"):
        r = client.post(
            "/api/admin/tickets",
            headers=headers,
            json={"name": name, "phone": phone, "eventId": client.event_id},
        )
        assert r.status_code == 200
        created_ids.append(r.json()["id"])

    # Click any of the three — should group all names into one SMS
    res = client.post(f"/api/admin/tickets/resend-sms?id={created_ids[1]}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["namesCount"] == 3
    assert body["sms"]["sent"] == 1
    assert len(calls) == 1
    params = {p["name"]: p["value"] for p in calls[0]["parameters"]}
    assert params["PHONE"] == phone
    assert params["NAMES"] == "آنا، هستی و امیرعلی"


def test_ticket_resend_sms_revoked_409(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    headers = _auth(client)
    r = client.post(
        "/api/admin/tickets",
        headers=headers,
        json={"name": "تست", "phone": "09120001122", "eventId": client.event_id},
    )
    assert r.status_code == 200
    tid = r.json()["id"]
    deleted = client.delete(f"/api/admin/tickets?id={tid}", headers=headers)
    assert deleted.status_code == 200
    again = client.post(f"/api/admin/tickets/resend-sms?id={tid}", headers=headers)
    assert again.status_code == 409


def test_ticket_resend_sms_requires_auth(client: TestClient, monkeypatch):
    _enable_sms(monkeypatch)
    r = client.post("/api/admin/tickets/resend-sms?id=1")
    assert r.status_code == 401
