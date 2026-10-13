"""Active public ticket numbers and balanced A/B issuance."""

import os
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["WW_DISABLE_MIGRATE"] = "1"

from app.db import Base, get_db
from app.main import app
from app.models import Event, SiteSetting, Ticket
from app.services.events import FEATURED_KEY
from app.services.tickets import active_rank_map, issue_ticket, public_number


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="num-test",
        title="Num",
        event_at=datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
        capacity=20,
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
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_public_numbers_compact_after_revoke(client):
    c, SessionLocal, event_id = client
    db = SessionLocal()
    try:
        for i in range(4):
            issue_ticket(
                db,
                event_id=event_id,
                order_id=None,
                holder_name=f"Guest {i}",
                phone=f"091200000{i:02d}",
            )
        db.commit()
        ids = list(db.scalars(select(Ticket.id).where(Ticket.event_id == event_id).order_by(Ticket.id.asc())))
    finally:
        db.close()

    headers = _admin_headers(c)
    for tid in ids[:2]:
        r = c.delete(f"/api/admin/tickets?id={tid}", headers=headers)
        assert r.status_code == 200

    db = SessionLocal()
    try:
        active = db.scalars(
            select(Ticket).where(Ticket.event_id == event_id, Ticket.status == "active")
        ).all()
        ranks = active_rank_map(db, event_id)
        numbers = sorted(public_number(t, ranks) for t in active)
        assert numbers == [1, 2]
        code = active[0].public_code
    finally:
        db.close()

    track = c.get(f"/api/orders/track?serial={code}")
    assert track.status_code == 200
    assert track.json()["tickets"][0]["number"] == 1


def test_issue_four_tickets_balances_groups(client):
    c, SessionLocal, event_id = client
    db = SessionLocal()
    try:
        for i in range(4):
            issue_ticket(
                db,
                event_id=event_id,
                order_id=None,
                holder_name=f"G{i}",
                phone=f"091300000{i:02d}",
            )
        db.commit()
        rows = db.scalars(select(Ticket).where(Ticket.event_id == event_id, Ticket.status == "active")).all()
        count_a = sum(1 for t in rows if t.group_name == "A")
        count_b = sum(1 for t in rows if t.group_name == "B")
        assert abs(count_a - count_b) <= 1
        assert count_a + count_b == 4
    finally:
        db.close()


def test_approve_order_three_names_balanced_groups(client):
    c, SessionLocal, event_id = client
    headers = _admin_headers(c)
    order_body = {
        "phone": "09123456789",
        "names": ["A", "B", "C"],
        "receiptText": "paid",
    }
    created = c.post("/api/orders", json=order_body)
    assert created.status_code in (200, 201)
    oid = created.json()["orderId"]
    approved = c.post(f"/api/admin/orders/approve?id={oid}", headers=headers)
    assert approved.status_code == 200
    groups = [t["group"] for t in approved.json()["tickets"]]
    assert len(groups) == 3
    assert abs(groups.count("A") - groups.count("B")) <= 1


def test_active_rank_map_dense_order(client):
    c, SessionLocal, event_id = client
    db = SessionLocal()
    try:
        t1, _ = issue_ticket(db, event_id=event_id, order_id=None, holder_name="a", phone="09111111111")
        t2, _ = issue_ticket(db, event_id=event_id, order_id=None, holder_name="b", phone="09111111112")
        db.commit()
        t1.status = "revoked"
        db.commit()
        ranks = active_rank_map(db, event_id)
        assert public_number(t2, ranks) == 1
    finally:
        db.close()
