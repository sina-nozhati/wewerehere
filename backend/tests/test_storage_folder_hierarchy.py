"""Unit and integration tests for Storage Folder Hierarchy and Files.ir Nested Folders Fix."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import create_session
from app.db import Base, get_db
from app.main import app
from app.models import Event, EventStorageConfig, EventStorageFolder, StorageProvider
from app.services.storage.base_adapter import FolderInfo
from app.services.storage.files_ir_adapter import FilesIrAdapter
from app.services.storage.folder_manager import FolderManager
from app.services.storage.provider_manager import ProviderManager


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test_folder_hierarchy.sqlite'}")
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()

    ProviderManager.seed_default_providers(db)

    ev = Event(
        slug="hierarchy-test-event",
        title="رویداد تست ساختار پوشه‌ها",
        episode_number=1,
        event_at=datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="تالار",
        capacity=50,
        ticket_price=0,
        status="sales_open",
        sales_status="open",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    p_local = db.scalar(select(StorageProvider).where(StorageProvider.provider_type == "local"))
    cfg = EventStorageConfig(
        event_id=ev.id,
        primary_provider_id=p_local.id if p_local else 1,
        fallback_provider_ids_json="[]",
        routing_status="active",
    )
    db.add(cfg)
    db.commit()

    yield db
    db.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def _auth() -> dict:
    token = create_session()
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_files_ir_folder_cache_hit_and_case_insensitive():
    """Verify that in-memory cache avoids duplicate API calls and supports case/whitespace tolerance."""
    adapter = FilesIrAdapter({"api_key": "test_token", "workspace_id": 101})

    call_count = 0

    async def fake_request(method, path, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "status": "success",
            "data": [
                {"id": 555, "name": "Memories", "type": "folder", "parent_id": 10},
                {"id": 556, "name": "Photos", "type": "folder", "parent_id": 555},
            ],
        }

    adapter._request = fake_request  # type: ignore[assignment]

    # 1. First find -> hits API
    fid = await adapter._find_folder("Memories", parent_id="10", workspace_id=101)
    assert fid == "555"
    assert call_count == 1

    # 2. Second find with lowercase and whitespace -> hits cache, call_count stays 1
    fid_cached = await adapter._find_folder("  memories  ", parent_id="10", workspace_id=101)
    assert fid_cached == "555"
    assert call_count == 1

    # 3. Different parent -> triggers API call
    await adapter._find_folder("Memories", parent_id="999", workspace_id=101)
    assert call_count == 2


@pytest.mark.anyio
async def test_files_ir_guard_against_path_repetition():
    """Verify defensive guard strips redundant root prefix when parent_folder_id is provided."""
    adapter = FilesIrAdapter({"api_key": "test_token", "workspace_id": 101})

    created_paths = []

    async def fake_request(method, path, **kwargs):
        if method == "GET" and "/file-entries/123" in path:
            return {"file_entry": {"id": 123, "name": "slug-test", "type": "folder"}}
        if method == "GET" and "/drive/file-entries" in path:
            return {"data": []}
        if method == "POST" and path == "/folders":
            json_data = kwargs.get("json_data") or {}
            name = json_data.get("name")
            pid = json_data.get("parentId")
            created_paths.append((name, pid))
            return {"folder": {"id": 900 + len(created_paths)}}
        return {}

    adapter._request = fake_request  # type: ignore[assignment]

    # Caller passes full event path along with parent_folder_id=123 (which is already slug-test)
    finfo = await adapter.create_or_get_folder(
        "WE WERE HERE/Events/2026/slug-test/Memories/Photos",
        parent_folder_id="123",
    )
    assert finfo.name == "Photos"
    # Verify created paths did NOT re-create "WE WERE HERE" or "Events" or "slug-test" under 123
    created_names = [name for name, pid in created_paths]
    assert "WE WERE HERE" not in created_names
    assert "Events" not in created_names
    assert "slug-test" not in created_names
    assert created_names == ["Memories", "Photos"]
    assert created_paths[0] == ("Memories", 123)


@pytest.mark.anyio
async def test_folder_manager_clean_hierarchy_creation(db_session: Session):
    """Verify FolderManager creates root, then intermediate branches, then child folders using single segments."""
    ev = db_session.scalar(select(Event).limit(1))
    assert ev is not None

    prov = db_session.scalar(select(StorageProvider).where(StorageProvider.provider_type == "files_ir"))
    assert prov is not None

    calls = []

    class MockAdapter:
        async def create_or_get_folder(self, folder_path, parent_folder_id=None, workspace_id=None):
            calls.append((folder_path, parent_folder_id))
            folder_id = f"fid-{len(calls)}"
            return FolderInfo(folder_id=folder_id, name=folder_path.split("/")[-1], path=folder_path)

    with patch("app.services.storage.provider_manager.ProviderManager.get_adapter_for_provider", return_value=MockAdapter()):
        folders = await FolderManager.ensure_event_folders(db_session, ev.id, prov.id)

    assert "root" in folders
    assert "memories_photos" in folders
    assert "memories_videos" in folders
    assert "official_photos" in folders
    assert "exports" in folders

    # Check the exact folder creation calls
    # 1. Root call: full standardized path
    root_call = calls[0]
    assert root_call[0] == f"WE WERE HERE/Events/2026/{ev.slug}"
    assert root_call[1] is None

    # 2. Branch & leaf calls under root: MUST be single-segment names!
    child_calls = calls[1:]
    for fpath, pid in child_calls:
        assert pid is not None
        assert "/" not in fpath  # No multi-segment or nested paths!
        assert fpath in ("Memories", "Photos", "Videos", "Other", "Official-Media", "Exports")

    # 3. Canonical paths in DB must remain full canonical paths
    mem_photos = folders["memories_photos"]
    assert mem_photos.provider_folder_path == f"WE WERE HERE/Events/2026/{ev.slug}/Memories/Photos"
    assert "WE WERE HERE/Events/2026" not in mem_photos.provider_folder_path[20:]  # No duplicate repetition


def test_get_event_storage_config_auto_ensures_folders(client: TestClient, db_session: Session):
    """Verify GET /api/admin/storage/events/{event_id} auto-provisions folders when missing."""
    ev = db_session.scalar(select(Event).limit(1))
    assert ev is not None

    headers = _auth()
    res = client.get(f"/api/admin/storage/events/{ev.id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["eventId"] == ev.id
    assert "primaryProviderId" in data
    assert "folders" in data
    assert len(data["folders"]) >= 1


def test_sync_event_storage_folders_endpoint(client: TestClient, db_session: Session):
    """Verify POST /api/admin/storage/events/{event_id}/sync-folders provisions and returns folder list."""
    ev = db_session.scalar(select(Event).limit(1))
    assert ev is not None

    headers = _auth()
    res = client.post(f"/api/admin/storage/events/{ev.id}/sync-folders", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["eventId"] == ev.id
    assert data["folderCount"] >= 1
    assert isinstance(data["folders"], list)


@pytest.mark.anyio
async def test_folder_manager_idempotency_and_no_redundant_creation(db_session: Session):
    """Verify ensure_event_folders is completely idempotent and makes zero creation calls when already mapped."""
    ev = db_session.scalar(select(Event).limit(1))
    prov = db_session.scalar(select(StorageProvider).where(StorageProvider.provider_type == "files_ir"))
    assert ev is not None and prov is not None

    call_count = 0

    class MockAdapter:
        async def create_or_get_folder(self, folder_path, parent_folder_id=None, workspace_id=None):
            nonlocal call_count
            call_count += 1
            return FolderInfo(folder_id=f"fid-{call_count}", name=folder_path.split("/")[-1], path=folder_path)

    with patch("app.services.storage.provider_manager.ProviderManager.get_adapter_for_provider", return_value=MockAdapter()):
        # First call creates folders
        first_folders = await FolderManager.ensure_event_folders(db_session, ev.id, prov.id)
        assert len(first_folders) >= 6
        initial_call_count = call_count
        assert initial_call_count > 0

        # Second call: All folders exist in DB -> should NOT create any folders again!
        second_folders = await FolderManager.ensure_event_folders(db_session, ev.id, prov.id)
        assert len(second_folders) == len(first_folders)
        assert call_count == initial_call_count  # No new creation calls!


@pytest.mark.anyio
async def test_files_ir_prevents_none_string_folder_id():
    """Verify FilesIrAdapter prevents storing 'None' string IDs from corrupt or nested responses."""
    adapter = FilesIrAdapter({"api_key": "test_token", "workspace_id": 101})

    async def fake_request(method, path, **kwargs):
        if method == "GET":
            # Finding returns existing folder with real ID
            return {"data": [{"id": 8888, "name": "Memories", "type": "folder", "parent_id": None}]}
        if method == "POST":
            # Malformed POST response with missing ID
            return {"status": "ok", "message": "created"}
        return {}

    adapter._request = fake_request  # type: ignore[assignment]

    # create_or_get_folder should find fallback ID 8888 rather than returning "None"
    finfo = await adapter.create_or_get_folder("Memories")
    assert finfo.folder_id == "8888"
    assert finfo.folder_id != "None"

