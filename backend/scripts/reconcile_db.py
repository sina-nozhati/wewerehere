#!/usr/bin/env python3
"""We Were Here — Database Reconciliation and Merge Tool.

Inspects SQLite backups (.tar.gz or .sqlite files) vs the active database,
identifies missing orders and tickets, and safely merges them back without
overwriting new tickets or conflicting on primary keys.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _extract_db_from_archive(archive_path: str, temp_dir: str) -> str:
    """Extract data.sqlite (and WAL if present) from a .tar.gz archive into temp_dir."""
    with tarfile.open(archive_path, "r:gz") as tar:
        members = [m for m in tar.getmembers() if "data.sqlite" in m.name]
        if not members:
            raise ValueError(f"No data.sqlite found inside {archive_path}")
        tar.extractall(path=temp_dir, members=members)
        # Find where data.sqlite was placed
        for root, _, files in os.walk(temp_dir):
            if "data.sqlite" in files:
                return os.path.join(root, "data.sqlite")
    raise ValueError(f"Could not locate data.sqlite in extracted {archive_path}")


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _open_sqlite(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = _dict_factory
    # Ensure WAL checkpoint is flushed so all data is visible
    try:
        con.execute("PRAGMA wal_checkpoint(PASSIVE);")
    except sqlite3.Error:
        pass
    return con


def inspect_db(db_path: str) -> dict:
    con = _open_sqlite(db_path)
    try:
        events = con.execute("SELECT id, title, episode_number FROM events").fetchall()
        orders = con.execute("SELECT * FROM orders").fetchall()
        tickets = con.execute("SELECT * FROM tickets").fetchall()
        receipts = con.execute("SELECT * FROM payment_receipts").fetchall()
        return {
            "events": {e["id"]: e for e in events},
            "orders": {o["id"]: o for o in orders},
            "tickets": {t["id"]: t for t in tickets},
            "receipts": {r["id"]: r for r in receipts},
        }
    finally:
        con.close()


def find_differences(source_data: dict, target_data: dict) -> dict:
    """Compare source (backup) against target (current DB).

    Identifies tickets and orders present in source but missing in target.
    """
    target_tickets_by_code = {
        (t["event_id"], str(t["public_code"]).zfill(4)): t
        for t in target_data["tickets"].values()
    }
    target_orders_by_key = {
        (o["event_id"], o["phone"], o["names_json"]): o
        for o in target_data["orders"].values()
    }

    missing_tickets = []
    for t in source_data["tickets"].values():
        code = str(t["public_code"]).zfill(4)
        if (t["event_id"], code) not in target_tickets_by_code:
            missing_tickets.append(t)

    missing_orders = []
    missing_order_ids = set()
    for o in source_data["orders"].values():
        key = (o["event_id"], o["phone"], o["names_json"])
        if key not in target_orders_by_key:
            missing_orders.append(o)
            missing_order_ids.add(o["id"])

    # Collect receipts for missing orders
    missing_receipts = []
    for r in source_data["receipts"].values():
        if r["order_id"] in missing_order_ids:
            missing_receipts.append(r)

    return {
        "missing_tickets": missing_tickets,
        "missing_orders": missing_orders,
        "missing_receipts": missing_receipts,
    }


def format_report(diff: dict, source_name: str, target_name: str) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"RECONCILIATION REPORT: {source_name} vs {target_name}")
    lines.append("=" * 70)
    lines.append(f"Missing Tickets: {len(diff['missing_tickets'])}")
    lines.append(f"Missing Orders:  {len(diff['missing_orders'])}")
    lines.append(f"Missing Receipts: {len(diff['missing_receipts'])}")
    lines.append("-" * 70)

    if diff["missing_tickets"]:
        lines.append("MISSING TICKETS DETAILS:")
        for t in diff["missing_tickets"]:
            lines.append(
                f"  • Event {t['event_id']} | Serial: {t['public_code']} | "
                f"Group: {t.get('group_name')} | Name: {t.get('holder_name')} | "
                f"Phone: {t.get('phone')} | Status: {t.get('status')}"
            )
        lines.append("-" * 70)

    if diff["missing_orders"]:
        lines.append("MISSING ORDERS DETAILS:")
        for o in diff["missing_orders"]:
            lines.append(
                f"  • Order ID {o['id']} (Event {o['event_id']}) | Phone: {o.get('phone')} | "
                f"Names: {o.get('names_json')} | Status: {o.get('status')} | Date: {o.get('created_at')}"
            )
        lines.append("-" * 70)

    return "\n".join(lines)


def merge_missing_records(
    source_db_path: str,
    target_db_path: str,
    diff: dict,
    *,
    dry_run: bool = True,
) -> dict:
    """Safely insert missing orders, receipts, and tickets into target database."""
    if dry_run:
        return {
            "status": "dry-run",
            "orders_to_insert": len(diff["missing_orders"]),
            "tickets_to_insert": len(diff["missing_tickets"]),
            "receipts_to_insert": len(diff["missing_receipts"]),
        }

    # 1. Take a safety backup of target database first
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_copy = f"{target_db_path}.pre-merge-{ts}"
    shutil.copy2(target_db_path, backup_copy)

    target_con = sqlite3.connect(target_db_path)
    target_con.row_factory = _dict_factory
    cursor = target_con.cursor()

    inserted_orders = 0
    inserted_receipts = 0
    inserted_tickets = 0

    try:
        # Check existing max IDs to avoid collision
        max_order_id = cursor.execute("SELECT coalesce(max(id), 0) FROM orders").fetchone()["coalesce(max(id), 0)"]
        max_ticket_id = cursor.execute("SELECT coalesce(max(id), 0) FROM tickets").fetchone()["coalesce(max(id), 0)"]
        max_receipt_id = cursor.execute("SELECT coalesce(max(id), 0) FROM payment_receipts").fetchone()["coalesce(max(id), 0)"]

        # Maps old_order_id -> new_order_id
        order_id_map: dict[int, int] = {}

        # Check existing order IDs in target
        existing_order_ids = {row["id"] for row in cursor.execute("SELECT id FROM orders").fetchall()}
        next_order_id = max_order_id + 1

        for o in diff["missing_orders"]:
            old_id = o["id"]
            if old_id not in existing_order_ids:
                new_id = old_id
            else:
                while next_order_id in existing_order_ids:
                    next_order_id += 1
                new_id = next_order_id
                next_order_id += 1
            existing_order_ids.add(new_id)
            order_id_map[old_id] = new_id

            cursor.execute(
                """
                INSERT INTO orders (id, event_id, phone, names_json, status, admin_note, wants_physical_card, created_at, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    o["event_id"],
                    o["phone"],
                    o["names_json"],
                    o["status"],
                    o.get("admin_note", ""),
                    o.get("wants_physical_card", 0),
                    o["created_at"],
                    o.get("reviewed_at"),
                ),
            )
            inserted_orders += 1

        # Insert missing receipts
        existing_receipt_ids = {row["id"] for row in cursor.execute("SELECT id FROM payment_receipts").fetchall()}
        next_receipt_id = max_receipt_id + 1
        for r in diff["missing_receipts"]:
            old_order_id = r["order_id"]
            target_order_id = order_id_map.get(old_order_id, old_order_id)
            # Make sure order exists
            if target_order_id not in existing_order_ids:
                continue
            if r["id"] not in existing_receipt_ids:
                new_rec_id = r["id"]
            else:
                while next_receipt_id in existing_receipt_ids:
                    next_receipt_id += 1
                new_rec_id = next_receipt_id
                next_receipt_id += 1
            existing_receipt_ids.add(new_rec_id)
            cursor.execute(
                """
                INSERT INTO payment_receipts (id, order_id, text, file_path, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    new_rec_id,
                    target_order_id,
                    r.get("text", ""),
                    r.get("file_path", ""),
                    r.get("submitted_at"),
                ),
            )
            inserted_receipts += 1

        # Insert missing tickets
        existing_ticket_ids = {row["id"] for row in cursor.execute("SELECT id FROM tickets").fetchall()}
        existing_codes = {
            (row["event_id"], str(row["public_code"]).zfill(4))
            for row in cursor.execute("SELECT event_id, public_code FROM tickets").fetchall()
        }
        next_ticket_id = max_ticket_id + 1

        for t in diff["missing_tickets"]:
            code = str(t["public_code"]).zfill(4)
            if (t["event_id"], code) in existing_codes:
                # Code already exists in target; skip to avoid unique constraint clash
                continue

            old_oid = t.get("order_id")
            new_oid = order_id_map.get(old_oid) if old_oid else None
            if old_oid and not new_oid:
                if old_oid in existing_order_ids:
                    new_oid = old_oid
                else:
                    new_oid = None

            if t["id"] not in existing_ticket_ids:
                new_tid = t["id"]
            else:
                while next_ticket_id in existing_ticket_ids:
                    next_ticket_id += 1
                new_tid = next_ticket_id
                next_ticket_id += 1
            existing_ticket_ids.add(new_tid)

            cursor.execute(
                """
                INSERT INTO tickets (
                    id, event_id, order_id, holder_name, phone, public_code,
                    display_number, group_name, access_token_hash, status,
                    wants_physical_card, issued_at, revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_tid,
                    t["event_id"],
                    new_oid,
                    t["holder_name"],
                    t["phone"],
                    code,
                    t.get("display_number", 1),
                    t.get("group_name", "A"),
                    t.get("access_token_hash", ""),
                    t.get("status", "active"),
                    t.get("wants_physical_card", 0),
                    t.get("issued_at"),
                    t.get("revoked_at"),
                ),
            )
            existing_codes.add((t["event_id"], code))
            inserted_tickets += 1

        target_con.commit()
    except Exception:
        target_con.rollback()
        raise
    finally:
        target_con.close()

    return {
        "status": "success",
        "safety_backup": backup_copy,
        "inserted_orders": inserted_orders,
        "inserted_receipts": inserted_receipts,
        "inserted_tickets": inserted_tickets,
    }


def cmd_scan_backups(backup_dir: str, target_db: str) -> None:
    if not os.path.exists(target_db):
        print(f"Error: Target database {target_db} not found!")
        sys.exit(1)

    target_data = inspect_db(target_db)
    print(f"Active Target Database: {target_db}")
    print(f"  • Existing tickets: {len(target_data['tickets'])}")
    print(f"  • Existing orders:  {len(target_data['orders'])}")
    print("-" * 70)

    archives = sorted(glob.glob(os.path.join(backup_dir, "*.tar.gz")), reverse=True)
    if not archives:
        print(f"No backup archives found under {backup_dir}")
        return

    print(f"Found {len(archives)} backup archive(s). Scanning for missing records...")
    all_reports = []

    for arc in archives:
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                extracted_db = _extract_db_from_archive(arc, tmp_dir)
                source_data = inspect_db(extracted_db)
                diff = find_differences(source_data, target_data)
                missing_t_count = len(diff["missing_tickets"])
                missing_o_count = len(diff["missing_orders"])
                status_icon = "⚠️  MISSING DATA FOUND" if (missing_t_count or missing_o_count) else "✅ ALL SYNCED"
                print(f"[{status_icon}] {os.path.basename(arc)}:")
                print(f"       Backup holds: {len(source_data['tickets'])} tickets, {len(source_data['orders'])} orders")
                print(f"       Missing in target: {missing_t_count} tickets, {missing_o_count} orders")

                if missing_t_count or missing_o_count:
                    report_txt = format_report(diff, os.path.basename(arc), os.path.basename(target_db))
                    all_reports.append((os.path.basename(arc), diff, report_txt))
            except Exception as e:
                print(f"  [ERROR] {os.path.basename(arc)}: {e}")

    if all_reports:
        print("\n" + "=" * 70)
        print("DETAILS OF MISSING RECORDS:")
        for name, diff, rep in all_reports:
            print(f"\n--- {name} ---")
            print(rep)


def main():
    parser = argparse.ArgumentParser(description="Reconcile and merge missing tickets/orders from backups.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # scan
    scan_p = subparsers.add_parser("scan", help="Scan backup archives and compare against target DB")
    scan_p.add_argument("--backup-dir", default="/var/backups/wewerehere", help="Path to backups directory")
    scan_p.add_argument("--target", default="/opt/wewerehere/data.sqlite", help="Path to target data.sqlite")

    # diff
    diff_p = subparsers.add_parser("diff", help="Diff a specific backup file vs target DB")
    diff_p.add_argument("--source", required=True, help="Path to .tar.gz or .sqlite backup file")
    diff_p.add_argument("--target", default="/opt/wewerehere/data.sqlite", help="Path to target data.sqlite")
    diff_p.add_argument("--out-json", help="Save diff output to JSON file")

    # merge
    merge_p = subparsers.add_parser("merge", help="Merge missing tickets/orders from backup into target DB")
    merge_p.add_argument("--source", required=True, help="Path to .tar.gz or .sqlite backup file")
    merge_p.add_argument("--target", default="/opt/wewerehere/data.sqlite", help="Path to target data.sqlite")
    merge_p.add_argument("--apply", action="store_true", help="Actually commit changes (default is dry-run)")

    args = parser.parse_args()

    if args.subcommand == "scan":
        cmd_scan_backups(args.backup_dir, args.target)

    elif args.subcommand == "diff":
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = args.source
            if src_path.endswith(".tar.gz"):
                src_path = _extract_db_from_archive(src_path, tmp_dir)
            source_data = inspect_db(src_path)
            target_data = inspect_db(args.target)
            diff = find_differences(source_data, target_data)
            print(format_report(diff, os.path.basename(args.source), os.path.basename(args.target)))
            if args.out_json:
                with open(args.out_json, "w", encoding="utf-8") as f:
                    json.dump(diff, f, ensure_ascii=False, indent=2, default=str)
                print(f"Diff written to {args.out_json}")

    elif args.subcommand == "merge":
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = args.source
            if src_path.endswith(".tar.gz"):
                src_path = _extract_db_from_archive(src_path, tmp_dir)
            source_data = inspect_db(src_path)
            target_data = inspect_db(args.target)
            diff = find_differences(source_data, target_data)

            if not diff["missing_tickets"] and not diff["missing_orders"]:
                print("No missing tickets or orders found. Nothing to merge!")
                return

            print(f"Found {len(diff['missing_tickets'])} tickets and {len(diff['missing_orders'])} orders to restore.")
            if not args.apply:
                print("\n[DRY RUN] No changes made. Pass --apply to execute the merge.")
                print(format_report(diff, os.path.basename(args.source), os.path.basename(args.target)))
                return

            res = merge_missing_records(src_path, args.target, diff, dry_run=False)
            print("=" * 70)
            print("MERGE COMPLETED SUCCESSFULLY!")
            print(f"Safety pre-merge backup: {res['safety_backup']}")
            print(f"Inserted Orders:         {res['inserted_orders']}")
            print(f"Inserted Receipts:       {res['inserted_receipts']}")
            print(f"Inserted Tickets:        {res['inserted_tickets']}")
            print("=" * 70)


if __name__ == "__main__":
    main()
