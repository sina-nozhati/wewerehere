#!/usr/bin/env python3
"""Deep forensic scanner to find the guest name entered for Order 118 (phone 09378401747)."""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def search_all_sqlite_variants():
    print("=" * 70)
    print("SEARCHING ALL SQLITE VARIANTS AND BACKUPS IN /opt/wewerehere/")
    print("=" * 70)

    matches = glob.glob("/opt/wewerehere/data.sqlite*") + glob.glob("/opt/wewerehere/*.sqlite*") + glob.glob("/root/wwh_save/**/data.sqlite*", recursive=True)
    for p in sorted(list(set(matches))):
        if not os.path.isfile(p):
            continue
        sz = os.path.getsize(p)
        print(f"\nChecking file: {p} ({sz:,} bytes)")
        try:
            with open(p, "rb") as f:
                content = f.read()
        except Exception as e:
            print(f"  Error reading {p}: {e}")
            continue

        for token in [b"09378401747", b"6452"]:
            idx = 0
            while True:
                idx = content.find(token, idx)
                if idx == -1:
                    break
                w_start = max(0, idx - 200)
                w_end = min(len(content), idx + 200)
                chunk = content[w_start:w_end]
                cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", chunk.decode("utf-8", errors="replace"))
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                print(f"  [FOUND in {os.path.basename(p)} at {idx}]: {cleaned}")
                idx += len(token) + 20


def search_nginx_temp_bodies():
    print("\n" + "=" * 70)
    print("SEARCHING NGINX CLIENT BODY BUFFER DIRECTORIES")
    print("=" * 70)

    body_dirs = ["/var/lib/nginx/body", "/var/lib/nginx/tmp", "/var/spool/nginx", "/tmp"]
    found_any = False
    for bdir in body_dirs:
        if not os.path.exists(bdir):
            continue
        for root, dirs, files in os.walk(bdir):
            for f in files:
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "rb") as bf:
                        data = bf.read()
                        if b"09378401747" in data or b"6452" in data:
                            found_any = True
                            print(f"  [MATCH in {fpath}]:")
                            cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", data[:1000].decode("utf-8", errors="replace"))
                            print(f"    {cleaned}")
                except Exception:
                    pass
    if not found_any:
        print("  No active temp files matching 09378401747 found in nginx body dirs.")


def search_journalctl():
    print("\n" + "=" * 70)
    print("SEARCHING SYSTEMD JOURNAL FOR 09378401747 OR 6452")
    print("=" * 70)

    try:
        cmd = ["journalctl", "-u", "wewerehere", "--since", "2026-11-20 18:00:00", "--until", "2026-11-21 04:00:00", "--no-pager"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        lines = res.stdout.splitlines()
        matches = [l for l in lines if any(k in l for k in ["09378401747", "6452", "118", "Order"])]
        print(f"  Total matching journal lines: {len(matches)}")
        for l in matches[:30]:
            print(f"    {l}")
    except Exception as e:
        print(f"  Journal query error: {e}")


def main():
    search_all_sqlite_variants()
    search_nginx_temp_bodies()
    search_journalctl()


if __name__ == "__main__":
    main()
