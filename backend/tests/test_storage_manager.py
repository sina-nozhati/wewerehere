"""Comprehensive tests for the Provider-Agnostic Media Storage Manager."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth import create_session
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import (
    Event,
    EventStorageConfig,
    EventStorageFolder,
    Media,
    MediaAsset,
    MemoryItem,
    StorageProvider,
    StorageRoutingLog,
    Ticket,
    UploadReservation,
    utcnow,
)
from app.services.storage.base_adapter import (
    FileEntryInfo,
    FolderInfo,
    ProviderCapabilities,
    StorageAuthError,
    StorageError,
    StorageQuotaError,
    StorageUnavailableError,
    StorageUsage,
    UploadSessionInfo,
)
from app.services.storage.download_manager import DownloadManager
from app.services.storage.files_ir_adapter import FilesIrAdapter
from app.services.storage.folder_manager import FolderManager
from app.services.storage.local_adapter import LocalStorageAdapter
from app.services.storage.media_registry import MediaRegistry
from app.services.storage.provider_manager import ProviderManager, mask_config, unmask_config
from app.services.storage.routing_manager import StorageRoutingManager
from app.services.storage.s3_adapter import S3CompatibleAdapter
from app.services.storage.storage_monitor import StorageMonitor
from app.services.storage.upload_manager import UploadManager


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test_storage.sqlite'}")
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()

    # Seed default providers
    ProviderManager.seed_default_providers(db)

    # Seed test event
    ev = Event(
        slug="storage-test-event",
        title="رویداد تست ذخیره‌سازی",
        episode_number=1,
        event_at=datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc),
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

    # Link event storage config
    p_files = db.scalar(select(StorageProvider).where(StorageProvider.key == "files_ir_main"))
    p_local = db.scalar(select(StorageProvider).where(StorageProvider.key == "local_storage"))
    p_s3 = db.scalar(select(StorageProvider).where(StorageProvider.key == "s3_backup"))

    cfg = EventStorageConfig(
        event_id=ev.id,
        primary_provider_id=p_local.id if p_local else 1,
        fallback_provider_ids_json=json.dumps([p_files.id, p_s3.id]),
        routing_status="active",
    )
    db.add(cfg)
    db.commit()

    yield db
    db.close()


@pytest.fixture()
def client(db_session, monkeypatch):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def _auth(client: TestClient) -> dict:
    token = create_session()
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Files.ir Provider Adapter Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_files_ir_adapter_capabilities():
    config = {
        "api_key": "test_token_123",
        "api_endpoint": "https://my.files.ir/api/v1",
        "max_file_size_bytes": 500 * 1024 * 1024,
    }
    adapter = FilesIrAdapter(config)
    caps = adapter.get_capabilities()
    assert caps.provider_type == "files_ir"
    assert caps.supports_direct_upload is True
    assert caps.supports_multipart_upload is True
    assert caps.supports_folders is True
    assert caps.max_file_size_bytes == 500 * 1024 * 1024


@pytest.mark.anyio
async def test_files_ir_validate_credentials():
    adapter = FilesIrAdapter({"api_key": "valid_token"})
    with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"status": "success", "scopes": ["files.view", "files.create"]}
        assert await adapter.validate_credentials() is True

    with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = StorageAuthError("Invalid token")
        assert await adapter.validate_credentials() is False


@pytest.mark.anyio
async def test_files_ir_storage_usage():
    adapter = FilesIrAdapter({"api_key": "valid_token"})
    with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {
            "status": "success",
            "used": 2000000,
            "available": 10000000,
            "remaining": 8000000,
        }
        usage = await adapter.get_storage_usage()
        assert usage.used_bytes == 2000000
        assert usage.available_bytes == 8000000
        assert usage.total_bytes == 10000000
        assert usage.percent_used == 20.0


@pytest.mark.anyio
async def test_files_ir_init_upload_modes():
    adapter = FilesIrAdapter({"api_key": "valid_token", "max_file_size_bytes": 500 * 1024 * 1024})

    # s3-multipart mode (files >= 100MB)
    with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {
            "status": "success",
            "uploadSessionId": "sess_multi_123",
            "uploadMode": "s3-multipart",
            "partSize": 20971520,
            "next": {
                "method": "PUT",
                "completeUrl": "https://my.files.ir/api/v1/uploads-new/sess_multi_123/complete",
            },
        }
        session = await adapter.init_upload("video.mp4", 150 * 1024 * 1024, "video/mp4", parent_folder_id="456")
        assert session.session_id == "sess_multi_123"
        assert session.upload_mode == "s3-multipart"
        assert session.part_size == 20971520

    # Oversized rejection
    with pytest.raises(StorageQuotaError):
        await adapter.init_upload("huge.mp4", 600 * 1024 * 1024, "video/mp4")


@pytest.mark.anyio
async def test_files_ir_complete_upload():
    adapter = FilesIrAdapter({"api_key": "valid_token"})
    with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {
            "status": "success",
            "fileEntry": {
                "id": 987,
                "name": "photo.jpg",
                "file_size": 12345,
                "mime": "image/jpeg",
                "hash": "hash_abc",
            },
        }
        entry = await adapter.complete_upload("sess_123", parts=[{"PartNumber": 1, "ETag": '"tag"'}])
        assert entry.file_id == "987"
        assert entry.size_bytes == 12345
        assert entry.mime == "image/jpeg"


@pytest.mark.anyio
async def test_files_ir_shareable_download_link():
    adapter = FilesIrAdapter({"api_key": "valid_token", "api_endpoint": "https://my.files.ir/api/v1"})
    with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {
            "status": "success",
            "link": {
                "id": 10,
                "hash": "KXe8LLkaCDV0mzwDcKjO1Ym7xARTCs",
                "allow_download": True,
            },
        }
        link = await adapter.generate_download_link("987", expires_sec=1800)
        assert "shareable_link=KXe8LLkaCDV0mzwDcKjO1Ym7xARTCs" in link


# ---------------------------------------------------------------------------
# 2. S3-Compatible Provider Adapter Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_s3_adapter_presigned_urls():
    config = {
        "endpoint": "https://s3.ir-thr-at1.arvanstorage.ir",
        "bucket": "wwh-test-bucket",
        "access_key": "test_access_key",
        "secret_key": "test_secret_key",
        "region": "ir-thr-at1",
        "force_path_style": True,
    }
    adapter = S3CompatibleAdapter(config)
    assert adapter.is_configured is True

    # Presigned PUT
    put_url = adapter.generate_presigned_url("PUT", "events/2026/test.jpg", expires_sec=3600)
    assert "https://s3.ir-thr-at1.arvanstorage.ir/wwh-test-bucket/events/2026/test.jpg" in put_url
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in put_url
    assert "X-Amz-Signature=" in put_url

    # Presigned GET
    get_url = adapter.generate_presigned_url("GET", "events/2026/test.jpg", expires_sec=1800)
    assert "X-Amz-Expires=1800" in get_url


# ---------------------------------------------------------------------------
# 3. Local VPS Adapter Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_local_adapter_read_write(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "legacy_uploads", tmp_path / "uploads")
    adapter = LocalStorageAdapter({"root_dir": str(tmp_path)})

    entry = await adapter.upload_direct_bytes(b"hello media bytes", "sample.txt", "text/plain")
    assert entry.size_bytes == 17
    resolved = adapter.resolve_local_path(entry.file_id)
    assert resolved is not None
    assert resolved.read_bytes() == b"hello media bytes"


# ---------------------------------------------------------------------------
# 4. Hybrid Routing & Concurrency Reservation Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_routing_primary_selected(db_session):
    ev = db_session.scalar(select(Event).where(Event.slug == "storage-test-event"))
    p_files = db_session.scalar(select(StorageProvider).where(StorageProvider.key == "files_ir_main"))
    cfg = db_session.scalar(select(EventStorageConfig).where(EventStorageConfig.event_id == ev.id))
    cfg.primary_provider_id = p_files.id
    p_files.is_enabled = True
    p_files.health_status = "healthy"
    p_files.total_capacity_bytes = 10 * 1024 * 1024 * 1024
    db_session.commit()

    decision = await StorageRoutingManager.select_provider_and_reserve(
        db_session,
        event_id=ev.id,
        filename="photo1.jpg",
        file_size=2 * 1024 * 1024,
        mime="image/jpeg",
    )
    assert decision.provider.id == p_files.id
    assert decision.is_fallback is False
    assert decision.reservation.status == "reserved"

    # Active reservations count
    active_bytes = StorageMonitor.get_active_reserved_bytes(db_session, p_files.id)
    assert active_bytes >= 2 * 1024 * 1024

    # Release
    StorageRoutingManager.release_reservation(db_session, decision.reservation.id, "completed")
    assert StorageMonitor.get_active_reserved_bytes(db_session, p_files.id) == 0


@pytest.mark.anyio
async def test_routing_fallback_when_primary_full(db_session):
    ev = db_session.scalar(select(Event).where(Event.slug == "storage-test-event"))
    p_files = db_session.scalar(select(StorageProvider).where(StorageProvider.key == "files_ir_main"))
    p_local = db_session.scalar(select(StorageProvider).where(StorageProvider.key == "local_storage"))
    cfg = db_session.scalar(select(EventStorageConfig).where(EventStorageConfig.event_id == ev.id))
    cfg.primary_provider_id = p_files.id
    cfg.fallback_provider_ids_json = json.dumps([p_local.id])

    # Mock primary capacity as small
    p_files.health_status = "healthy"
    p_files.total_capacity_bytes = 1000
    db_session.commit()

    decision = await StorageRoutingManager.select_provider_and_reserve(
        db_session,
        event_id=ev.id,
        filename="large_photo.jpg",
        file_size=5000,
        mime="image/jpeg",
    )
    # Selected fallback provider
    assert decision.provider.id == p_local.id
    assert decision.is_fallback is True
    assert "فضا" in decision.fallback_reason or "کافی" in decision.fallback_reason


@pytest.mark.anyio
async def test_routing_rejects_when_all_full_or_disabled(db_session):
    ev = db_session.scalar(select(Event).where(Event.slug == "storage-test-event"))
    for p in db_session.scalars(select(StorageProvider)).all():
        p.is_enabled = False
    db_session.commit()

    with pytest.raises(StorageQuotaError):
        await StorageRoutingManager.select_provider_and_reserve(
            db_session,
            event_id=ev.id,
            filename="test.jpg",
            file_size=1024,
            mime="image/jpeg",
        )


# ---------------------------------------------------------------------------
# 5. Security & Masking Tests
# ---------------------------------------------------------------------------

def test_secret_masking():
    cfg = {
        "api_endpoint": "https://my.files.ir/api/v1",
        "api_key": "files_ir_super_secret_token",
        "workspace_id": 12,
    }
    masked = mask_config(cfg)
    assert masked["api_key"] != "files_ir_super_secret_token"
    assert "..." in masked["api_key"]
    assert masked["has_api_key"] is True

    # Unmask preserves original secret if masked sent back
    unmasked = unmask_config({"api_key": masked["api_key"], "workspace_id": 15}, cfg)
    assert unmasked["api_key"] == "files_ir_super_secret_token"
    assert unmasked["workspace_id"] == 15


# ---------------------------------------------------------------------------
# 6. Admin Storage API Integration Tests
# ---------------------------------------------------------------------------

def test_admin_storage_providers_endpoints(client):
    headers = _auth(client)

    # 1. List providers
    r = client.get("/api/admin/storage/providers", headers=headers)
    assert r.status_code == 200
    providers = r.json()["providers"]
    assert len(providers) >= 2
    # Ensure no secrets exposed in JSON
    for p in providers:
        if "api_key" in p["config"]:
            assert "..." in p["config"]["api_key"] or p["config"]["api_key"] == ""

    # 2. Storage monitor KPIs
    mon = client.get("/api/admin/storage/monitor", headers=headers)
    assert mon.status_code == 200
    data = mon.json()
    assert "global" in data
    assert "providers" in data
    assert "recentRoutingLogs" in data


def test_admin_event_storage_config(client, db_session):
    headers = _auth(client)
    ev = db_session.scalar(select(Event).where(Event.slug == "storage-test-event"))

    # Get config
    r = client.get(f"/api/admin/storage/events/{ev.id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["eventId"] == ev.id

    # Update config
    p_local = db_session.scalar(select(StorageProvider).where(StorageProvider.key == "local_storage"))
    up_r = client.put(
        f"/api/admin/storage/events/{ev.id}",
        json={"primaryProviderId": p_local.id, "fallbackProviderIds": []},
        headers=headers,
    )
    assert up_r.status_code == 200
    assert up_r.json()["primaryProviderId"] == p_local.id


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6. Direct Upload & Security Tests
# ---------------------------------------------------------------------------

import uuid
from app.services.tickets import issue_ticket

_guest_seq = [2100]


def _create_guest_session(client: TestClient, db, slug: str = "storage-test-event"):
    _guest_seq[0] += 1
    code = f"{_guest_seq[0]:04d}"
    ev = db.scalar(select(Event).where(Event.slug == slug))
    ticket, _ = issue_ticket(
        db,
        event_id=ev.id,
        order_id=None,
        holder_name="مهمان تست",
        phone="09121112222",
        public_code=code,
        group_name="A",
    )
    res = client.post(f"/api/events/{slug}/memories/gate", json={"serial": ticket.public_code})
    assert res.status_code == 200, res.text
    token = res.json()["sessionToken"]
    return token, ticket


def test_memories_direct_upload_lifecycle(client: TestClient, db_session):
    # Set primary provider to local_storage for seamless local resolution
    ev = db_session.scalar(select(Event).where(Event.slug == "storage-test-event"))
    p_local = db_session.scalar(select(StorageProvider).where(StorageProvider.key == "local_storage"))
    cfg = db_session.scalar(select(EventStorageConfig).where(EventStorageConfig.event_id == ev.id))
    cfg.primary_provider_id = p_local.id
    db_session.commit()

    token, ticket = _create_guest_session(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Direct upload init
    init_res = client.post(
        "/api/events/storage-test-event/memories/upload/init",
        json={
            "filename": "camera_photo.jpg",
            "sizeBytes": 1024 * 50,
            "mime": "image/jpeg",
            "mediaKind": "image",
            "consentPublish": True,
        },
        headers=headers,
    )
    assert init_res.status_code == 200, init_res.text
    init_data = init_res.json()
    assert "sessionId" in init_data
    session_id = init_data["sessionId"]
    assert init_data["uploadMode"] in ("server-proxy", "single", "s3-single")

    # Verify reservation created
    reservation = db_session.get(UploadReservation, session_id)
    assert reservation is not None
    assert reservation.status == "reserved"

    # 2. Direct upload complete
    complete_res = client.post(
        "/api/events/storage-test-event/memories/upload/complete",
        json={
            "sessionId": session_id,
            "consentPublish": True,
            "uploadKey": init_data.get("storedName", "camera_photo.jpg"),
        },
        headers=headers,
    )
    assert complete_res.status_code == 200, complete_res.text
    comp_data = complete_res.json()
    assert comp_data["ok"] is True
    item_id = comp_data["id"]

    # Verify memory item and asset created in DB
    item = db_session.get(MemoryItem, item_id)
    assert item is not None
    assert item.status == "pending"
    assert item.ticket_id == ticket.id

    asset = db_session.scalar(select(MediaAsset).where(MediaAsset.memory_item_id == item_id))
    assert asset is not None
    assert asset.provider_id == p_local.id

    # Verify reservation is marked completed
    db_session.refresh(reservation)
    assert reservation.status == "completed"


def test_memories_direct_upload_persian_rejections(client: TestClient, db_session):
    token, _ = _create_guest_session(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Consent required error
    r_consent = client.post(
        "/api/events/storage-test-event/memories/upload/init",
        json={
            "filename": "no_consent.jpg",
            "sizeBytes": 1000,
            "mime": "image/jpeg",
            "mediaKind": "image",
            "consentPublish": False,
        },
        headers=headers,
    )
    assert r_consent.status_code == 400
    assert "رضایت" in str(r_consent.json())

    # 2. File too large error
    r_large = client.post(
        "/api/events/storage-test-event/memories/upload/init",
        json={
            "filename": "huge.jpg",
            "sizeBytes": 500 * 1024 * 1024,  # exceeds image limit
            "mime": "image/jpeg",
            "mediaKind": "image",
            "consentPublish": True,
        },
        headers=headers,
    )
    assert r_large.status_code == 400
    assert "حجم فایل بیشتر از حد مجاز" in str(r_large.json())


def test_direct_upload_cancel_releases_reservation(client: TestClient, db_session):
    token, _ = _create_guest_session(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    init_res = client.post(
        "/api/events/storage-test-event/memories/upload/init",
        json={
            "filename": "cancel_me.jpg",
            "sizeBytes": 2048,
            "mime": "image/jpeg",
            "mediaKind": "image",
            "consentPublish": True,
        },
        headers=headers,
    )
    session_id = init_res.json()["sessionId"]
    reservation = db_session.get(UploadReservation, session_id)
    assert reservation.status == "reserved"

    cancel_res = client.post(
        "/api/events/storage-test-event/memories/upload/cancel",
        json={"sessionId": session_id},
        headers=headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["ok"] is True

    db_session.refresh(reservation)
    assert reservation.status == "cancelled"


def test_cross_event_media_isolation(client: TestClient, db_session):
    # Create Event B with another ticket
    ev_b = Event(
        slug="isolated-event-b",
        title="رویداد مجزا ب",
        episode_number=2,
        event_at=datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc),
        city="تهران",
        venue="تالار",
        capacity=50,
        ticket_price=0,
        status="sales_open",
        sales_status="open",
    )
    db_session.add(ev_b)
    db_session.commit()
    db_session.refresh(ev_b)

    # Issue ticket for Event A and Event B
    token_a, _ = _create_guest_session(client, db_session, slug="storage-test-event")
    token_b, _ = _create_guest_session(client, db_session, slug="isolated-event-b")

    # Upload item in Event A
    headers_a = {"Authorization": f"Bearer {token_a}"}
    init_res = client.post(
        "/api/events/storage-test-event/memories/upload/init",
        json={
            "filename": "event_a_photo.jpg",
            "sizeBytes": 1024,
            "mime": "image/jpeg",
            "mediaKind": "image",
            "consentPublish": True,
        },
        headers=headers_a,
    )
    comp_res = client.post(
        "/api/events/storage-test-event/memories/upload/complete",
        json={"sessionId": init_res.json()["sessionId"], "consentPublish": True},
        headers=headers_a,
    )
    item_id_a = comp_res.json()["id"]

    # Guest from Event B attempts to access Event A's file: must be forbidden / not found
    headers_b = {"Authorization": f"Bearer {token_b}"}
    get_res = client.get(
        f"/api/events/isolated-event-b/memories/files/{item_id_a}",
        headers=headers_b,
    )
    assert get_res.status_code in (403, 404)
