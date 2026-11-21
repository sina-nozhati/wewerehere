"""Smoke-style checks for deploy-critical static assets (chrome shell)."""

import os

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT
from app.services.ticket_render import ensure_vazirmatn_font, vazirmatn_font_path

os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["WW_DISABLE_MIGRATE"] = "1"

pytest_plugins = ("tests.test_api",)


def test_vazirmatn_font_bundled_in_repo():
    path = ROOT / "assets" / "fonts" / "Vazirmatn-Regular.ttf"
    assert path.is_file()
    assert path.stat().st_size > 10_000
    assert vazirmatn_font_path().resolve() == path.resolve()
    ensure_vazirmatn_font()


def test_deploy_chrome_assets(client: TestClient):
    r = client.get("/assets/wwh-shell.css")
    assert r.status_code == 200
    assert "--wwh-topbar-height" in r.text

    r2 = client.get("/assets/wwh-chrome.js")
    assert r2.status_code == 200
    assert "data-wwh-chrome" in r2.text


def test_memories_gallery_frontend_features():
    html_path = ROOT / "memories.html"
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")

    # 1. Skeleton Loading and Gothic error retry
    assert "renderGallerySkeleton" in html
    assert "mem-card--skeleton" in html
    assert "wwh-skeleton-fade" in html
    assert "gallery-error" in html
    assert "gallery-retry-btn" in html
    assert "تلاش مجدد" in html

    # 2. Thumbnail loading & lazy & explicit dimensions
    assert "getThumbnailUrl" in html
    assert "thumb_url" in html
    assert "thumbUrl" in html
    assert "lazy" in html
    assert "aspect-ratio" in html

    # 3. Lightbox on-demand & no download button
    assert "openMediaLightbox" in html
    assert "download=" not in html.lower()


def test_lightbox_assets_no_download_and_navigation():
    js_path = ROOT / "assets" / "wwh-lightbox.js"
    assert js_path.is_file()
    js = js_path.read_text(encoding="utf-8")

    assert "nodownload" in js
    assert "controlsList" in js
    assert "ArrowLeft" in js and "ArrowRight" in js
    assert "bindPointer" in js  # mobile touch swipe

    css_path = ROOT / "assets" / "wwh-theme.css"
    assert css_path.is_file()
    css = css_path.read_text(encoding="utf-8")
    assert "mem-card--skeleton" in css
    assert "wwh-gallery-error" in css
    assert "wwh-skeleton-fade" in css


def test_self_hosted_fonts_and_inapp_performance():
    # 1. Local font-face rules in wwh-theme.css
    theme_css = (ROOT / "assets" / "wwh-theme.css").read_text(encoding="utf-8")
    assert "@font-face" in theme_css
    assert "Vazirmatn-Regular.ttf" in theme_css
    assert "font-display: swap" in theme_css

    # 2. HTML pages have non-blocking font references & load local theme first
    for page in ["index.html", "admin.html", "memories.html", "track.html", "support.html", "episodes.html"]:
        html_file = ROOT / page
        assert html_file.is_file()
        content = html_file.read_text(encoding="utf-8")
        assert "wwh-theme.css" in content
        # Ensure external fonts are not blocking
        if "fonts.googleapis.com" in content:
            assert 'media="print"' in content or 'as="style"' in content or 'wwh-perf.js' in content

    # 3. In-app browser detection in wwh-perf.js
    perf_js = (ROOT / "assets" / "wwh-perf.js").read_text(encoding="utf-8")
    assert "Instagram|FBAN|FBAV|Telegram" in perf_js
    assert "wwh-perf-lite" in perf_js

    # 4. In-app browser fast loader dismissal in wwh-loader.js
    loader_js = (ROOT / "assets" / "wwh-loader.js").read_text(encoding="utf-8")
    assert "Instagram|FBAN|FBAV|Telegram" in loader_js
    assert "350" in loader_js  # MIN_VISIBLE_MS <= 400ms
    assert "250" in loader_js  # FONT_WAIT_MS <= 250ms


def test_song_features_frontend_assets():
    """Verify memories.html and wwh-theme.css contain song feature components."""
    mem_html = (ROOT / "memories.html").read_text(encoding="utf-8")

    # 1. Public winner song banner
    assert "winner-song-banner" in mem_html
    assert "winner-banner-heading" in mem_html
    assert "winner-banner-badge" in mem_html
    assert "اجرای قطعی در این رویداد" in mem_html
    assert "wwh-winner-song-banner--pending" in mem_html

    # 2. Exclusive winner song selection form
    assert "winner-form-card" in mem_html
    assert "winner-song-form" in mem_html
    assert "winner-song-title-input" in mem_html
    assert "winner-song-artist-input" in mem_html
    assert "winner-song-submit-btn" in mem_html
    assert "isWinnerEligible" in mem_html

    # 3. Band rehearsal song suggestions & voting
    assert "suggestions-toggle" in mem_html
    assert "suggestions-panel" in mem_html
    assert "suggest-song-form" in mem_html
    assert "suggestions-list" in mem_html
    assert "wwh-song-vote-btn" in mem_html

    # 4. API endpoints referenced in JS
    assert "/songs/winner-pick" in mem_html
    assert "/songs/status" in mem_html
    assert "/songs/suggestions" in mem_html
    assert "/songs/suggest" in mem_html

    # 5. Gothic dark & gold CSS styles in theme
    theme_css = (ROOT / "assets" / "wwh-theme.css").read_text(encoding="utf-8")
    assert ".wwh-winner-song-banner" in theme_css
    assert ".wwh-winner-form-card" in theme_css
    assert ".wwh-suggestions-panel" in theme_css
    assert ".wwh-song-vote-btn" in theme_css



