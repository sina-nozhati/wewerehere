"""Ticket render export, host fields, serial track, support phone."""

import json
import os
import tempfile

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
from app.config import ROOT
from app.services.ticket_render import (
    REQUIRED_TICKET_FIELDS,
    fill_ticket_svg,
    render_ticket_png,
    ticket_png_export_available,
    ticket_template_field_names,
)
from app.services.tickets import issue_ticket
from datetime import datetime, timezone


def _cairo_png_export_available() -> bool:
    return ticket_png_export_available()


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    ev = Event(
        slug="tr-test",
        title="T",
        event_at=datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
        capacity=10,
        ticket_price=1000,
        city="بندر انزلی",
        venue="سالن کنار دریا",
        host_name="میزبان نمونه",
        host_venue="کافه کنار دریا",
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
        holder_name="Guest",
        phone="09123334444",
        public_code="4242",
        group_name="A",
    )
    issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="Guest Two",
        phone="09123334444",
        public_code="4343",
        group_name="B",
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


def test_fill_ticket_svg_has_fields():
    event_at = datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc)
    svg = fill_ticket_svg(
        "A",
        "تست",
        "4242",
        7,
        event_at=event_at,
        venue="سالن کنار دریا",
        city="بندر انزلی",
    )
    assert "4242" in svg
    assert "تست" in svg
    assert svg.count("تست") == 2  # main watermark + entry stub
    assert "Live in بندر انزلی" in svg
    assert "@font-face" in svg and "Vazirmatn" in svg
    assert "سوم شهریور" in svg
    assert "۱۷:۰۰" in svg
    assert "سالن کنار دریا" in svg


def test_fill_ticket_svg_latin_venue_uses_ascii_time():
    event_at = datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc)
    svg = fill_ticket_svg(
        "A",
        "Guest",
        "1111",
        1,
        event_at=event_at,
        venue="Cafe Anzali",
        city="Bandar Anzali",
    )
    assert "17:00" in svg
    assert "۳" not in svg.split("data-field=\"time\"")[1][:80]
    assert "Mehr" in svg or "mehr" in svg.lower()


def test_track_by_serial(client: TestClient):
    r = client.get("/api/orders/track?serial=4242")
    assert r.status_code == 200
    ticket = r.json()["tickets"][0]
    assert ticket["serial"] == "4242"
    assert ticket["date"] == "سوم شهریور"
    assert ticket["time"] == "۱۷:۰۰"
    assert ticket["venue"] == "سالن کنار دریا"


def test_track_phone_returns_all_tickets_when_serial_is_blank(client: TestClient):
    r = client.get("/api/orders/track?phone=09123334444")
    assert r.status_code == 200
    data = r.json()
    assert {ticket["serial"] for ticket in data["tickets"]} == {"4242", "4343"}
    assert data["event"]["isFeatured"] is True


def test_track_scoped_to_event_id(client: TestClient):
    from app.db import get_db
    from app.models import Event, Order, PaymentReceipt
    from sqlalchemy.orm import Session

    override = app.dependency_overrides.get(get_db)
    gen = override()
    db: Session = next(gen)
    try:
        ev2 = Event(
            slug="tr-test-2",
            title="اپیزود دوم",
            episode_number=2,
            event_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            capacity=10,
            ticket_price=1000,
            city="تهران",
            venue="سالن",
            status="sales_open",
            sales_status="open",
        )
        db.add(ev2)
        db.flush()
        order = Order(
            event_id=ev2.id,
            phone="09123334444",
            names_json='["Other"]',
            status="payment_submitted",
        )
        db.add(order)
        db.flush()
        db.add(PaymentReceipt(order_id=order.id, text="pending ep2", file_path=""))
        issue_ticket(
            db,
            event_id=ev2.id,
            order_id=None,
            holder_name="Ep2",
            phone="09123334444",
            public_code="4242",
            group_name="A",
        )
        db.commit()
        ev2_id = ev2.id
    finally:
        try:
            next(gen)
        except StopIteration:
            pass

    featured_phone = client.get("/api/orders/track?phone=09123334444").json()
    assert featured_phone["event"]["isFeatured"] is True
    assert len(featured_phone["tickets"]) == 2

    scoped = client.get(f"/api/orders/track?phone=09123334444&eventId={ev2_id}")
    assert scoped.status_code == 200
    body = scoped.json()
    assert body["event"]["id"] == ev2_id
    assert body["event"]["episodeNumber"] == 2
    assert len(body["orders"]) == 1
    assert body["orders"][0]["status"] == "pending"
    assert len(body["tickets"]) == 1
    assert body["tickets"][0]["serial"] == "4242"

    featured_only = client.get("/api/orders/track?serial=4242").json()
    assert len(featured_only["tickets"]) == 1
    assert featured_only["tickets"][0]["name"] == "Guest"

    ep2_serial = client.get(f"/api/orders/track?serial=4242&eventId={ev2_id}").json()
    assert len(ep2_serial["tickets"]) == 1
    assert ep2_serial["tickets"][0]["name"] == "Ep2"


def test_track_accepts_persian_serial_digits(client: TestClient):
    r = client.get("/api/orders/track?serial=۴۲۴۲")
    assert r.status_code == 200
    assert r.json()["tickets"][0]["serial"] == "4242"


@pytest.mark.skipif(not _cairo_png_export_available(), reason="Cairo library not available")
def test_ticket_can_open_inline_with_current_template(client: TestClient):
    ticket = client.get("/api/orders/track?serial=4242").json()["tickets"][0]
    r = client.get(f'{ticket["printUrl"]}?serial=4242&inline=true')
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("inline;")
    assert r.headers["content-type"].startswith("image/png")


def test_host_on_admin_events(client: TestClient):
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    ev = client.get("/api/admin/events", headers=headers).json()["events"][0]
    assert ev["hostName"] == "میزبان نمونه"
    assert ev["city"] == "بندر انزلی"


@pytest.mark.skipif(not _cairo_png_export_available(), reason="Cairo library not available")
def test_admin_sample_ticket(client: TestClient):
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    r = client.get("/api/admin/tickets/sample", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    disp = r.headers.get("content-disposition", "")
    assert ".png" in disp


def test_admin_tickets_default_active_hides_revoked(client: TestClient):
    from datetime import timezone as tz

    from app.db import get_db
    from sqlalchemy.orm import Session

    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    override = app.dependency_overrides.get(get_db)
    gen = override()
    db: Session = next(gen)
    try:
        t = db.get(Ticket, db.scalars(select(Ticket)).first().id)
        t.status = "revoked"
        t.revoked_at = datetime.now(tz.utc)
        db.commit()
        tid = t.id
    finally:
        try:
            next(gen)
        except StopIteration:
            pass

    active = client.get("/api/admin/tickets", headers=headers).json()["tickets"]
    assert not any(x["id"] == tid for x in active)
    all_rows = client.get("/api/admin/tickets?status=all", headers=headers).json()["tickets"]
    assert any(x["id"] == tid and x["status"] == "revoked" for x in all_rows)


def test_download_rejects_svg_format(client: TestClient):
    ticket = client.get("/api/orders/track?serial=4242").json()["tickets"][0]
    r = client.get(f'{ticket["printUrl"]}?serial=4242&format=svg')
    assert r.status_code == 400
    body = r.json()
    err = body.get("error") or (body.get("detail") or {}).get("error")
    assert err == "svg_not_available"


def test_support_requires_auth(client: TestClient):
    r = client.post("/api/support/tickets", json={"subject": "s", "message": "m"})
    assert r.status_code == 401


def test_ticket_templates_have_required_fields():
    for group in ("A", "B"):
        fields = ticket_template_field_names(group)
        assert REQUIRED_TICKET_FIELDS <= fields


def _layout_spec() -> list[dict]:
    path = ROOT / "design-system" / "we-were-here" / "ticket-field-layout.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_field_coords(svg_name: str) -> dict[str, dict]:
    raw = (ROOT / svg_name).read_text(encoding="utf-8")
    return _parse_field_coords_from_xml(raw)


def _parse_field_coords_from_xml(xml_str: str) -> dict[str, dict]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_str)
    out: dict[str, dict] = {}
    for el in root.iter():
        field = el.attrib.get("data-field")
        if not field:
            continue
        style = el.attrib.get("style") or ""
        out[field] = {
            "x": el.attrib.get("x"),
            "y": el.attrib.get("y"),
            "transform": el.attrib.get("transform"),
            "text-anchor": el.attrib.get("text-anchor"),
            "direction": el.attrib.get("direction"),
            "hidden": "display:none" in style,
        }
    return out


def _baked_sample_paths_in_svg(xml_str: str) -> int:
    import re
    import xml.etree.ElementTree as ET

    start_re = re.compile(r"^m\s*([-\d.]+)\s*,\s*([-\d.]+)", re.I)
    root = ET.fromstring(xml_str)
    count = 0
    for el in root.iter():
        if not el.tag.endswith("path"):
            continue
        if "cls-8" not in el.attrib.get("class", ""):
            continue
        m = start_re.match((el.attrib.get("d") or "").strip())
        if not m:
            continue
        x, y = float(m.group(1)), float(m.group(2))
        if x >= 125 and 58 <= y <= 95:
            count += 1
    return count


def test_ticket_field_layout_matches_spec():
    for entry in _layout_spec():
        live = _parse_field_coords(entry["file"])
        for field, exp in entry["fields"].items():
            assert field in live
            assert live[field]["hidden"] is False
            assert exp["hidden"] is False
            for key in ("x", "y", "transform"):
                if exp[key] is None:
                    assert live[field][key] is None
                else:
                    assert live[field][key] == exp[key]


def test_fill_applies_layout_from_json():
    event_at = datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc)
    for group, svg_file in (("A", "ticket-a.svg"), ("B", "ticket-b.svg")):
        svg = fill_ticket_svg(
            group,
            "تست",
            "4242",
            7,
            event_at=event_at,
            venue="سالن",
            city="شهر",
        )
        live = _parse_field_coords_from_xml(svg)
        spec = next(e for e in _layout_spec() if e["file"] == svg_file)
        for field, exp in spec["fields"].items():
            assert field in live
            for key in ("x", "y", "transform", "text-anchor", "direction"):
                if key in ("x", "y", "transform"):
                    if exp[key] is None:
                        assert live[field][key] is None
                    else:
                        assert live[field][key] == exp[key]
                elif exp.get(key):
                    assert live[field][key] == exp[key]


def test_fill_has_no_baked_sample_paths():
    event_at = datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc)
    for group in ("A", "B"):
        svg = fill_ticket_svg(group, "تست", "1111", 1, event_at=event_at, venue="V", city="C")
        assert _baked_sample_paths_in_svg(svg) == 0


def test_long_venue_keeps_anchor():
    event_at = datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc)
    long_venue = "سالن بسیار بزرگ مول پلاس و فضای باز کنار دریا با نام طولانی"
    svg = fill_ticket_svg("A", "نام", "4242", 1, event_at=event_at, venue=long_venue, city="تهران")
    live = _parse_field_coords_from_xml(svg)
    assert live["venue"]["x"] == "199"
    assert live["venue"]["y"] == "88.75"
    assert live["venue"]["text-anchor"] == "start"
    assert live["venue"]["direction"] == "rtl"
    assert long_venue in svg


def test_name_stub_visible_in_filled_svg():
    svg = fill_ticket_svg("A", "سینا نزهتی", "6925", 12, city="انزلی")
    assert 'data-field="name_stub"' in svg
    stub_slice = svg.split('data-field="name_stub"', 1)[1][:200]
    assert "display:none" not in stub_slice
    assert "سینا نزهتی" in svg
    assert svg.count("سینا نزهتی") == 2


@pytest.mark.skipif(not _cairo_png_export_available(), reason="Cairo library not available")
def test_ticket_png_export_dimensions():
    event_at = datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc)
    svg = fill_ticket_svg(
        "A",
        "Guest",
        "4242",
        1,
        event_at=event_at,
        venue="Venue",
        city="City",
    )
    png = render_ticket_png(svg, scale=4.0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert width == 362 * 4
    assert height == 128 * 4


@pytest.mark.skipif(not _cairo_png_export_available(), reason="Cairo library not available")
def test_ticket_download_returns_png_when_cairo_available(client: TestClient):
    ticket = client.get("/api/orders/track?serial=4242").json()["tickets"][0]
    r = client.get(f'{ticket["printUrl"]}?serial=4242')
    assert r.status_code == 200
    if r.headers["content-type"].startswith("image/png"):
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
