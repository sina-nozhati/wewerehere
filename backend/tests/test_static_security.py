"""Security regression tests for static file serving and path traversal prevention."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_sensitive_files_blocked(client: TestClient):
    """Ensure repository root files, secrets, database, and backend code are never accessible."""
    blocked = [
        "/.env",
        "/.env.example",
        "/data.sqlite",
        "/data.sqlite-wal",
        "/data.sqlite-shm",
        "/backend/app/main.py",
        "/backend/app/config.py",
        "/server.js",
        "/package.json",
        "/.git/HEAD",
        "/.git/config",
        "/storage/sms-console.log",
        "/docs/CODEMAPS.md",
        "/_index-preview.html",
    ]
    for path in blocked:
        resp = client.get(path)
        assert resp.status_code == 404, f"Sensitive path {path} returned {resp.status_code} instead of 404!"


def test_allowed_public_assets(client: TestClient):
    """Ensure authorized public assets and pages continue to be served cleanly."""
    allowed = [
        "/assets/wwh-uploader.js",
        "/assets/wwh-theme.css",
        "/",
        "/index",
        "/index.html",
        "/admin",
        "/track",
        "/support",
        "/episodes",
    ]
    for path in allowed:
        resp = client.get(path)
        assert resp.status_code == 200, f"Public path {path} returned {resp.status_code}!"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
