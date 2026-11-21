#!/usr/bin/env python3
"""Deep Forensic Recovery Tool for We Were Here.

Carves raw SQLite pages, WAL files, receipts directory, and system logs
to recover lost order data, phone numbers, and companions.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def carve_sqlite_wal(file_path: str):
    print(f"\n[CARVING] Scanning raw bytes of: {file_path}")
    if not os.path.exists(file_path):
        print("  File not found.")
        return []

    with open(file_path, "rb") as f:
        data = f.read()

    print(f"  File size: {len(data):,} bytes")

    # Search for all phone numbers
    phones = set(re.findall(rb"09\d{9}", data))
    print(f"  Total phone occurrences found: {len(phones)}")

    # Search for names_json patterns like ["...", "..."]
    # Persian characters in utf-8: \xd8\x80 - \xdb\xbf
    json_pattern = re.compile(rb'\[\s*"([^"]+)"(?:\s*,\s*"([^"]+)")*\s*\]')
    matches = json_pattern.finditer(data)
    
    extracted_records = []
    
    # Also find any occurrence of our target keywords
    keywords = [
        "دلبر".encode("utf-8"),
        "عصیانی".encode("utf-8"),
        "سیدی".encode("utf-8"),
        "خوشدل".encode("utf-8"),
        "حدادی".encode("utf-8"),
        "محمد".encode("utf-8"),
    ]

    for kw in keywords:
        pos = 0
        while True:
            idx = data.find(kw, pos)
            if idx == -1:
                break
            pos = idx + len(kw)
            w_start = max(0, idx - 500)
            w_end = min(len(data), idx + 500)
            chunk = data[w_start:w_end]

            chunk_phones = [p.decode("ascii") for p in re.findall(rb"09\d{9}", chunk)]
            
            # Try to find JSON or text in this chunk
            chunk_txt = chunk.decode("utf-8", errors="replace")
            clean_txt = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", chunk_txt)
            clean_txt = re.sub(r"\s+", " ", clean_txt).strip()

            extracted_records.append({
                "keyword": kw.decode("utf-8", errors="replace"),
                "phones": list(set(chunk_phones)),
                "snippet": clean_txt,
            })

    return extracted_records


def inspect_receipts():
    print("\n[RECEIPTS] Inspecting /opt/wewerehere/storage/receipts/ and backups...")
    paths = glob.glob("/opt/wewerehere/storage/receipts/*") + glob.glob("/root/wwh_save/**/receipts/*", recursive=True)
    if not paths:
        print("  No receipt files found.")
        return

    print(f"  Found {len(paths)} receipt file(s).")
    for p in sorted(paths, key=os.path.getmtime, reverse=True):
        mtime = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        size = os.path.getsize(p)
        fname = os.path.basename(p)
        print(f"  * {fname} | Size: {size:,} bytes | Modified: {mtime} | Path: {p}")


def search_logs():
    print("\n[LOGS] Searching systemd journal and nginx access logs...")
    # Nginx logs
    for log_file in glob.glob("/var/log/nginx/*access*"):
        try:
            print(f"  Scanning nginx log: {log_file}")
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "20/Nov/2026" in line and ("/api/orders" in line or "/api/admin/orders" in line):
                        print(f"    [NGINX] {line.strip()}")
        except Exception as e:
            print(f"    Error reading {log_file}: {e}")

    # Journalctl
    try:
        print("  Querying journalctl for Nov 20...")
        cmd = [
            "journalctl",
            "-u",
            "wewerehere",
            "--since",
            "2026-11-20 08:00:00",
            "--until",
            "2026-11-21 04:00:00",
            "--no-pager",
            "-n",
            "200",
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10).decode("utf-8", errors="replace")
        for line in out.splitlines():
            if any(k in line for k in ["order", "Order", "ticket", "Ticket", "POST", "approve"]):
                print(f"    [JOURNAL] {line}")
    except Exception as e:
        print(f"    journalctl check skipped/failed: {e}")


def main():
    print("=" * 70)
    print("DEEP FORENSIC RECOVERY: LOCATING TICKETS & PHONE NUMBERS")
    print("=" * 70)

    # 1. Carve SQLite WAL in /root/wwh_save/
    wal_files = [
        "/root/wwh_save/data.sqlite-wal",
        "/root/wwh_save/data.sqlite",
        "/opt/wewerehere/data.sqlite-wal",
        "/opt/wewerehere/data.sqlite",
    ]
    for wf in wal_files:
        records = carve_sqlite_wal(wf)
        if records:
            print(f"\n--- Discovered Snippets in {wf} ---")
            seen = set()
            for r in records:
                s = r["snippet"]
                if s in seen:
                    continue
                seen.add(s)
                print(f"  [Match: {r['keyword']}] Phones: {r['phones']}")
                print(f"  Snippet: {s}\n")

    # 2. Inspect receipts
    inspect_receipts()

    # 3. Search logs
    search_logs()

    print("\n" + "=" * 70)
    print("FORENSIC SEARCH COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()
