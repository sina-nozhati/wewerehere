"""Support ticket phone-keyed threads and admin/user replies."""

import os
import tempfile

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
from datetime import datetime, timezone


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="sup-test",
        title="T",
        event_at=datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
        capacity=10,
        ticket_price=1000,
        city="بندر انزلی",
        venue="سالن",
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
        holder_name="آرش صلاحی",
        phone="09121112233",
        public_code="1111",
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


def _support_headers(client: TestClient, phone: str) -> dict[str, str]:
    r = client.post("/api/support/verify", json={"phone": phone})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def test_support_verify_issues_token(client: TestClient):
    r = client.post("/api/support/verify", json={"phone": "09121112233"})
    assert r.status_code == 200
    data = r.json()
    assert data["accessToken"]
    assert data["hasEventTicket"] is True


def test_support_tickets_requires_token(client: TestClient):
    assert client.get("/api/support/tickets").status_code == 401


def test_support_me_requires_token(client: TestClient):
    assert client.get("/api/support/me").status_code == 401


def test_support_me_detects_ticket_holder(client: TestClient):
    sh = _support_headers(client, "09121112233")
    r = client.get("/api/support/me", headers=sh)
    assert r.status_code == 200
    data = r.json()
    assert data["hasEventTicket"] is True
    assert data["holderName"] == "آرش صلاحی"
    assert data["ticketCount"] == 1


def test_support_session_deprecated(client: TestClient):
    assert client.get("/api/support/session?phone=09121112233").status_code == 410


def test_support_me_no_ticket(client: TestClient):
    sh = _support_headers(client, "09998887766")
    r = client.get("/api/support/me", headers=sh)
    assert r.status_code == 200
    assert r.json()["hasEventTicket"] is False


def test_support_admin_reply_visible_to_user(client: TestClient):
    sh = _support_headers(client, "09121112233")
    r = client.post(
        "/api/support/tickets",
        headers=sh,
        json={"subject": "سوال", "message": "سلام"},
    )
    assert r.status_code == 200
    ticket_id = r.json()["id"]

    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    rr = client.post(
        f"/api/admin/support/tickets/{ticket_id}/reply",
        headers=headers,
        json={"body": "پاسخ ادمین"},
    )
    assert rr.status_code == 200

    list_r = client.get("/api/support/tickets", headers=sh)
    assert list_r.status_code == 200
    tickets = list_r.json()["tickets"]
    assert len(tickets) == 1
    roles = [m["role"] for m in tickets[0]["messages"]]
    assert "admin" in roles
    assert any(m["body"] == "پاسخ ادمین" for m in tickets[0]["messages"])


def test_support_contact_name_from_ticket(client: TestClient):
    sh = _support_headers(client, "09121112233")
    client.post(
        "/api/support/tickets",
        headers=sh,
        json={"subject": "x", "message": "y"},
    )
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    active = client.get("/api/admin/support/tickets?status=active", headers=headers)
    assert active.status_code == 200
    row = active.json()["tickets"][0]
    assert row["displayName"] == "آرش صلاحی"
    assert row["phone"] == "09121112233"


def test_user_followup_message_on_ticket(client: TestClient):
    sh = _support_headers(client, "09121112233")
    created = client.post(
        "/api/support/tickets",
        headers=sh,
        json={"subject": "t", "message": "اول"},
    ).json()
    tid = created["id"]
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    client.post(f"/api/admin/support/tickets/{tid}/reply", headers=headers, json={"body": "جواب"})

    fu = client.post(
        f"/api/support/tickets/{tid}/messages",
        headers=sh,
        json={"message": "ممنون"},
    )
    assert fu.status_code == 200

    detail = client.get(f"/api/admin/support/tickets/{tid}", headers=headers)
    bodies = [m["body"] for m in detail.json()["messages"]]
    assert "ممنون" in bodies
    assert detail.json()["status"] == "waiting_admin"
