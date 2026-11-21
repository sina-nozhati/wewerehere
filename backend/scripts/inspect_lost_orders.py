#!/usr/bin/env python3
"""Investigate the exact 3 lost orders (117, 118, 119) from Nov 20 evening."""

import glob
import gzip
import os
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def search_all_nginx_logs():
    print("=" * 70)
    print("NGINX LOG SEARCH FOR NOV 20 ORDERS (117, 118, 119)")
    print("=" * 70)

    log_files = glob.glob("/var/log/nginx/*access*")
    found_lines = []

    for fpath in log_files:
        opener = gzip.open if fpath.endswith(".gz") else open
        try:
            with opener(fpath, "rt", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "20/Nov/2026" in line:
                        # Check for track with phone or order IDs
                        if any(k in line for k in ["orderId=117", "orderId=118", "orderId=119", "5.122.236.152", "09033645669", "09378401747"]):
                            found_lines.append(line.strip())
                        elif "POST /api/orders" in line:
                            found_lines.append(line.strip())
                        elif "GET /api/orders/track" in line and "eventId=3" in line:
                            found_lines.append(line.strip())
        except Exception as e:
            pass

    for l in sorted(list(set(found_lines))):
        print(f"  {l}")


def check_receipt_files():
    print("\n" + "=" * 70)
    print("RECEIPT FILES FOR LOST ORDERS:")
    print("=" * 70)
    receipt_dir = "/opt/wewerehere/storage/receipts"
    for oid in [117, 118, 119]:
        matches = glob.glob(f"{receipt_dir}/*-{oid}.*")
        for m in matches:
            sz = os.path.getsize(m)
            print(f"  Order {oid} Receipt: {m} ({sz:,} bytes)")


def check_root_save():
    print("\n" + "=" * 70)
    print("CHECKING /root/wwh_save/ DIRECTORY:")
    print("=" * 70)
    if os.path.exists("/root/wwh_save"):
        for root, dirs, files in os.walk("/root/wwh_save"):
            for f in files:
                p = os.path.join(root, f)
                print(f"  {p} ({os.path.getsize(p):,} bytes)")
    else:
        print("  /root/wwh_save does not exist.")


def main():
    search_all_nginx_logs()
    check_receipt_files()
    check_root_save()


if __name__ == "__main__":
    main()
