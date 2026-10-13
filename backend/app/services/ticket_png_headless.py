"""PNG export via headless Chromium/Edge — same SVG engine as the browser preview."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_CHROMIUM_CANDIDATES = (
    lambda: os.environ.get("WW_CHROMIUM_PATH", "").strip(),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


def headless_chromium_path() -> Path | None:
    for item in _CHROMIUM_CANDIDATES:
        raw = item() if callable(item) else item
        if not raw:
            continue
        path = Path(raw)
        if path.is_file():
            return path
    return None


def headless_chromium_available() -> bool:
    return headless_chromium_path() is not None


def render_svg_png_headless(svg_text: str, out_w: int, out_h: int) -> bytes:
    browser = headless_chromium_path()
    if browser is None:
        raise RuntimeError("headless Chromium/Edge not found")

    with tempfile.TemporaryDirectory(prefix="wwh-ticket-") as td:
        td_path = Path(td)
        html_path = td_path / "ticket.html"
        png_path = td_path / "ticket.png"
        # Inline SVG so @font-face data URIs and RTL layout match track/admin preview.
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;background:#e3e3e3;}"
            f"svg{{display:block;width:{out_w}px;height:{out_h}px}}</style>"
            "</head><body>"
            f"{svg_text}"
            "</body></html>"
        )
        html_path.write_text(html, encoding="utf-8")
        uri = html_path.resolve().as_uri()
        cmd = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-sandbox",
            f"--window-size={out_w},{out_h}",
            f"--screenshot={png_path}",
            uri,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("headless browser screenshot timed out") from exc
        if proc.returncode != 0 or not png_path.is_file():
            err = (proc.stderr or proc.stdout or "").strip()[:500]
            raise RuntimeError(f"headless screenshot failed (code {proc.returncode}): {err}")
        return png_path.read_bytes()
