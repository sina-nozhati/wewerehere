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
