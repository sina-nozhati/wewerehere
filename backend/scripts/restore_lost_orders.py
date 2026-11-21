#!/usr/bin/env python3
"""Restore lost Event 3 orders and tickets safely into data.sqlite.

Features:
- Full pre-flight verification
- Non-destructive: preserves all existing tickets and orders
- Restores original public_codes (6881, 6452, 2850, 6172, 6720, 0483)
- Links existing receipt images in storage/receipts/
- Automatic timestamped backup before apply
- Supports --dry-run and --apply
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def hash_token(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    import secrets
    return secrets.token_hex(24)


def run_restore(
    db_path: str,
    ticket8_name: str = "",
    dry_run: bool = True,
):
    print("=" * 70)
    print("WE WERE HERE — EVENT 3 RESTORATION TOOL")
    print(f"Target DB: {db_path}")
    print(f"Mode: {'[DRY-RUN] No changes will be written' if dry_run else '[APPLY] WRITING TO DATABASE'}")
    print("=" * 70)

    if not os.path.exists(db_path):
        print(f"ERROR: Database file {db_path} does not exist!")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 1. Check Event 3
    ev = cur.execute("SELECT id, title, capacity FROM events WHERE id = 3").fetchone()
    if not ev:
        print("ERROR: Event 3 not found in target database!")
        sys.exit(1)

    print(f"Target Event: ID 3 - {ev['title']} (Capacity: {ev['capacity']})")

    # 2. Check current max IDs
    max_order_id = cur.execute("SELECT COALESCE(MAX(id), 0) as m FROM orders").fetchone()["m"]
    max_ticket_id = cur.execute("SELECT COALESCE(MAX(id), 0) as m FROM tickets").fetchone()["m"]
    max_display_no = cur.execute("SELECT COALESCE(MAX(display_number), 0) as m FROM tickets WHERE event_id = 3").fetchone()["m"]
    current_tickets_count = cur.execute("SELECT COUNT(*) as c FROM tickets WHERE event_id = 3").fetchone()["c"]

    print(f"Current Status: {current_tickets_count} tickets for Event 3 (Max Display No: {max_display_no})")
    print(f"Max Order ID across DB: {max_order_id} | Max Ticket ID across DB: {max_ticket_id}")

    # 3. Check for existing public_codes to prevent collision
    codes_to_restore = ["6881", "6452", "2850", "6172", "6720", "0483"]
    placeholders = ",".join(["?"] * len(codes_to_restore))
    clashes = cur.execute(
        f"SELECT id, public_code, holder_name FROM tickets WHERE event_id = 3 AND public_code IN ({placeholders})",
        codes_to_restore,
    ).fetchall()

    if clashes:
        print("\nWARNING: Some serial codes already exist in Event 3:")
        for cl in clashes:
            print(f"  * Serial {cl['public_code']} already assigned to Ticket #{cl['id']} ({cl['holder_name']})")
        print("Aborting to prevent duplicate serial collision.")
        sys.exit(1)

    # 4. Prepare Orders & Tickets Plan
    t8_name = (ticket8_name or "").strip() or "مهمان رویداد (شماره ۸)"

    recovery_plan = [
        {
            "original_order_id": 117,
            "phone": "09033645669",
            "names": ["محمد دلبر"],
            "wants_physical": 1,
            "created_at": "2026-11-20 19:13:29",
            "receipt_path": "receipts/1a1f9a087a3-117.jpg",
            "receipt_text": "رسید پرداخت کارت به کارت",
            "tickets": [
                {
                    "holder_name": "محمد دلبر",
                    "public_code": "6881",
                    "group_name": "A",
                    "wants_physical": 1,
                    "historical_display_no": 7,
                }
            ],
        },
        {
            "original_order_id": 118,
            "phone": "09378401747",
            "names": [t8_name],
            "wants_physical": 0,
            "created_at": "2026-11-20 19:24:04",
            "receipt_path": "receipts/1a1f9aa369b-118.png",
            "receipt_text": "رسید پرداخت کارت به کارت",
            "tickets": [
                {
                    "holder_name": t8_name,
                    "public_code": "6452",
                    "group_name": "B",
                    "wants_physical": 0,
                    "historical_display_no": 8,
                }
            ],
        },
        {
            "original_order_id": 119,
            "phone": "09116949539",
            "names": ["بیتا عصیانی", "زهرا سیدی", "ارسلان خوشدل", "محمدمهدی حدادی"],
            "wants_physical": 1,
            "created_at": "2026-11-20 23:30:18",
            "receipt_path": "receipts/1a1fa8ba5c4-119.jpg",
            "receipt_text": "رسید پرداخت کارت به کارت",
            "tickets": [
                {
                    "holder_name": "بیتا عصیانی",
                    "public_code": "2850",
                    "group_name": "A",
                    "wants_physical": 1,
                    "historical_display_no": 9,
                },
                {
                    "holder_name": "زهرا سیدی",
                    "public_code": "6172",
                    "group_name": "B",
                    "wants_physical": 1,
                    "historical_display_no": 10,
                },
                {
                    "holder_name": "ارسلان خوشدل",
                    "public_code": "6720",
                    "group_name": "A",
                    "wants_physical": 1,
                    "historical_display_no": 11,
                },
                {
                    "holder_name": "محمدمهدی حدادی",
                    "public_code": "0483",
                    "group_name": "B",
                    "wants_physical": 1,
                    "historical_display_no": 12,
                },
            ],
        },
    ]

    print("\n" + "=" * 70)
    print("RESTORATION PLAN OVERVIEW:")
    print("=" * 70)

    next_order_id = max_order_id + 1
    next_ticket_id = max_ticket_id + 1
    next_display_no = max_display_no + 1

    operations = []

    for o_idx, o in enumerate(recovery_plan, 1):
        assigned_order_id = next_order_id
        next_order_id += 1

        print(f"\n[Order Plan {o_idx}/3] New Order ID: {assigned_order_id} (Hist: {o['original_order_id']})")
        print(f"  Phone: {o['phone']} | Physical: {o['wants_physical']} | Date: {o['created_at']}")
        print(f"  Names: {json.dumps(o['names'], ensure_ascii=False)}")
        print(f"  Receipt: {o['receipt_path']}")

        ticket_records = []
        for t in o["tickets"]:
            assigned_ticket_id = next_ticket_id
            assigned_display_no = next_display_no
            next_ticket_id += 1
            next_display_no += 1

            token = generate_token()
            token_hash = hash_token(token)

            print(f"    * New Ticket ID: {assigned_ticket_id} | Serial: {t['public_code']} | No: #{assigned_display_no} (Hist #{t['historical_display_no']}) | Name: {t['holder_name']} | Group: {t['group_name']} | Physical: {t['wants_physical']}")

            ticket_records.append({
                "id": assigned_ticket_id,
                "event_id": 3,
                "order_id": assigned_order_id,
                "holder_name": t["holder_name"],
                "phone": o["phone"],
                "public_code": t["public_code"],
                "display_number": assigned_display_no,
                "group_name": t["group_name"],
                "access_token_hash": token_hash,
                "status": "active",
                "wants_physical_card": t["wants_physical"],
                "issued_at": o["created_at"],
            })

        operations.append({
            "order": {
                "id": assigned_order_id,
                "event_id": 3,
                "phone": o["phone"],
                "names_json": json.dumps(o["names"], ensure_ascii=False),
                "status": "approved",
                "admin_note": f"Restored lost order from 2026-11-20 (originally order {o['original_order_id']})",
                "wants_physical_card": o["wants_physical"],
                "created_at": o["created_at"],
                "reviewed_at": o["created_at"],
            },
            "receipt": {
                "order_id": assigned_order_id,
                "text": o["receipt_text"],
                "file_path": o["receipt_path"],
                "submitted_at": o["created_at"],
            },
            "tickets": ticket_records,
        })

    total_tickets_to_add = sum(len(op["tickets"]) for op in operations)
    print("\n" + "=" * 70)
    print(f"SUMMARY: 3 Orders, 3 Receipts, and {total_tickets_to_add} Tickets ready to insert.")
    print("=" * 70)

    if dry_run:
        con.close()
        print("\n[DRY RUN FINISHED] Database was NOT modified.")
        print("To execute this restore, run with: --apply")
        return

    # Backup before write
    ts_str = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = f"{db_path}.before-restore-{ts_str}"
    print(f"\n[BACKUP] Creating pre-restore snapshot: {backup_path}")
    shutil.copy2(db_path, backup_path)

    # Perform Inserts in Transaction
    try:
        cur.execute("BEGIN TRANSACTION")
        for op in operations:
            o = op["order"]
            cur.execute(
                """
                INSERT INTO orders (id, event_id, phone, names_json, status, admin_note, wants_physical_card, created_at, reviewed_at)
                VALUES (:id, :event_id, :phone, :names_json, :status, :admin_note, :wants_physical_card, :created_at, :reviewed_at)
                """,
                o,
            )

            r = op["receipt"]
            cur.execute(
                """
                INSERT INTO payment_receipts (order_id, text, file_path, submitted_at)
                VALUES (:order_id, :text, :file_path, :submitted_at)
                """,
                r,
            )

            for t in op["tickets"]:
                cur.execute(
                    """
                    INSERT INTO tickets (id, event_id, order_id, holder_name, phone, public_code, display_number, group_name, access_token_hash, status, wants_physical_card, issued_at)
                    VALUES (:id, :event_id, :order_id, :holder_name, :phone, :public_code, :display_number, :group_name, :access_token_hash, :status, :wants_physical_card, :issued_at)
                    """,
                    t,
                )

        con.commit()
        print("\n[SUCCESS] All records successfully inserted into data.sqlite!")

        # Verify final count
        after_count = cur.execute("SELECT COUNT(*) as c FROM tickets WHERE event_id = 3").fetchone()["c"]
        print(f"[VERIFIED] Event 3 ticket count is now: {after_count} (was {current_tickets_count})")
    except Exception as e:
        con.rollback()
        print(f"\n[ERROR] Transaction failed, rolled back! Error: {e}")
        sys.exit(1)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description="Restore lost Event 3 orders and tickets")
    parser.add_argument("--db", default="/opt/wewerehere/data.sqlite", help="Path to data.sqlite")
    parser.add_argument("--ticket8-name", default="", help="Holder name for ticket #8 (serial 6452)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    run_restore(
        db_path=args.db,
        ticket8_name=args.ticket8_name,
        dry_run=not args.apply,
    )


if __name__ == "__main__":
    main()
