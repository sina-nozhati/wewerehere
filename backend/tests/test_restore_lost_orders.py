"""Tests for Event 3 lost orders and tickets restoration."""

import os
import sqlite3
import tempfile
import pytest

from scripts.restore_lost_orders import run_restore


@pytest.fixture
def mock_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)

    con = sqlite3.connect(path)
    cur = con.cursor()

    # Create tables
    cur.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            capacity INTEGER DEFAULT 100
        )
    """)
    cur.execute("INSERT INTO events (id, title, capacity) VALUES (3, 'ما اینجا بودیم (Ep. 4)', 100)")

    cur.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            phone TEXT,
            names_json TEXT,
            status TEXT,
            admin_note TEXT,
            wants_physical_card BOOLEAN,
            created_at TIMESTAMP,
            reviewed_at TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE payment_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER UNIQUE,
            text TEXT,
            file_path TEXT,
            submitted_at TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            order_id INTEGER,
            holder_name TEXT,
            phone TEXT,
            public_code TEXT,
            display_number INTEGER,
            group_name TEXT,
            access_token_hash TEXT,
            status TEXT,
            wants_physical_card BOOLEAN,
            issued_at TIMESTAMP
        )
    """)

    # Seed existing 14 tickets (IDs 213-226)
    for i in range(1, 15):
        tid = 212 + i
        cur.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status, wants_physical_card) VALUES (?, 3, 1, 'Guest', '09120000000', ?, ?, 'A', 'hash', 'active', 0)",
            (tid, f"90{i:02d}", i)
        )
    con.commit()
    con.close()

    yield path

    if os.path.exists(path):
        os.remove(path)
    # clean any backups
    for f in os.listdir(tempfile.gettempdir()):
        if f.startswith(os.path.basename(path)) and "before-restore" in f:
            try:
                os.remove(os.path.join(tempfile.gettempdir(), f))
            except Exception:
                pass


def test_dry_run_does_not_modify_db(mock_db):
    run_restore(mock_db, ticket8_name="تست نام", dry_run=True)

    con = sqlite3.connect(mock_db)
    cur = con.cursor()
    cnt = cur.execute("SELECT COUNT(*) FROM tickets WHERE event_id = 3").fetchone()[0]
    con.close()
    assert cnt == 14


def test_apply_inserts_all_6_tickets(mock_db):
    run_restore(mock_db, ticket8_name="نام مهمان هشت", dry_run=False)

    con = sqlite3.connect(mock_db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cnt = cur.execute("SELECT COUNT(*) FROM tickets WHERE event_id = 3").fetchone()[0]
    assert cnt == 20

    # Verify serials
    serials = [r["public_code"] for r in cur.execute("SELECT public_code FROM tickets WHERE event_id = 3 ORDER BY id").fetchall()]
    for s in ["6881", "6452", "2850", "6172", "6720", "0483"]:
        assert s in serials

    # Verify orders
    orders = cur.execute("SELECT * FROM orders").fetchall()
    assert len(orders) == 3

    # Verify receipts
    receipts = cur.execute("SELECT * FROM payment_receipts").fetchall()
    assert len(receipts) == 3

    con.close()
