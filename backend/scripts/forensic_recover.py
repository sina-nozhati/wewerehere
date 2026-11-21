#!/usr/bin/env python3
"""Forensic recovery tool to search SQLite raw files, WALs, logs and backups
for lost guest names, phone numbers, and orders.
"""

from __future__ import annotations

import glob
import os
import re
import sys
import tarfile
import tempfile

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TARGET_NAMES = [
    "محمد دلبر",
    "بیتا عصیانی",
    "زهرا سیدی",
    "ارسلان خوشدل",
    "محمدمهدی حدادی",
    "دلبر",
    "عصیانی",
    "سیدی",
    "خوشدل",
    "حدادی",
]

TARGET_CODES = ["6881", "2850", "6172", "6720", "0483"]


def scan_buffer(data: bytes, source_name: str) -> list[dict]:
    results = []
    found_keys = set()

    for name in TARGET_NAMES:
        name_bytes = name.encode("utf-8")
        start = 0
        while True:
            idx = data.find(name_bytes, start)
            if idx == -1:
                break
            start = idx + len(name_bytes)
            win_start = max(0, idx - 400)
            win_end = min(len(data), idx + 400)
            chunk = data[win_start:win_end]

            # Find phones
            phones = [p.decode("ascii") for p in re.findall(rb"09\d{9}", chunk)]
            # Find serial codes
            codes = [c.decode("ascii") for c in re.findall(rb"\b\d{4}\b", chunk) if c.decode("ascii") in TARGET_CODES]

            key = (name, tuple(phones), tuple(codes))
            if key in found_keys:
                continue
            found_keys.add(key)

            snippet = chunk.decode("utf-8", errors="replace")
            # Clean snippet for terminal display
            cleaned_snippet = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", snippet)
            cleaned_snippet = re.sub(r"\s+", " ", cleaned_snippet).strip()

            results.append({
                "source": source_name,
                "name": name,
                "phones": list(set(phones)),
                "codes": list(set(codes)),
                "snippet": cleaned_snippet,
            })

    for code in TARGET_CODES:
        code_bytes = code.encode("ascii")
        start = 0
        while True:
            idx = data.find(code_bytes, start)
            if idx == -1:
                break
            start = idx + len(code_bytes)
            win_start = max(0, idx - 300)
            win_end = min(len(data), idx + 300)
            chunk = data[win_start:win_end]

            phones = [p.decode("ascii") for p in re.findall(rb"09\d{9}", chunk)]
            key = (f"CODE_{code}", tuple(phones))
            if key in found_keys:
                continue
            found_keys.add(key)

            snippet = chunk.decode("utf-8", errors="replace")
            cleaned_snippet = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", snippet)
            cleaned_snippet = re.sub(r"\s+", " ", cleaned_snippet).strip()

            results.append({
                "source": source_name,
                "code": code,
                "phones": list(set(phones)),
                "snippet": cleaned_snippet,
            })

    return results


def scan_file(file_path: str) -> list[dict]:
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return []
    try:
        size = os.path.getsize(file_path)
        if size > 100 * 1024 * 1024:
            return []
        with open(file_path, "rb") as f:
            data = f.read()
        return scan_buffer(data, file_path)
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return []


def main():
    print("=" * 70)
    print("FORENSIC SCAN FOR LOST TICKETS AND PHONE NUMBERS")
    print(f"Target Names: {', '.join(TARGET_NAMES[:5])}")
    print(f"Target Codes: {', '.join(TARGET_CODES)}")
    print("=" * 70)

    candidate_files = []
    # 1. SQLite and WAL files
    for pattern in [
        "/root/wwh_save/data.sqlite*",
        "/opt/wewerehere/data.sqlite*",
        "/opt/wewerehere/storage/receipts/*",
        "/var/log/nginx/access.log*",
        "/var/backups/wewerehere/*.tar.gz",
    ]:
        candidate_files.extend(glob.glob(pattern))

    all_results = []

    for fpath in candidate_files:
        if fpath.endswith(".tar.gz"):
            try:
                with tempfile.TemporaryDirectory() as td:
                    with tarfile.open(fpath, "r:gz") as tar:
                        tar.extractall(path=td)
                    for root, _, files in os.walk(td):
                        for f in files:
                            res = scan_file(os.path.join(root, f))
                            for r in res:
                                r["source"] = f"{os.path.basename(fpath)}:{f}"
                                all_results.append(r)
            except Exception:
                pass
        else:
            res = scan_file(fpath)
            all_results.extend(res)

    print(f"\nScan completed. Found {len(all_results)} candidate occurrences.\n")
    if not all_results:
        print("No raw text occurrences found in candidate files.")
        return

    # Aggregate phones by name
    name_to_phones: dict[str, set[str]] = {}
    for r in all_results:
        matched_name = r.get("name")
        if matched_name:
            for p in r.get("phones", []):
                name_to_phones.setdefault(matched_name, set()).add(p)

        print("-" * 70)
        print(f"File: {r['source']}")
        if "name" in r:
            print(f"Matched Name: {r['name']}")
        if "code" in r:
            print(f"Matched Code: {r['code']}")
        if r.get("phones"):
            print(f"Discovered Phones: {', '.join(r['phones'])}")
        print(f"Snippet: {r['snippet'][:300]}")

    print("\n" + "=" * 70)
    print("SUMMARY OF DISCOVERED PHONE NUMBERS:")
    for n, phones in name_to_phones.items():
        print(f"  * {n}: {', '.join(phones) if phones else 'No phone found'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
