#!/usr/bin/env python3
"""Complete forensic investigation script for Event 3 lost orders and tickets."""

from __future__ import annotations

import glob
import gzip
import json
import os
import re
import subprocess
import sys
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def search_all_nginx_logs():
    print("=" * 70)
    print("STEP 1: NGINX ACCESS LOGS (Nov 20 18:00 -> Nov 21 04:30 UTC / 21:30 -> 08:00 Tehran)")
    print("=" * 70)

    log_files = sorted(glob.glob("/var/log/nginx/*access*"))
    lines_found = []

    target_tokens = [
        "POST /api/orders",
        "/api/admin/orders/approve",
        "/api/orders/track",
        "/api/tickets/",
        "/api/orders/receipt-image",
        "09378401747",
        "09033645669",
        "09116949539",
        "6452",
        "6881",
        "2850",
        "6172",
        "6720",
        "0483",
    ]

    for fpath in log_files:
        opener = gzip.open if fpath.endswith(".gz") else open
        try:
            with opener(fpath, "rt", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if ("20/Nov/2026" in line or "21/Nov/2026" in line) and any(t in line for t in target_tokens):
                        # Filter to only relevant evening/morning window
                        lines_found.append(line.strip())
        except Exception as e:
            pass

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for l in lines_found:
        if l not in seen:
            seen.add(l)
            deduped.append(l)

    print(f"Total matching log lines found: {len(deduped)}")
    for l in deduped:
        print(f"  {l}")


def carve_sqlite_files():
    print("\n" + "=" * 70)
    print("STEP 2: SCANNING RAW SQLITE BYTES FOR PHONES & SERIALS")
    print("=" * 70)

    db_paths = [
        "/opt/wewerehere/data.sqlite",
        "/opt/wewerehere/data.sqlite-wal",
        "/root/wwh_save/data.sqlite",
        "/root/wwh_save/data.sqlite-wal",
        "/root/wwh_save/data.sqlite.bak",
    ]

    targets = [
        b"09378401747",
        b"09033645669",
        b"09116949539",
        b"6452",
        b"6881",
        b"2850",
        b"6172",
        b"6720",
        b"0483",
        "عصیانی".encode("utf-8"),
        "سیدی".encode("utf-8"),
        "خوشدل".encode("utf-8"),
        "حدادی".encode("utf-8"),
        "دلبر".encode("utf-8"),
    ]

    for p in db_paths:
        if not os.path.exists(p):
            continue
        print(f"\nScanning: {p} ({os.path.getsize(p):,} bytes)")
        try:
            with open(p, "rb") as f:
                content = f.read()
        except Exception as e:
            print(f"  Error reading {p}: {e}")
            continue

        for tgt in targets:
            start = 0
            count = 0
            tgt_str = tgt.decode("utf-8", errors="replace")
            while True:
                idx = content.find(tgt, start)
                if idx == -1:
                    break
                count += 1
                start = idx + len(tgt) + 50
                w_start = max(0, idx - 150)
                w_end = min(len(content), idx + 250)
                chunk = content[w_start:w_end]

                # Clean non-printable bytes
                chunk_str = chunk.decode("utf-8", errors="replace")
                cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", chunk_str)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                print(f"  * Match [{tgt_str}] at offset {idx}: {cleaned}")
                if count >= 10:
                    print(f"    (further matches for {tgt_str} truncated)")
                    break


def inspect_receipt_images():
    print("\n" + "=" * 70)
    print("STEP 3: INSPECTING RECEIPT FILES & SENDER METADATA")
    print("=" * 70)

    receipt_dir = "/opt/wewerehere/storage/receipts"
    files = [
        "1a1f9a087a3-117.jpg",
        "1a1f9aa369b-118.png",
        "1a1fa8ba5c4-119.jpg",
    ]

    for fname in files:
        fpath = os.path.join(receipt_dir, fname)
        if not os.path.exists(fpath):
            print(f"  File not found: {fpath}")
            continue
        sz = os.path.getsize(fpath)
        print(f"\nReceipt: {fname} ({sz:,} bytes)")

        # Check strings for any legible text
        try:
            res = subprocess.run(["strings", "-n", "6", fpath], capture_args=True if hasattr(subprocess, "capture_args") else {}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output_lines = [l.strip() for l in res.stdout.splitlines() if l.strip()][:15]
            if output_lines:
                print(f"    Strings found: {output_lines}")
        except Exception:
            pass

        # Try OCR if tesseract exists
        tesseract_path = None
        for cand in ["/usr/bin/tesseract", "tesseract"]:
            try:
                subprocess.run([cand, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                tesseract_path = cand
                break
            except Exception:
                pass

        if tesseract_path:
            try:
                ocr_cmd = [tesseract_path, fpath, "stdout", "-l", "fas+eng"]
                ocr_res = subprocess.run(ocr_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                ocr_text = "\n".join([line.strip() for line in ocr_res.stdout.splitlines() if line.strip()])
                print(f"    OCR OUTPUT:\n{ocr_text}")
            except Exception as e:
                print(f"    OCR error: {e}")
        else:
            print("    Tesseract OCR not installed on system.")


def main():
    search_all_nginx_logs()
    carve_sqlite_files()
    inspect_receipt_images()


if __name__ == "__main__":
    main()
