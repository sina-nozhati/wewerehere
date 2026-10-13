#!/usr/bin/env python3
"""Print ticket PNG pipeline status (run from repo root: python backend/scripts/check_ticket_png.py)."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.ticket_render import ticket_png_diagnostics  # noqa: E402


def main() -> int:
    info = ticket_png_diagnostics()
    print("ticket PNG diagnostics:")
    for key, val in info.items():
        print(f"  {key}: {val}")
    if info.get("preferred") == "pymupdf":
        print(
            "\nWARNING: PyMuPDF fallback — Persian/background will look wrong. "
            "Install/use Chrome or Edge, or GTK+Cairo.",
            file=sys.stderr,
        )
        return 1
    if info.get("preferred") in ("chromium", "cairo"):
        print("\nOK — expected ticket download quality.")
        return 0
    print("\nERROR: no PNG renderer available.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
