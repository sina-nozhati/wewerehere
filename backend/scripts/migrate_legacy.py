#!/usr/bin/env python3
"""Migrate legacy Node SQLite schema into multi-event tables."""
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data.sqlite"


def _has_column(conn, table: str, col: str) -> bool:
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def needs_migration(conn) -> bool:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "events" in tables:
        return False
    if "orders" in tables and not _has_column(conn, "orders", "event_id"):
        return True
    if "tickets" in tables and not _has_column(conn, "tickets", "event_id"):
        return True
    return "orders" in tables or "tickets" in tables


def main():
    if not DB.exists():
        print("No data.sqlite — nothing to migrate.")
        return 0

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    if not needs_migration(conn):
        print("No legacy migration needed.")
        conn.close()
        return 0

    print("Backing up to data.sqlite.bak")
    shutil.copy2(DB, DB.with_suffix(".sqlite.bak"))

    legacy = {"settings": [], "orders": [], "tickets": [], "media": []}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "settings" in tables:
        legacy["settings"] = [dict(r) for r in conn.execute("SELECT * FROM settings")]
    if "orders" in tables:
        legacy["orders"] = [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id")]
    if "tickets" in tables:
        legacy["tickets"] = [dict(r) for r in conn.execute("SELECT * FROM tickets ORDER BY id")]
    if "media" in tables:
        legacy["media"] = [dict(r) for r in conn.execute("SELECT * FROM media ORDER BY id")]

    for name in ("tickets", "orders", "media", "settings"):
        if name in tables:
            conn.execute(f"DROP TABLE {name}")
    conn.commit()
    conn.close()

    sys.path.insert(0, str(ROOT / "backend"))
    from app.db import Base, SessionLocal, engine
    from app.models import Event, Media, Order, PaymentReceipt, Ticket
    from app.services.events import set_featured_event_id
    from app.services.tickets import generate_access_token, group_for_code, hash_access_token

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    event = Event(
        slug="third-shahrivar",
        title="ما اینجا بودیم — سوم شهریور",
        episode_number=3,
        description="رویداد موسیقی WE WERE HERE",
        event_at=datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
        city="",
        venue="",
        capacity=50,
        ticket_price=0,
        status="sales_open",
        sales_status="open",
        setlist_json="[]",
        artists_json="[]",
    )
    for row in legacy["settings"]:
        k, v = row.get("key"), row.get("value")
        if k == "card_number":
            event.payment_card_number = v or ""
        elif k == "card_holder":
            event.payment_card_holder = v or ""
        elif k == "bank_name":
            event.payment_bank_name = v or ""
        elif k == "ticket_price":
            try:
                event.ticket_price = int(str(v).replace(",", ""))
            except ValueError:
                pass

    db.add(event)
    db.commit()
    db.refresh(event)
    set_featured_event_id(db, event.id)

    order_map = {}
    for row in legacy["orders"]:
        status = row.get("status") or "pending"
        if status == "pending":
            status = "payment_submitted"
        o = Order(
            id=row["id"],
            event_id=event.id,
            phone=row["phone"],
            names_json=row["names"],
            status=status,
            admin_note=row.get("admin_note") or "",
            created_at=datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            if row.get("created_at")
            else datetime.now(timezone.utc),
            reviewed_at=datetime.fromisoformat(str(row["reviewed_at"]).replace("Z", "+00:00"))
            if row.get("reviewed_at")
            else None,
        )
        db.merge(o)
        db.flush()
        order_map[row["id"]] = o.id
        receipt_text = row.get("receipt_text") or ""
        receipt_img = row.get("receipt_image") or ""
        file_path = f"legacy/receipts/{receipt_img}" if receipt_img else ""
        if receipt_text or file_path:
            db.add(PaymentReceipt(order_id=o.id, text=receipt_text, file_path=file_path))

    db.commit()

    display = 0
    for row in legacy["tickets"]:
        display += 1
        serial = row["serial"]
        token = generate_access_token()
        oid = row.get("order_id")
        t = Ticket(
            event_id=event.id,
            order_id=order_map.get(oid) if oid else None,
            holder_name=row["name"],
            phone=row["phone"],
            public_code=serial,
            display_number=display,
            group_name=row.get("group_name") or group_for_code(serial),
            access_token_hash=hash_access_token(token),
            status="active",
            issued_at=datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            if row.get("created_at")
            else datetime.now(timezone.utc),
        )
        db.add(t)
    db.commit()

    for row in legacy["media"]:
        db.add(
            Media(
                id=row["id"],
                event_id=event.id,
                filename=row["filename"],
                original_name=row.get("original_name") or "",
                mime=row["mime"],
                size=row.get("size") or 0,
                caption=row.get("caption") or "",
                access_level="archive_private",
                created_at=datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
                if row.get("created_at")
                else datetime.now(timezone.utc),
            )
        )
    event_id = event.id
    db.commit()
    db.close()
    print(f"Migrated into event id={event_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
