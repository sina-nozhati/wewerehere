import csv
import io
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
from app.models import Event, Order, SiteSetting, Ticket
from app.services.events import FEATURED_KEY
from app.services.orders import approve_order
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
        slug="csv-test",
        title="رویداد خروجی CSV",
        episode_number=1,
        description="desc",
        event_at=datetime(2026, 11, 25, 18, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="سالن تست",
        capacity=50,
        ticket_price=100000,
        payment_card_number="6037-9999",
        payment_card_holder="علی حسینی",
        payment_bank_name="ملی",
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
        c.testing_session = TestingSession
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
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _get_token(client: TestClient) -> str:
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    return login.json()["token"]


def test_csv_export_empty_404(client: TestClient):
    headers = _auth(client)
    r = client.get("/api/admin/tickets/export-csv", headers=headers)
    assert r.status_code == 404
    detail = r.json().get("detail", {})
    msg = detail.get("message") or r.json().get("message")
    assert "هیچ بلیت/رزروی برای خروجی یافت نشد" in msg


def test_csv_export_with_tables_and_standalone(client: TestClient):
    headers = _auth(client)
    db = client.testing_session()
    eid = client.event_id

    # 1. Create a 4-person table order
    order_4 = Order(
        event_id=eid,
        phone="09121111111",
        names_json=json.dumps(["سارا", "رضا", "نیما", "مریم"], ensure_ascii=False),
        wants_physical_card=True,
        status="payment_submitted",
    )
    db.add(order_4)
    db.commit()
    approve_order(db, order_4.id)
    order_4_id = order_4.id

    # 2. Create a 2-person table order (digital only)
    order_2 = Order(
        event_id=eid,
        phone="09122222222",
        names_json=json.dumps(["علی", "مهسا"], ensure_ascii=False),
        wants_physical_card=False,
        status="payment_submitted",
    )
    db.add(order_2)
    db.commit()
    approve_order(db, order_2.id)
    order_2_id = order_2.id

    # 3. Create a single-person order
    order_1 = Order(
        event_id=eid,
        phone="09123333333",
        names_json=json.dumps(["سینا"], ensure_ascii=False),
        wants_physical_card=True,
        status="payment_submitted",
    )
    db.add(order_1)
    db.commit()
    approve_order(db, order_1.id)
    order_1_id = order_1.id

    # 4. Create an admin standalone ticket without order
    issue_ticket(
        db,
        event_id=eid,
        order_id=None,
        holder_name="مهمان ویژه ادمین",
        phone="09124444444",
        wants_physical_card=False,
    )
    db.commit()
    db.close()

    # Test GET /api/admin/tickets endpoint data enrichment
    r_tickets = client.get("/api/admin/tickets", headers=headers)
    assert r_tickets.status_code == 200
    t_list = r_tickets.json()["tickets"]
    assert len(t_list) == 8  # 4 + 2 + 1 + 1

    # Check that tableType and guestPosition exist in JSON
    sara_ticket = next(t for t in t_list if t["name"] == "سارا")
    assert sara_ticket["tableType"] == "۴ نفره"
    assert sara_ticket["partySize"] == 4
    assert sara_ticket["guestPosition"] == "نفر ۱ از ۴"

    admin_ticket = next(t for t in t_list if t["name"] == "مهمان ویژه ادمین")
    assert admin_ticket["tableType"] == "تک‌نفره"
    assert admin_ticket["orderId"] is None
    assert admin_ticket["tableLabel"] == "تکی (دستی)"

    # Test GET /api/admin/tickets/export-csv
    r_csv = client.get("/api/admin/tickets/export-csv?sortBy=table", headers=headers)
    assert r_csv.status_code == 200
    assert "text/csv" in r_csv.headers["content-type"]
    assert "attachment; filename=" in r_csv.headers["content-disposition"]

    content = r_csv.content.decode("utf-8")
    assert content.startswith("\ufeff")  # Check UTF-8 BOM

    # Parse CSV lines
    reader = list(csv.reader(io.StringIO(content.lstrip("\ufeff"))))
    assert len(reader) == 9  # 1 header + 8 rows

    header = reader[0]
    expected_header = [
        "ردیف",
        "شناسه سفارش / میز",
        "نوع میز / رزرو",
        "تعداد نفرات میز",
        "موقعیت در میز",
        "شماره سریال بلیت",
        "شماره نوبت ورود",
        "نام مهمان",
        "شماره تماس خریدار",
        "گروه سالن",
        "کارت فیزیکی",
        "وضعیت بلیت",
        "تاریخ ثبت",
        "توضیحات و امضای چک‌این",
    ]
    assert header == expected_header

    rows = reader[1:]
    # Check rows grouping: 4-person table should be contiguous
    table_4_rows = [r for r in rows if r[1] == f"میز #{order_4_id}"]
    assert len(table_4_rows) == 4
    for r in table_4_rows:
        assert r[2] == "۴ نفره"
        assert r[3] == "4"
        assert r[8] == "09121111111"
        assert r[10] == "بله"

    assert [r[4] for r in table_4_rows] == ["نفر ۱ از ۴", "نفر ۲ از ۴", "نفر ۳ از ۴", "نفر ۴ از ۴"]
    assert [r[7] for r in table_4_rows] == ["سارا", "رضا", "نیما", "مریم"]

    # Check 2-person table
    table_2_rows = [r for r in rows if r[1] == f"میز #{order_2_id}"]
    assert len(table_2_rows) == 2
    for r in table_2_rows:
        assert r[2] == "۲ نفره"
        assert r[3] == "2"
        assert r[8] == "09122222222"
        assert r[10] == "خیر"

    assert [r[4] for r in table_2_rows] == ["نفر ۱ از ۲", "نفر ۲ از ۲"]
    assert [r[7] for r in table_2_rows] == ["علی", "مهسا"]

    # Check single order
    table_1_rows = [r for r in rows if r[1] == f"میز #{order_1_id}"]
    assert len(table_1_rows) == 1
    assert table_1_rows[0][2] == "تک‌نفره"
    assert table_1_rows[0][3] == "1"
    assert table_1_rows[0][4] == "تک‌نفره"
    assert table_1_rows[0][7] == "سینا"

    # Check standalone admin ticket
    admin_rows = [r for r in rows if r[1] == "تکی (دستی)"]
    assert len(admin_rows) == 1
    assert admin_rows[0][2] == "تک‌نفره"
    assert admin_rows[0][3] == "1"
    assert admin_rows[0][4] == "تک‌نفره"
    assert admin_rows[0][7] == "مهمان ویژه ادمین"


def test_csv_export_physical_only(client: TestClient):
    headers = _auth(client)
    db = client.testing_session()
    eid = client.event_id

    # 4-person table with physical cards
    order_phys = Order(
        event_id=eid,
        phone="09121111111",
        names_json=json.dumps(["پریسا", "امیر"], ensure_ascii=False),
        wants_physical_card=True,
        status="payment_submitted",
    )
    db.add(order_phys)
    db.commit()
    approve_order(db, order_phys.id)

    # 2-person table digital only
    order_digital = Order(
        event_id=eid,
        phone="09122222222",
        names_json=json.dumps(["داوود"], ensure_ascii=False),
        wants_physical_card=False,
        status="payment_submitted",
    )
    db.add(order_digital)
    db.commit()
    approve_order(db, order_digital.id)
    db.close()

    # Query with physicalOnly=true
    r = client.get("/api/admin/tickets/export-csv?physicalOnly=true", headers=headers)
    assert r.status_code == 200
    reader = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
    rows = reader[1:]
    assert len(rows) == 2
    for r in rows:
        assert r[10] == "بله"
        assert r[8] == "09121111111"


def test_csv_export_token_query_param(client: TestClient):
    token = _get_token(client)
    db = client.testing_session()
    eid = client.event_id

    order = Order(
        event_id=eid,
        phone="09125555555",
        names_json=json.dumps(["تست توکن"], ensure_ascii=False),
        wants_physical_card=False,
        status="payment_submitted",
    )
    db.add(order)
    db.commit()
    approve_order(db, order.id)
    db.close()

    # Download without Authorization header, using ?token=
    r = client.get(f"/api/admin/tickets/export-csv?token={token}")
    assert r.status_code == 200
    assert "تست توکن" in r.content.decode("utf-8")


def test_csv_export_sort_by_serial_and_name(client: TestClient):
    headers = _auth(client)
    db = client.testing_session()
    eid = client.event_id

    order = Order(
        event_id=eid,
        phone="09126666666",
        names_json=json.dumps(["بهرام", "آرش"], ensure_ascii=False),
        wants_physical_card=False,
        status="payment_submitted",
    )
    db.add(order)
    db.commit()
    approve_order(db, order.id)
    db.close()

    # Sort by name
    r_name = client.get("/api/admin/tickets/export-csv?sortBy=name", headers=headers)
    assert r_name.status_code == 200
    rows = list(csv.reader(io.StringIO(r_name.content.decode("utf-8"))))[1:]
    names = [r[7] for r in rows]
    assert names == ["آرش", "بهرام"]
