"""Smoke-style checks for deploy-critical static assets (chrome shell)."""

import os

import pytest
from fastapi.testclient import TestClient

os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
os.environ["WW_DISABLE_MIGRATE"] = "1"

pytest_plugins = ("tests.test_api",)


def test_deploy_chrome_assets(client: TestClient):
    r = client.get("/assets/wwh-shell.css")
    assert r.status_code == 200
    assert "--wwh-topbar-height" in r.text

    r2 = client.get("/assets/wwh-chrome.js")
    assert r2.status_code == 200
    assert "data-wwh-chrome" in r2.text
