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

