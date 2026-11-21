import os
import sqlite3
import tarfile
import tempfile
import pytest

from scripts.reconcile_db import (
    find_differences,
    inspect_db,
    merge_missing_records,
    _extract_db_from_archive,
)


def _create_sample_db(path: str):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            title TEXT,
            episode_number INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            event_id INTEGER,
            phone TEXT,
            names_json TEXT,
            status TEXT,
            admin_note TEXT DEFAULT '',
            wants_physical_card BOOLEAN DEFAULT 0,
            created_at DATETIME,
            reviewed_at DATETIME
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE payment_receipts (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            text TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            submitted_at DATETIME
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE tickets (
            id INTEGER PRIMARY KEY,
            event_id INTEGER,
            order_id INTEGER,
            holder_name TEXT,
            phone TEXT,
            public_code TEXT,
            display_number INTEGER,
            group_name TEXT,
            access_token_hash TEXT,
            status TEXT,
            wants_physical_card BOOLEAN DEFAULT 0,
            issued_at DATETIME,
            revoked_at DATETIME,
            UNIQUE(event_id, public_code)
        )
        """
    )
    cur.execute("INSERT INTO events (id, title, episode_number) VALUES (1, 'Episode 1', 1)")
    con.commit()
    con.close()


def test_reconcile_diff_and_merge():
    with tempfile.TemporaryDirectory() as tmp_dir:
        backup_db = os.path.join(tmp_dir, "backup.sqlite")
        target_db = os.path.join(tmp_dir, "target.sqlite")

        _create_sample_db(backup_db)
        _create_sample_db(target_db)

        # Populate backup DB: has Order 1 + Ticket 1001 (Ali) + Ticket 1002 (Reza)
        b_con = sqlite3.connect(backup_db)
        b_con.execute(
            "INSERT INTO orders (id, event_id, phone, names_json, status, created_at) "
            "VALUES (1, 1, '09121111111', '[\"Ali\", \"Reza\"]', 'approved', '2026-11-20 12:00:00')"
        )
        b_con.execute(
            "INSERT INTO payment_receipts (id, order_id, text, submitted_at) "
            "VALUES (1, 1, 'receipt text', '2026-11-20 12:00:00')"
        )
        b_con.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status) "
            "VALUES (1, 1, 1, 'Ali', '09121111111', '1001', 1, 'A', 'hash1', 'active')"
        )
        b_con.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status) "
            "VALUES (2, 1, 1, 'Reza', '09121111111', '1002', 2, 'B', 'hash2', 'active')"
        )
        b_con.commit()
        b_con.close()

        # Populate target DB: Order 1 was created TODAY with a different person (Sara) and Ticket 1003
        t_con = sqlite3.connect(target_db)
        t_con.execute(
            "INSERT INTO orders (id, event_id, phone, names_json, status, created_at) "
            "VALUES (1, 1, '09122222222', '[\"Sara\"]', 'approved', '2026-11-21 08:00:00')"
        )
        t_con.execute(
            "INSERT INTO payment_receipts (id, order_id, text, submitted_at) "
            "VALUES (1, 1, 'sara receipt', '2026-11-21 08:00:00')"
        )
        t_con.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status) "
            "VALUES (1, 1, 1, 'Sara', '09122222222', '1003', 1, 'A', 'hash3', 'active')"
        )
        t_con.commit()
        t_con.close()

        # 1. Run find_differences
        src_data = inspect_db(backup_db)
        tgt_data = inspect_db(target_db)
        diff = find_differences(src_data, tgt_data)

        assert len(diff["missing_orders"]) == 1
        assert diff["missing_orders"][0]["phone"] == "09121111111"
        assert len(diff["missing_tickets"]) == 2
        assert {t["public_code"] for t in diff["missing_tickets"]} == {"1001", "1002"}

        # 2. Dry-run
        res_dry = merge_missing_records(backup_db, target_db, diff, dry_run=True)
        assert res_dry["status"] == "dry-run"
        # Verify target DB was not changed
        tgt_check = inspect_db(target_db)
        assert len(tgt_check["orders"]) == 1
        assert len(tgt_check["tickets"]) == 1

        # 3. Apply merge
        res_merge = merge_missing_records(backup_db, target_db, diff, dry_run=False)
        assert res_merge["status"] == "success"
        assert res_merge["inserted_orders"] == 1
        assert res_merge["inserted_tickets"] == 2
        assert res_merge["inserted_receipts"] == 1
        assert os.path.exists(res_merge["safety_backup"])

        # 4. Check target DB has all 2 orders and all 3 tickets!
        tgt_after = inspect_db(target_db)
        assert len(tgt_after["orders"]) == 2
        assert len(tgt_after["tickets"]) == 3
        # Sara and Ali and Reza all exist
        names = {t["holder_name"] for t in tgt_after["tickets"].values()}
        assert names == {"Sara", "Ali", "Reza"}
        # Both orders exist
        phones = {o["phone"] for o in tgt_after["orders"].values()}
        assert phones == {"09121111111", "09122222222"}

        # Order ID collision was safely resolved
        order_ids = set(tgt_after["orders"].keys())
        assert len(order_ids) == 2
        # Check tickets link to valid orders
        for t in tgt_after["tickets"].values():
            assert t["order_id"] in order_ids


def test_reconcile_event_isolation():
    """Verify that --event-id strictly isolates reconciliation and merge to that event."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        backup_db = os.path.join(tmp_dir, "backup.sqlite")
        target_db = os.path.join(tmp_dir, "target.sqlite")

        _create_sample_db(backup_db)
        _create_sample_db(target_db)

        # Backup DB has Event 1 (Order 1, Ticket 1001) AND Event 2 (Order 2, Ticket 2001)
        b_con = sqlite3.connect(backup_db)
        b_con.execute("INSERT INTO events (id, title, episode_number) VALUES (2, 'Episode 2', 2)")
        b_con.execute(
            "INSERT INTO orders (id, event_id, phone, names_json, status, created_at) "
            "VALUES (1, 1, '09121111111', '[\"Ali\"]', 'approved', '2026-10-20 12:00:00')"
        )
        b_con.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status) "
            "VALUES (1, 1, 1, 'Ali', '09121111111', '1001', 1, 'A', 'hash1', 'active')"
        )
        b_con.execute(
            "INSERT INTO orders (id, event_id, phone, names_json, status, created_at) "
            "VALUES (2, 2, '09122222222', '[\"Reza\"]', 'approved', '2026-11-20 12:00:00')"
        )
        b_con.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status) "
            "VALUES (2, 2, 2, 'Reza', '09122222222', '2001', 1, 'A', 'hash2', 'active')"
        )
        b_con.commit()
        b_con.close()

        # Target DB has Event 1 already (Order 1, Ticket 1001), and a NEW order/ticket in Event 2 (Order 3, Ticket 2002)
        t_con = sqlite3.connect(target_db)
        t_con.execute("INSERT INTO events (id, title, episode_number) VALUES (2, 'Episode 2', 2)")
        t_con.execute(
            "INSERT INTO orders (id, event_id, phone, names_json, status, created_at) "
            "VALUES (1, 1, '09121111111', '[\"Ali\"]', 'approved', '2026-10-20 12:00:00')"
        )
        t_con.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status) "
            "VALUES (1, 1, 1, 'Ali', '09121111111', '1001', 1, 'A', 'hash1', 'active')"
        )
        t_con.execute(
            "INSERT INTO orders (id, event_id, phone, names_json, status, created_at) "
            "VALUES (3, 2, '09123333333', '[\"Sara\"]', 'approved', '2026-11-21 08:00:00')"
        )
        t_con.execute(
            "INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status) "
            "VALUES (3, 2, 3, 'Sara', '09123333333', '2002', 2, 'A', 'hash3', 'active')"
        )
        t_con.commit()
        t_con.close()

        src_data = inspect_db(backup_db)
        tgt_data = inspect_db(target_db)

        # 1. Scope strictly to Event 2:
        diff_ev2 = find_differences(src_data, tgt_data, event_id=2)
        assert len(diff_ev2["missing_tickets"]) == 1
        assert diff_ev2["missing_tickets"][0]["public_code"] == "2001"
        assert diff_ev2["missing_tickets"][0]["event_id"] == 2
        assert len(diff_ev2["missing_orders"]) == 1
        assert diff_ev2["missing_orders"][0]["phone"] == "09122222222"
        assert diff_ev2["missing_orders"][0]["event_id"] == 2

        # 2. Scope strictly to Event 1:
        diff_ev1 = find_differences(src_data, tgt_data, event_id=1)
        assert len(diff_ev1["missing_tickets"]) == 0
        assert len(diff_ev1["missing_orders"]) == 0

        # 3. Assert guard: passing diff with wrong event_id triggers AssertionError
        with pytest.raises(AssertionError):
            merge_missing_records(backup_db, target_db, diff_ev2, dry_run=False, event_id=1)

        # 4. Perform merge for Event 2
        res = merge_missing_records(backup_db, target_db, diff_ev2, dry_run=False, event_id=2)
        assert res["status"] == "success"
        assert res["inserted_tickets"] == 1
        assert res["inserted_orders"] == 1

        # 5. Verify target DB:
        final_tgt = inspect_db(target_db)
        # Event 1 unchanged: exactly 1 ticket
        ev1_tickets = [t for t in final_tgt["tickets"].values() if t["event_id"] == 1]
        assert len(ev1_tickets) == 1
        assert ev1_tickets[0]["public_code"] == "1001"

        # Event 2 has both 2001 (restored) and 2002 (newly created today)
        ev2_tickets = [t for t in final_tgt["tickets"].values() if t["event_id"] == 2]
        assert len(ev2_tickets) == 2
        assert {t["public_code"] for t in ev2_tickets} == {"2001", "2002"}

