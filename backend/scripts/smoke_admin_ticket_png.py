#!/usr/bin/env python3
"""Login as admin and verify GET /api/admin/tickets/sample returns PNG. Used on VPS after deploy."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def main() -> int:
    base = (os.environ.get("WW_BASE") or "http://127.0.0.1:5173").rstrip("/")
    password = os.environ.get("ADMIN_PASSWORD") or os.environ.get("PW")
    if not password:
        print("Set ADMIN_PASSWORD or PW in the environment", file=sys.stderr)
        return 2

    login = urllib.request.Request(
        f"{base}/api/admin/login",
        data=json.dumps({"password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(login, timeout=20) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"admin login failed: HTTP {e.code}", file=sys.stderr)
        return 1
    token = body.get("token")
    if not token:
        print(f"admin login: no token in {body!r}", file=sys.stderr)
        return 1

    sample = urllib.request.Request(
        f"{base}/api/admin/tickets/sample",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(sample, timeout=60) as r:
            ct = (r.headers.get("Content-Type") or "").lower()
            head = r.read(8)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"sample ticket failed: HTTP {e.code} {err[:500]}", file=sys.stderr)
        return 1

    if "image/png" not in ct:
        print(f"unexpected content-type: {ct}", file=sys.stderr)
        return 1
    if head != PNG_MAGIC:
        print(f"not PNG magic bytes: {head!r}", file=sys.stderr)
        return 1
    print(f"OK sample PNG from {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
