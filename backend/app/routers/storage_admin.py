"""Admin router for Storage Provider Management, Event Routing, and Storage Monitoring."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import (
    Event,
    EventStorageConfig,
    EventStorageFolder,
    MediaAsset,
    StorageProvider,
    StorageRoutingLog,
    UploadReservation,
    utcnow,
)
from app.services.storage.folder_manager import FolderManager
from app.services.storage.media_registry import MediaRegistry
from app.services.storage.provider_manager import ProviderManager, mask_config, unmask_config
from app.services.storage.storage_monitor import StorageMonitor

log = logging.getLogger("wwh.routers.storage_admin")

router = APIRouter(prefix="/api/admin/storage", tags=["admin-storage"])


class ProviderUpdateBody(BaseModel):
    name: str | None = None
    isEnabled: bool | None = None
    priority: int | None = None
    config: dict[str, Any] | None = None
    maxFileSizeBytes: int | None = None
    fileCountLimit: int | None = None
    totalCapacityBytes: int | None = None


class ProviderCreateBody(BaseModel):
    key: str
    name: str
    providerType: str  # files_ir | s3 | local
    isEnabled: bool = True
    priority: int = 2
    config: dict[str, Any] = {}
    maxFileSizeBytes: int = 500 * 1024 * 1024
    fileCountLimit: int | None = 3000
    totalCapacityBytes: int | None = 10 * 1024 * 1024 * 1024


class EventStorageConfigBody(BaseModel):
    primaryProviderId: int
    fallbackProviderIds: list[int] = []


def _provider_admin_card(p: StorageProvider, usage_data: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        raw_cfg = json.loads(p.config_json or "{}")
    except Exception:
        raw_cfg = {}

    adapter = ProviderManager.get_adapter_for_provider(p)
    caps = adapter.get_capabilities()

    return {
        "id": p.id,
        "key": p.key,
        "name": p.name,
        "providerType": p.provider_type,
        "isEnabled": p.is_enabled,
        "priority": p.priority,
        "config": mask_config(raw_cfg),
        "maxFileSizeBytes": p.max_file_size_bytes,
        "fileCountLimit": p.file_count_limit,
        "totalCapacityBytes": p.total_capacity_bytes,
        "lastHealthCheckAt": p.last_health_check_at.isoformat() if p.last_health_check_at else None,
        "healthStatus": p.health_status,
        "healthError": p.health_error,
        "capabilities": {
            "supportsDirectUpload": caps.supports_direct_upload,
            "supportsMultipartUpload": caps.supports_multipart_upload,
            "supportsResumableUpload": caps.supports_resumable_upload,
            "supportsFolders": caps.supports_folders,
            "supportsTemporaryDownloadLinks": caps.supports_temporary_download_links,
            "maxFileSizeBytes": caps.max_file_size_bytes,
        },
        "usage": usage_data or {},
    }


@router.get("/providers")
async def list_providers(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """List all storage providers with health status, masked secrets, and usage metrics."""
    providers = db.scalars(select(StorageProvider).order_by(StorageProvider.priority.asc())).all()
    result = []
    for p in providers:
        usage = await StorageMonitor.get_effective_provider_usage(db, p)
        result.append(_provider_admin_card(p, usage))
    return {"providers": result}


@router.post("/providers")
async def create_provider(
    body: ProviderCreateBody,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    key = body.key.strip().lower()
    if not key:
        raise HTTPException(400, {"error": "کلید ارائه‌دهنده الزامی است."})
    if body.providerType not in ("files_ir", "s3", "local"):
        raise HTTPException(400, {"error": "نوع ارائه‌دهنده نامعتبر است."})

    existing = db.scalar(select(StorageProvider).where(StorageProvider.key == key))
    if existing:
        raise HTTPException(409, {"error": "ارائه‌دهنده‌ای با این کلید از قبل وجود دارد."})

    p = StorageProvider(
        key=key,
        name=body.name.strip() or key,
        provider_type=body.providerType,
        is_enabled=body.isEnabled,
        priority=body.priority,
        config_json=json.dumps(body.config or {}),
        max_file_size_bytes=body.maxFileSizeBytes,
        file_count_limit=body.fileCountLimit,
        total_capacity_bytes=body.totalCapacityBytes,
        health_status="unknown",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    usage = await StorageMonitor.get_effective_provider_usage(db, p)
    return {"ok": True, "provider": _provider_admin_card(p, usage)}


@router.put("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    body: ProviderUpdateBody,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    p = db.get(StorageProvider, provider_id)
    if not p:
        raise HTTPException(404, {"error": "ارائه‌دهنده یافت نشد."})

    if body.name is not None:
        p.name = body.name.strip()
    if body.isEnabled is not None:
        p.is_enabled = body.isEnabled
    if body.priority is not None:
        p.priority = body.priority
    if body.maxFileSizeBytes is not None:
        p.max_file_size_bytes = body.maxFileSizeBytes
    if body.fileCountLimit is not None:
        p.file_count_limit = body.fileCountLimit
    if body.totalCapacityBytes is not None:
        p.total_capacity_bytes = body.totalCapacityBytes

    if body.config is not None:
        try:
            old_cfg = json.loads(p.config_json or "{}")
        except Exception:
            old_cfg = {}
        merged_cfg = unmask_config(body.config, old_cfg)
        p.config_json = json.dumps(merged_cfg)

    p.updated_at = utcnow()
    db.commit()
    db.refresh(p)
    usage = await StorageMonitor.get_effective_provider_usage(db, p)
    return {"ok": True, "provider": _provider_admin_card(p, usage)}


@router.post("/providers/{provider_id}/test")
async def test_provider_connection(
    provider_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Test provider connectivity and update DB health status."""
    try:
        res = await ProviderManager.test_provider_health(db, provider_id)
        return res
    except Exception as e:
        raise HTTPException(400, {"error": str(e)})


@router.get("/events/{event_id}")
async def get_event_storage_config(
    event_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, {"error": "رویداد یافت نشد."})

    cfg = db.scalar(select(EventStorageConfig).where(EventStorageConfig.event_id == event_id))
    if not cfg:
        # Default assignment
        local_p = db.scalar(select(StorageProvider).where(StorageProvider.provider_type == "local"))
        files_p = db.scalar(select(StorageProvider).where(StorageProvider.provider_type == "files_ir"))
        primary_id = files_p.id if files_p and files_p.is_enabled else (local_p.id if local_p else 1)
        fallback_ids = [local_p.id] if local_p and local_p.id != primary_id else []

        cfg = EventStorageConfig(
            event_id=event_id,
            primary_provider_id=primary_id,
            fallback_provider_ids_json=json.dumps(fallback_ids),
            routing_status="active",
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)

    # Auto-ensure event folders if not yet created for the primary provider
    if cfg.primary_provider_id:
        try:
            folder_count = db.scalar(
                select(func.count(EventStorageFolder.id)).where(
                    EventStorageFolder.event_id == event_id,
                    EventStorageFolder.provider_id == cfg.primary_provider_id,
                )
            ) or 0
            if folder_count == 0:
                await FolderManager.ensure_event_folders(db, event_id, cfg.primary_provider_id)
        except Exception as e:
            log.warning("Auto-ensuring folders for event %s failed: %s", event_id, e)

    try:
        fallbacks = json.loads(cfg.fallback_provider_ids_json or "[]")
    except Exception:
        fallbacks = []

    # Folders mapped for this event
    folders = db.scalars(
        select(EventStorageFolder).where(EventStorageFolder.event_id == event_id)
    ).all()

    return {
        "eventId": event_id,
        "eventSlug": ev.slug,
        "eventTitle": ev.title,
        "primaryProviderId": cfg.primary_provider_id,
        "fallbackProviderIds": fallbacks,
        "routingStatus": cfg.routing_status,
        "folders": [
            {
                "providerId": f.provider_id,
                "purpose": f.folder_purpose,
                "folderId": f.provider_folder_id,
                "path": f.provider_folder_path,
            }
            for f in folders
        ],
    }


@router.post("/events/{event_id}/sync-folders")
async def sync_event_storage_folders(
    event_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Explicitly provision and synchronize standardized event folders for configured providers."""
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, {"error": "رویداد یافت نشد."})

    cfg = db.scalar(select(EventStorageConfig).where(EventStorageConfig.event_id == event_id))
    if not cfg or not cfg.primary_provider_id:
        raise HTTPException(400, {"error": "پیکربندی ذخیره‌سازی برای این رویداد وجود ندارد."})

    try:
        await FolderManager.ensure_event_folders(db, event_id, cfg.primary_provider_id)
    except Exception as e:
        log.error("Sync folders failed for event %d on provider %d: %s", event_id, cfg.primary_provider_id, e)
        raise HTTPException(502, {"error": f"همگام‌سازی پوشه‌ها با ارائه‌دهنده با خطا مواجه شد: {str(e)}"}) from e

    folders = db.scalars(
        select(EventStorageFolder).where(EventStorageFolder.event_id == event_id)
    ).all()

    return {
        "ok": True,
        "eventId": event_id,
        "primaryProviderId": cfg.primary_provider_id,
        "folderCount": len(folders),
        "folders": [
            {
                "providerId": f.provider_id,
                "purpose": f.folder_purpose,
                "folderId": f.provider_folder_id,
                "path": f.provider_folder_path,
            }
            for f in folders
        ],
    }


@router.put("/events/{event_id}")
async def update_event_storage_config(
    event_id: int,
    body: EventStorageConfigBody,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, {"error": "رویداد یافت نشد."})

    primary = db.get(StorageProvider, body.primaryProviderId)
    if not primary:
        raise HTTPException(400, {"error": "ارائه‌دهنده اصلی نامعتبر است."})
    if not primary.is_enabled:
        raise HTTPException(400, {"error": "ارائه‌دهنده اصلی انتخاب شده غیرفعال است."})

    # Validate fallbacks: no duplicates, no disabled providers
    cleaned_fallbacks: list[int] = []
    seen = {primary.id}
    for fid in body.fallbackProviderIds:
        if fid in seen:
            continue
        p = db.get(StorageProvider, fid)
        if not p:
            raise HTTPException(400, {"error": f"ارائه‌دهنده جایگزین با شناسه {fid} یافت نشد."})
        if not p.is_enabled:
            raise HTTPException(400, {"error": f"ارائه‌دهنده جایگزین '{p.name}' غیرفعال است."})
        cleaned_fallbacks.append(fid)
        seen.add(fid)

    cfg = db.scalar(select(EventStorageConfig).where(EventStorageConfig.event_id == event_id))
    if not cfg:
        cfg = EventStorageConfig(
            event_id=event_id,
            primary_provider_id=primary.id,
            fallback_provider_ids_json=json.dumps(cleaned_fallbacks),
            routing_status="active",
        )
        db.add(cfg)
    else:
        cfg.primary_provider_id = primary.id
        cfg.fallback_provider_ids_json = json.dumps(cleaned_fallbacks)
        cfg.routing_status = "active"
        cfg.updated_at = utcnow()

    db.commit()

    # Pre-create standard folders for primary provider
    try:
        await FolderManager.ensure_event_folders(db, event_id, primary.id)
    except Exception as e:
        log.warning("Could not auto-create standard folders for primary provider %d: %s", primary.id, e)

    return {
        "ok": True,
        "eventId": event_id,
        "primaryProviderId": cfg.primary_provider_id,
        "fallbackProviderIds": cleaned_fallbacks,
        "routingStatus": cfg.routing_status,
    }


@router.get("/monitor")
async def storage_monitor_dashboard(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Aggregate monitoring view for capacity, thresholds, upload activities, and routing logs."""
    overview = await StorageMonitor.get_all_providers_overview(db)

    # Global totals
    total_capacity = sum(p.get("totalBytes", 0) for p in overview)
    total_used = sum(p.get("usedBytes", 0) for p in overview)
    total_reserved = sum(p.get("reservedBytes", 0) for p in overview)
    total_available = sum(p.get("availableBytes", 0) for p in overview)
    global_pct = round((total_used + total_reserved) / total_capacity * 100.0, 1) if total_capacity > 0 else 0.0

    # Recent routing logs
    recent_logs = db.scalars(
        select(StorageRoutingLog).order_by(StorageRoutingLog.id.desc()).limit(30)
    ).all()

    # Active reservations count
    active_reservations = int(
        db.scalar(
            select(func.count(UploadReservation.id)).where(
                UploadReservation.status == "reserved",
                UploadReservation.expires_at > utcnow(),
            )
        ) or 0
    )

    return {
        "global": {
            "totalCapacityBytes": total_capacity,
            "totalUsedBytes": total_used,
            "totalReservedBytes": total_reserved,
            "totalAvailableBytes": total_available,
            "percentUsed": global_pct,
            "activeReservationsCount": active_reservations,
        },
        "providers": overview,
        "recentRoutingLogs": [
            {
                "id": log_item.id,
                "eventId": log_item.event_id,
                "providerId": log_item.provider_id,
                "fileSize": log_item.file_size,
                "decision": log_item.decision,
                "reason": log_item.reason,
                "createdAt": log_item.created_at.isoformat() if log_item.created_at else "",
            }
            for log_item in recent_logs
        ],
    }


@router.get("/events/{event_id}/media-overview")
def event_media_overview(
    event_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Media breakdown by actual provider used, categories, and sizes."""
    return MediaRegistry.get_event_media_overview(db, event_id)
