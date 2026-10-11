import os
import tempfile
from pathlib import Path

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
    from datetime import datetime, timezone

    ev = Event(
        slug="test-ev",
        title="Test",
        event_at=datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
        capacity=2,
        ticket_price=1000,
        status="sales_open",
        sales_status="open",
        payment_card_number="123",
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
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_static_theme_assets(client: TestClient):
    r = client.get("/assets/wwh-theme.css")
    assert r.status_code == 200
    assert "--color-accent" in r.text
    r2 = client.get("/assets/wwh-landing.js")
    assert r2.status_code == 200
    assert client.get("/assets/wwh-datetime.js").status_code == 200
    assert client.get("/assets/wwh-hero.css").status_code == 200
    assert client.get("/assets/wwh-scroll.js").status_code == 200
    assert client.get("/assets/wwh-atmosphere.css").status_code == 200
    assert client.get("/assets/wwh-spotlight.js").status_code == 200
    assert client.get("/assets/wwh-loader.css").status_code == 200
    assert client.get("/assets/wwh-loader.js").status_code == 200
    assert client.get("/assets/wwh-fish.js").status_code == 200

def test_register_gone(client: TestClient):
    r = client.post("/api/register", json={})
    assert r.status_code == 410


def test_landing(client: TestClient):
    r = client.get("/api/landing")
    assert r.status_code == 200
    data = r.json()
    assert data["featured"] is True


def test_admin_events_include_edit_fields(client: TestClient):
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/admin/events", headers=headers)
    assert r.status_code == 200
    ev = r.json()["events"][0]
    for key in (
        "setlistJson",
        "paymentCardNumber",
        "ticketPrice",
        "salesStatus",
        "description",
    ):
        assert key in ev


def test_approve_idempotent(client: TestClient):
    login = client.post("/api/admin/login", json={"password": "test-admin-pass"})
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    order_body = {
        "phone": "09123456789",
        "names": ["Ali"],
        "receiptText": "paid",
    }
    created = client.post("/api/orders", json=order_body)
    assert created.status_code == 200 or created.status_code == 201
    oid = created.json()["orderId"]
    a1 = client.post(f"/api/admin/orders/approve?id={oid}", headers=headers)
    assert a1.status_code == 200
    a2 = client.post(f"/api/admin/orders/approve?id={oid}", headers=headers)
    assert a2.status_code == 200
    assert len(a2.json().get("tickets", [])) >= 1
