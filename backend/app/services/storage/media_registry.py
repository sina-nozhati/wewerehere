"""MediaRegistry: Centralized media tracking independently of storage providers."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Media, MediaAsset, MemoryItem, StorageProvider, utcnow

log = logging.getLogger("wwh.storage.media_registry")


class MediaRegistry:
    """Operations on the central MediaAsset table."""

    @classmethod
    def register_asset(
        cls,
        db: Session,
        *,
        event_id: int,
        provider_id: int,
        provider_type: str,
        provider_file_id: str,
        stored_name: str,
        original_name: str,
        mime: str,
        size_bytes: int,
        media_category: str = "memories_photo",
        memory_item_id: int | None = None,
        legacy_media_id: int | None = None,
        ticket_id: int | None = None,
        provider_folder_id: str = "",
        provider_path: str = "",
        provider_workspace_id: str = "",
        upload_session_ref: str = "",
        upload_status: str = "completed",
    ) -> MediaAsset:
        """Create or update a central media asset record."""
        existing = db.scalar(select(MediaAsset).where(MediaAsset.stored_name == stored_name))
        if existing:
            existing.provider_file_id = provider_file_id
            existing.provider_folder_id = provider_folder_id
            existing.provider_path = provider_path
            existing.size_bytes = size_bytes
            existing.mime = mime
            existing.upload_status = upload_status
            existing.updated_at = utcnow()
            db.commit()
            db.refresh(existing)
            return existing

        asset = MediaAsset(
            event_id=event_id,
            memory_item_id=memory_item_id,
            legacy_media_id=legacy_media_id,
            ticket_id=ticket_id,
            provider_id=provider_id,
            provider_type=provider_type,
            provider_workspace_id=str(provider_workspace_id),
            provider_file_id=str(provider_file_id),
            provider_folder_id=str(provider_folder_id),
            provider_path=str(provider_path),
            original_name=original_name,
            stored_name=stored_name,
            mime=mime,
            size_bytes=size_bytes,
            media_category=media_category,
            upload_status=upload_status,
            upload_session_ref=upload_session_ref,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset

    @classmethod
    def get_asset_by_id(cls, db: Session, asset_id: int) -> MediaAsset | None:
        return db.get(MediaAsset, asset_id)

    @classmethod
    def get_asset_by_memory_item_id(cls, db: Session, memory_item_id: int) -> MediaAsset | None:
        return db.scalar(
            select(MediaAsset).where(
                MediaAsset.memory_item_id == memory_item_id,
                MediaAsset.deleted_at.is_(None),
            )
        )

    @classmethod
    def get_asset_by_legacy_media_id(cls, db: Session, legacy_media_id: int) -> MediaAsset | None:
        return db.scalar(
            select(MediaAsset).where(
                MediaAsset.legacy_media_id == legacy_media_id,
                MediaAsset.deleted_at.is_(None),
            )
        )

    @classmethod
    def get_or_create_local_asset_for_memory(cls, db: Session, item: MemoryItem) -> MediaAsset:
        """Ensure an existing local memory item is registered in MediaAsset table (Archive Policy: KEEP)."""
        existing = cls.get_asset_by_memory_item_id(db, item.id)
        if existing:
            return existing

        local_prov = db.scalar(
            select(StorageProvider).where(StorageProvider.provider_type == "local")
        )
        prov_id = local_prov.id if local_prov else 1
        cat = "memories_video" if item.media_kind == "video" else "memories_photo"

        return cls.register_asset(
            db,
            event_id=item.event_id,
            provider_id=prov_id,
            provider_type="local",
            provider_file_id=item.stored_name,
            stored_name=item.stored_name,
            original_name=f"memory-{item.id}",
            mime=item.mime,
            size_bytes=item.size_bytes or 0,
            media_category=cat,
            memory_item_id=item.id,
            ticket_id=item.ticket_id,
            upload_status="completed",
        )

    @classmethod
    def get_or_create_local_asset_for_archive(cls, db: Session, media: Media) -> MediaAsset:
        """Ensure an existing local archive media item is registered in MediaAsset table (Archive Policy: KEEP)."""
        existing = cls.get_asset_by_legacy_media_id(db, media.id)
        if existing:
            return existing

        local_prov = db.scalar(
            select(StorageProvider).where(StorageProvider.provider_type == "local")
        )
        prov_id = local_prov.id if local_prov else 1

        return cls.register_asset(
            db,
            event_id=media.event_id,
            provider_id=prov_id,
            provider_type="local",
            provider_file_id=media.filename,
            stored_name=media.filename,
            original_name=media.original_name or media.filename,
            mime=media.mime,
            size_bytes=media.size or 0,
            media_category="official_photo",
            legacy_media_id=media.id,
            upload_status="completed",
        )

    @classmethod
    def get_event_media_overview(cls, db: Session, event_id: int) -> dict[str, Any]:
        """Aggregate breakdown of assets stored for an event."""
        assets = db.scalars(
            select(MediaAsset).where(
                MediaAsset.event_id == event_id,
                MediaAsset.deleted_at.is_(None),
            )
        ).all()

        total_count = len(assets)
        total_size = sum(a.size_bytes for a in assets)
        photos_count = sum(1 for a in assets if "photo" in a.media_category or a.mime.startswith("image/"))
        videos_count = sum(1 for a in assets if "video" in a.media_category or a.mime.startswith("video/"))
        other_count = total_count - photos_count - videos_count

        provider_breakdown: dict[str, dict[str, Any]] = {}
        providers = {p.id: p for p in db.scalars(select(StorageProvider)).all()}

        for a in assets:
            prov = providers.get(a.provider_id)
            prov_name = prov.name if prov else a.provider_type
            if prov_name not in provider_breakdown:
                provider_breakdown[prov_name] = {"count": 0, "size": 0, "type": a.provider_type}
            provider_breakdown[prov_name]["count"] += 1
            provider_breakdown[prov_name]["size"] += a.size_bytes

        return {
            "eventId": event_id,
            "totalCount": total_count,
            "totalSizeBytes": total_size,
            "photosCount": photos_count,
            "videosCount": videos_count,
            "otherCount": other_count,
            "providerBreakdown": provider_breakdown,
        }
