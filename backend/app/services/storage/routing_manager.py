"""StorageRoutingManager: Deterministic primary-to-fallback selection with concurrency reservations."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Event,
    EventStorageConfig,
    StorageProvider,
    StorageRoutingLog,
    UploadReservation,
    utcnow,
)
from app.services.storage.base_adapter import StorageError, StorageQuotaError, StorageUnavailableError
from app.services.storage.storage_monitor import StorageMonitor

log = logging.getLogger("wwh.storage.routing_manager")


class RoutingDecision:
    def __init__(
        self,
        provider: StorageProvider,
        is_fallback: bool = False,
        fallback_reason: str = "",
        reservation: UploadReservation | None = None,
    ):
        self.provider = provider
        self.is_fallback = is_fallback
        self.fallback_reason = fallback_reason
        self.reservation = reservation


class StorageRoutingManager:
    """Selects eligible providers and manages reservation concurrency."""

    @classmethod
    def cleanup_expired_reservations(cls, db: Session) -> int:
        """Mark expired upload reservations as 'expired' to free reserved capacity."""
        now = utcnow()
        expired = db.scalars(
            select(UploadReservation).where(
                UploadReservation.status == "reserved",
                UploadReservation.expires_at < now,
            )
        ).all()
        count = len(expired)
        for r in expired:
            r.status = "expired"
        if count > 0:
            db.commit()
            log.info("Cleaned up %d expired upload reservations", count)
        return count

    @classmethod
    async def evaluate_provider_eligibility(
        cls,
        db: Session,
        provider: StorageProvider,
        file_size: int,
    ) -> tuple[bool, str]:
        """Check the 6 criteria:
        1. Enabled
        2. Reachable
        3. Sufficient storage space (considering active reservations)
        4. Remaining file count capacity
        5. File size within per-file limit
        6. Upload capabilities support requested size
        """
        # 1. Enabled
        if not provider.is_enabled:
            return False, "ارائه‌دهنده غیرفعال است."

        # 5. Per-file size limit
        if provider.max_file_size_bytes and file_size > provider.max_file_size_bytes:
            max_mb = provider.max_file_size_bytes // (1024 * 1024)
            return False, f"حجم فایل از سقف مجاز ارائه‌دهنده ({max_mb} مگابایت) بیشتر است."

        # 2, 3, 4: Live effective usage & limits
        usage = await StorageMonitor.get_effective_provider_usage(db, provider)

        if usage.get("healthStatus") == "unreachable":
            return False, f"ارائه‌دهنده در دسترس نیست ({provider.health_error or 'خطای اتصال'})."

        # 3. Sufficient storage space
        avail = usage.get("availableBytes", 0)
        if avail < file_size:
            return False, f"فضای کافی در مخزن باقی نمانده است (باقی‌مانده: {avail} بایت، نیاز: {file_size} بایت)."

        # 4. Remaining file count capacity
        max_files = usage.get("maxFiles")
        file_count = usage.get("fileCount", 0)
        if max_files and file_count >= max_files:
            return False, f"سقف تعداد فایل‌های ارائه‌دهنده ({max_files} فایل) تکمیل شده است."

        return True, "مناسب برای آپلود"

    @classmethod
    async def select_provider_and_reserve(
        cls,
        db: Session,
        *,
        event_id: int,
        filename: str,
        file_size: int,
        mime: str,
        media_kind: str = "image",
        category: str = "memories_photo",
        ticket_id: int | None = None,
    ) -> RoutingDecision:
        """Evaluate Primary -> Fallback 1 -> Fallback 2 ... in order, then make a reservation."""
        cls.cleanup_expired_reservations(db)

        # Get event storage config
        config = db.scalar(
            select(EventStorageConfig).where(EventStorageConfig.event_id == event_id)
        )
        if not config:
            # Auto-create default config if missing
            local_p = db.scalar(select(StorageProvider).where(StorageProvider.provider_type == "local"))
            primary_id = local_p.id if local_p else 1
            config = EventStorageConfig(
                event_id=event_id,
                primary_provider_id=primary_id,
                fallback_provider_ids_json="[]",
                routing_status="active",
            )
            db.add(config)
            db.commit()
            db.refresh(config)

        # Ordered candidate providers
        candidates: list[tuple[int, bool, int]] = []  # (provider_id, is_fallback, priority_order)
        candidates.append((config.primary_provider_id, False, 0))

        try:
            fallbacks = json.loads(config.fallback_provider_ids_json or "[]")
            if isinstance(fallbacks, list):
                for idx, fid in enumerate(fallbacks, start=1):
                    if fid != config.primary_provider_id:
                        candidates.append((int(fid), True, idx))
        except Exception:
            pass

        selected_provider: StorageProvider | None = None
        is_fallback = False
        skipped_reasons: list[str] = []

        for prov_id, is_fb, order_idx in candidates:
            prov = db.get(StorageProvider, prov_id)
            if not prov:
                continue

            eligible, reason = await cls.evaluate_provider_eligibility(db, prov, file_size)
            if eligible:
                selected_provider = prov
                is_fallback = is_fb
                # Log success
                log_entry = StorageRoutingLog(
                    event_id=event_id,
                    provider_id=prov.id,
                    file_size=file_size,
                    decision="selected",
                    reason=f"Priority {order_idx} ({'primary' if not is_fb else 'fallback'}) selected",
                    created_at=utcnow(),
                )
                db.add(log_entry)
                break
            else:
                skipped_reasons.append(f"{prov.name}: {reason}")
                log_entry = StorageRoutingLog(
                    event_id=event_id,
                    provider_id=prov.id,
                    file_size=file_size,
                    decision="skipped_full" if "فضا" in reason or "سقف" in reason else "skipped_unreachable",
                    reason=reason,
                    created_at=utcnow(),
                )
                db.add(log_entry)

        if not selected_provider:
            # Reject upload
            rejection_log = StorageRoutingLog(
                event_id=event_id,
                provider_id=None,
                file_size=file_size,
                decision="rejected_all",
                reason=" | ".join(skipped_reasons) or "هیچ ارائه‌دهنده مجازی یافت نشد",
                created_at=utcnow(),
            )
            db.add(rejection_log)
            # Update event routing status to failed
            config.routing_status = "failed"
            db.commit()

            raise StorageQuotaError(
                "ظرفیت فضای ذخیره‌سازی تکمیل شده است یا سرویس‌ها در دسترس نیستند.",
                details={"reasons": skipped_reasons},
            )

        # Update event routing status
        if is_fallback:
            config.routing_status = "degraded"
        else:
            config.routing_status = "active"

        # Create upload reservation (Concurrency control)
        ttl_sec = settings.storage_reservation_ttl_sec or 1800
        expires = utcnow() + timedelta(seconds=ttl_sec)
        session_id = uuid.uuid4().hex

        reservation = UploadReservation(
            id=session_id,
            event_id=event_id,
            ticket_id=ticket_id,
            provider_id=selected_provider.id,
            upload_mode="s3-single" if selected_provider.provider_type in ("files_ir", "s3") else "single",
            filename=filename,
            file_size=file_size,
            mime=mime,
            media_kind=media_kind,
            category=category,
            status="reserved",
            expires_at=expires,
            created_at=utcnow(),
        )
        db.add(reservation)
        db.commit()
        db.refresh(reservation)

        fallback_reason = skipped_reasons[0] if is_fallback and skipped_reasons else ""
        return RoutingDecision(
            provider=selected_provider,
            is_fallback=is_fallback,
            fallback_reason=fallback_reason,
            reservation=reservation,
        )

    @classmethod
    def release_reservation(cls, db: Session, session_id: str, new_status: str = "completed") -> None:
        """Release or complete a reservation."""
        res = db.get(UploadReservation, session_id)
        if res and res.status == "reserved":
            res.status = new_status
            db.commit()
