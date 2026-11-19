"""StorageMonitor: Tracks capacity, active reservations, health, and warning thresholds."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    MediaAsset,
    StorageProvider,
    StorageRoutingLog,
    StorageUsageSnapshot,
    UploadReservation,
    utcnow,
)
from app.services.storage.base_adapter import StorageUsage
from app.services.storage.provider_manager import ProviderManager

log = logging.getLogger("wwh.storage.storage_monitor")


class StorageMonitor:
    """Monitors storage usage across providers and generates health/quota snapshots."""

    @classmethod
    def get_active_reserved_bytes(cls, db: Session, provider_id: int) -> int:
        """Sum reserved bytes for active, non-expired upload sessions."""
        now = utcnow()
        total = db.scalar(
            select(func.sum(UploadReservation.file_size)).where(
                UploadReservation.provider_id == provider_id,
                UploadReservation.status == "reserved",
                UploadReservation.expires_at > now,
            )
        )
        return int(total or 0)

    @classmethod
    def get_stored_file_count(cls, db: Session, provider_id: int) -> int:
        count = db.scalar(
            select(func.count(MediaAsset.id)).where(
                MediaAsset.provider_id == provider_id,
                MediaAsset.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    @classmethod
    async def get_effective_provider_usage(
        cls,
        db: Session,
        provider: StorageProvider,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Compute live or cached usage including reservations and threshold levels."""
        adapter = ProviderManager.get_adapter_for_provider(provider)
        reserved_bytes = cls.get_active_reserved_bytes(db, provider.id)
        file_count = cls.get_stored_file_count(db, provider.id)

        try:
            raw_usage = await adapter.get_storage_usage()
            used_bytes = raw_usage.used_bytes

            # Configured provider capacity in DB takes precedence
            if provider.total_capacity_bytes and provider.total_capacity_bytes > 0:
                total_bytes = provider.total_capacity_bytes
                available_bytes = max(0, total_bytes - used_bytes)
            else:
                total_bytes = raw_usage.total_bytes or (10 * 1024 * 1024 * 1024)
                available_bytes = raw_usage.available_bytes
        except Exception as e:
            log.warning("Could not query provider %s storage usage: %s", provider.key, e)
            total_bytes = provider.total_capacity_bytes or (10 * 1024 * 1024 * 1024)
            stored_bytes = db.scalar(
                select(func.sum(MediaAsset.size_bytes)).where(
                    MediaAsset.provider_id == provider.id,
                    MediaAsset.deleted_at.is_(None),
                )
            ) or 0
            used_bytes = int(stored_bytes)
            available_bytes = max(0, total_bytes - used_bytes)

        effective_available = max(0, available_bytes - reserved_bytes)
        effective_used = used_bytes + reserved_bytes
        pct = min(100.0, (effective_used / total_bytes * 100.0)) if total_bytes > 0 else 0.0

        # Warning levels: 80% warning, 90% critical warning, 100% full
        warn_level = "normal"
        if pct >= 100.0 or effective_available <= 0:
            warn_level = "full"
        elif pct >= (settings.storage_critical_threshold * 100.0):
            warn_level = "critical"
        elif pct >= (settings.storage_warning_threshold * 100.0):
            warn_level = "warning"

        max_files = provider.file_count_limit or 3000
        files_full = bool(max_files and file_count >= max_files)

        is_accepting_uploads = bool(
            provider.is_enabled
            and provider.health_status != "unreachable"
            and warn_level != "full"
            and not files_full
        )

        return {
            "providerId": provider.id,
            "key": provider.key,
            "name": provider.name,
            "providerType": provider.provider_type,
            "isEnabled": provider.is_enabled,
            "healthStatus": provider.health_status,
            "totalBytes": total_bytes,
            "usedBytes": used_bytes,
            "reservedBytes": reserved_bytes,
            "effectiveUsedBytes": effective_used,
            "availableBytes": effective_available,
            "percentUsed": round(pct, 1),
            "fileCount": file_count,
            "maxFiles": max_files,
            "warningLevel": warn_level,  # normal | warning | critical | full
            "isAcceptingUploads": is_accepting_uploads,
            "lastCheckedAt": provider.last_health_check_at.isoformat() if provider.last_health_check_at else None,
        }

    @classmethod
    async def get_all_providers_overview(cls, db: Session) -> list[dict[str, Any]]:
        providers = db.scalars(select(StorageProvider).order_by(StorageProvider.priority.asc())).all()
        result: list[dict[str, Any]] = []
        for p in providers:
            info = await cls.get_effective_provider_usage(db, p)
            result.append(info)
        return result

    @classmethod
    def record_usage_snapshot(
        cls,
        db: Session,
        provider_id: int,
        usage: StorageUsage,
        status: str = "ok",
        error_msg: str = "",
    ) -> StorageUsageSnapshot:
        snap = StorageUsageSnapshot(
            provider_id=provider_id,
            total_bytes=usage.total_bytes,
            used_bytes=usage.used_bytes,
            available_bytes=usage.available_bytes,
            file_count=usage.file_count,
            max_files=usage.max_files or 0,
            status=status,
            error_message=error_msg,
            checked_at=utcnow(),
        )
        db.add(snap)
        db.commit()
        return snap
