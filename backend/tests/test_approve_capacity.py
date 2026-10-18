"""Approve must not treat the order's own pending hold as blocking capacity."""

from __future__ import annotations

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
        slug="cap-approve",
        title="Cap",
        event_at=datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
        capacity=3,
        ticket_price=1000,
        status="sales_open",
        sales_status="open",
        payment_card_number="123",
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
        yield c, TestingSession, event_id
    app.dependency_overrides.clear()
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


def _admin_headers(client: TestClient) -> dict:
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_approve_when_remaining_zero_only_due_to_own_pending(client):
    """capacity=3, sold=1, this order holds 2 → public remaining=0, approve must succeed."""
    c, SessionLocal, event_id = client
    db = SessionLocal()
    try:
        issue_ticket(db, event_id=event_id, order_id=None, holder_name="Sold", phone="09121111111")
        db.commit()
    finally:
        db.close()

    created = c.post(
        "/api/orders",
        json={"phone": "09122222222", "names": ["A", "B"], "receiptText": "ok", "eventId": event_id},
    )
    assert created.status_code in (200, 201), created.text
    oid = created.json()["orderId"]

    cap = c.get(f"/api/events/{event_id}/capacity")
    assert cap.status_code == 200
    assert cap.json()["remaining"] == 0

    approved = c.post(f"/api/admin/orders/approve?id={oid}", headers=_admin_headers(c))
    assert approved.status_code == 200, approved.text
    assert len(approved.json()["tickets"]) == 2


def test_approve_blocked_when_other_pending_fills_capacity(client):
    """Two pending orders that together exceed free seats — second approve loses."""
    c, SessionLocal, event_id = client
    # capacity 3, no sold yet
    first = c.post(
        "/api/orders",
        json={"phone": "09123333333", "names": ["X", "Y"], "receiptText": "a", "eventId": event_id},
    )
    assert first.status_code in (200, 201)
    second = c.post(
        "/api/orders",
        json={"phone": "09124444444", "names": ["Z", "W"], "receiptText": "b", "eventId": event_id},
    )
    # Second create should fail (only 1 seat left after first's 2 pending) OR succeed if race —
    # with remaining check, second 2-name order should 409.
    assert second.status_code == 409

    # Fill remaining seat with a 1-name order, then try a conflicting larger approve path:
    # sold=0, pending first=2 → remaining=1. Approve first (2) OK. Then create another that
    # can't fit.
    headers = _admin_headers(c)
    ok = c.post(f"/api/admin/orders/approve?id={first.json()['orderId']}", headers=headers)
    assert ok.status_code == 200

    leftover = c.post(
        "/api/orders",
        json={"phone": "09125555555", "names": ["Solo"], "receiptText": "c", "eventId": event_id},
    )
    assert leftover.status_code in (200, 201)
    oid2 = leftover.json()["orderId"]

    # Manually create an overbook scenario: bump capacity down via another pending that was
    # accepted when capacity was higher — simulate by issuing tickets to fill, then approve.
    db = SessionLocal()
    try:
        # Fill last seat as active so only oid2's own hold remains visually "full"
        issue_ticket(db, event_id=event_id, order_id=None, holder_name="Fill", phone="09126666666")
        db.commit()
        ev = db.get(Event, event_id)
        # capacity 3, sold=3 (2 from first approve + Fill), oid2 still pending 1 → remaining=0
        # approving oid2 should 409 because sold already at capacity
        assert ev is not None
    finally:
        db.close()

    blocked = c.post(f"/api/admin/orders/approve?id={oid2}", headers=headers)
    assert blocked.status_code == 409
    body = blocked.json()
    detail = body.get("detail") or body
    err = detail.get("error") if isinstance(detail, dict) else None
    assert err and "ظرفیت" in err
