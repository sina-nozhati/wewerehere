import io
import os
import tempfile
import zipfile
from datetime import datetime, timezone
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
from app.models import Event, Order, Ticket
from app.services.orders import approve_order


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    (tmp_path / "receipts").mkdir(parents=True, exist_ok=True)

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._TestingSession = TestingSession
        yield c
    app.dependency_overrides.clear()
    engine.dispose()
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _create_event(client: TestClient) -> Event:
    db = client._TestingSession()
    try:
        ev = Event(
            slug="physical-test-night",
            title="رویداد تست کارت فیزیکی",
            capacity=100,
            ticket_price=250000,
            status="sales_open",
            sales_status="open",
            event_at=datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc),
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        return ev
    finally:
        db.close()


def _admin_auth(client: TestClient) -> dict:
    from app.config import settings

    res = client.post("/api/admin/login", json={"password": settings.admin_password})
    assert res.status_code == 200
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_order_and_ticket_physical_card_option(client: TestClient):
    ev = _create_event(client)

    # 1. Submit order WITH physical card requested
    resp1 = client.post(
        f"/api/events/{ev.id}/orders",
        json={
            "phone": "09121112233",
            "names": ["مهمان فیزیکی"],
            "receiptText": "کارت فیزیکی می‌خواهم",
            "wantsPhysicalCard": True,
        },
    )
    assert resp1.status_code == 200
    order1_id = resp1.json()["orderId"]

    # 2. Submit order WITHOUT physical card
    resp2 = client.post(
        f"/api/events/{ev.id}/orders",
        json={
            "phone": "09124445566",
            "names": ["مهمان دیجیتال"],
            "receiptText": "فقط دیجیتال",
            "wantsPhysicalCard": False,
        },
    )
    assert resp2.status_code == 200
    order2_id = resp2.json()["orderId"]

    # Verify orders in DB
    db = client._TestingSession()
    try:
        o1 = db.get(Order, order1_id)
        assert o1.wants_physical_card is True

        o2 = db.get(Order, order2_id)
        assert o2.wants_physical_card is False

        # Approve both orders
        approve_order(db, order1_id)
        approve_order(db, order2_id)

        from sqlalchemy import select

        t1 = db.scalar(select(Ticket).where(Ticket.order_id == order1_id))
        assert t1 is not None
        assert t1.wants_physical_card is True

        t2 = db.scalar(select(Ticket).where(Ticket.order_id == order2_id))
        assert t2 is not None
        assert t2.wants_physical_card is False
    finally:
        db.close()

    admin_headers = _admin_auth(client)

    # 3. Check Admin Tickets List returns wantsPhysicalCard
    admin_tickets = client.get(f"/api/admin/tickets?eventId={ev.id}", headers=admin_headers)
    assert admin_tickets.status_code == 200
    tickets = admin_tickets.json()["tickets"]
    assert len(tickets) == 2
    t_phys = next(t for t in tickets if t["name"] == "مهمان فیزیکی")
    t_digi = next(t for t in tickets if t["name"] == "مهمان دیجیتال")
    assert t_phys["wantsPhysicalCard"] is True
    assert t_digi["wantsPhysicalCard"] is False

    # 4. Check Admin Orders List returns wantsPhysicalCard
    admin_orders = client.get(f"/api/admin/orders?eventId={ev.id}", headers=admin_headers)
    assert admin_orders.status_code == 200
    orders = admin_orders.json()["orders"]
    o_phys = next(o for o in orders if o["id"] == order1_id)
    o_digi = next(o for o in orders if o["id"] == order2_id)
    assert o_phys["wantsPhysicalCard"] is True
    assert o_digi["wantsPhysicalCard"] is False

    # 5. Check ZIP Export with physicalOnly=True -> EXPORTS ONLY PHYSICAL TICKET!
    export_phys = client.get(
        f"/api/admin/tickets/export?eventId={ev.id}&physicalOnly=true", headers=admin_headers
    )
    assert export_phys.status_code == 200
    assert export_phys.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(export_phys.content)) as zf:
        names = zf.namelist()
        assert len(names) == 1
        assert "مهمان_فیزیکی" in names[0]
        assert "مهمان_دیجیتال" not in names[0]

    # 6. Check ZIP Export without physicalOnly -> EXPORTS ALL TICKETS
    export_all = client.get(
        f"/api/admin/tickets/export?eventId={ev.id}&physicalOnly=false", headers=admin_headers
    )
    assert export_all.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export_all.content)) as zf:
        names = zf.namelist()
        assert len(names) == 2


def test_physical_tickets_sold_out_toggle_and_rejection(client: TestClient):
    ev = _create_event(client)
    admin_headers = _admin_auth(client)

    # 1. Initially physical tickets are NOT sold out
    landing = client.get(f"/api/events/{ev.slug}").json()
    assert landing.get("physicalTicketsSoldOut") is False

    # 2. Admin toggles physical tickets to sold out
    tog_res = client.post(f"/api/admin/events/{ev.id}/toggle-physical-tickets", headers=admin_headers)
    assert tog_res.status_code == 200
    assert tog_res.json()["physicalTicketsSoldOut"] is True

    # Check via landing payload
    landing2 = client.get(f"/api/events/{ev.slug}").json()
    assert landing2.get("physicalTicketsSoldOut") is True

    # 3. Customer tries to order with physical ticket requested -> 400 rejection
    order_fail = client.post(
        f"/api/events/{ev.id}/orders",
        json={
            "phone": "09129998877",
            "names": ["متقاضی بلیت فیزیکی"],
            "receiptText": "رسید واریز ۱۲۳",
            "wantsPhysicalCard": True,
        },
    )
    assert order_fail.status_code == 400
    assert "کارت فیزیکی" in order_fail.json()["detail"]["error"] or "کارت" in order_fail.json()["detail"]["error"]

    # 4. Customer orders digital ticket (wantsPhysicalCard: False) -> succeeds
    order_ok = client.post(
        f"/api/events/{ev.id}/orders",
        json={
            "phone": "09129998877",
            "names": ["متقاضی بلیت دیجیتال"],
            "receiptText": "رسید واریز ۱۲۳",
            "wantsPhysicalCard": False,
        },
    )
    assert order_ok.status_code == 200
    assert order_ok.json()["status"] == "pending"

    # 5. Admin opens physical tickets again
    open_res = client.post(f"/api/admin/events/{ev.id}/open-physical-tickets", headers=admin_headers)
    assert open_res.status_code == 200
    assert open_res.json()["physicalTicketsSoldOut"] is False

    # 6. Customer can now order with physical ticket requested
    order_retry = client.post(
        f"/api/events/{ev.id}/orders",
        json={
            "phone": "09128887766",
            "names": ["متقاضی جدید فیزیکی"],
            "receiptText": "رسید واریز ۴۵۶",
            "wantsPhysicalCard": True,
        },
    )
    assert order_retry.status_code == 200
    assert order_retry.json()["status"] == "pending"
