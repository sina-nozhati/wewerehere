"""FolderManager: Manages standardized event folder hierarchies and path resolution."""

from __future__ import annotations

import logging
import secrets
import unicodedata
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, EventStorageFolder, StorageProvider, utcnow
from app.services.storage.base_adapter import FolderInfo, StorageProviderAdapter
from app.services.storage.provider_manager import ProviderManager

log = logging.getLogger("wwh.storage.folder_manager")

STANDARD_PURPOSES = [
    "root",
    "memories_photos",
    "memories_videos",
    "memories_other",
    "official_photos",
    "official_videos",
    "exports",
]


class FolderManager:
    """Manages the creation and retrieval of standardized event storage folders."""

    @classmethod
    def generate_safe_stored_filename(cls, original_filename: str, media_kind: str = "image") -> str:
        """Generate unique, non-guessable asset filename without ticket codes or sensitive details."""
        ext = ""
        if "." in original_filename:
            raw_ext = original_filename.rsplit(".", 1)[-1].lower()
            if len(raw_ext) <= 5 and raw_ext.isalnum():
                ext = f".{raw_ext}"
        if not ext:
            ext = ".jpg" if media_kind == "image" else (".mp4" if media_kind == "video" else ".bin")

        token = secrets.token_hex(16)
        u = uuid.uuid4().hex[:8]
        return f"{u}-{token}{ext}"

    @classmethod
    def get_standard_paths(cls, event: Event) -> dict[str, str]:
        """Compute the standardized hierarchy paths for an event."""
        year = str(event.event_at.year if event.event_at else "2026")
        slug = (event.slug or f"event-{event.id}").strip().lower()

        base = f"WE WERE HERE/Events/{year}/{slug}"
        return {
            "root": base,
            "memories_photos": f"{base}/Memories/Photos",
            "memories_videos": f"{base}/Memories/Videos",
            "memories_other": f"{base}/Memories/Other",
            "official_photos": f"{base}/Official-Media/Photos",
            "official_videos": f"{base}/Official-Media/Videos",
            "exports": f"{base}/Exports",
        }

    @classmethod
    async def ensure_event_folders(
        cls,
        db: Session,
        event_id: int,
        provider_id: int,
    ) -> dict[str, EventStorageFolder]:
        """Ensure all standardized folders exist on the provider and are recorded in the DB."""
        event = db.get(Event, event_id)
        if not event:
            return {}

        provider = db.get(StorageProvider, provider_id)
        if not provider:
            return {}

        adapter = ProviderManager.get_adapter_for_provider(provider)
        paths = cls.get_standard_paths(event)

        # Check existing folder mappings in DB
        existing = {
            f.folder_purpose: f
            for f in db.scalars(
                select(EventStorageFolder).where(
                    EventStorageFolder.event_id == event_id,
                    EventStorageFolder.provider_id == provider_id,
                )
            ).all()
        }

        # Root folder
        root_mapping = existing.get("root")
        root_folder_id = root_mapping.provider_folder_id if root_mapping else None
        if not root_mapping:
            try:
                root_info = await adapter.create_or_get_folder(paths["root"])
                root_mapping = EventStorageFolder(
                    event_id=event_id,
                    provider_id=provider_id,
                    folder_purpose="root",
                    provider_folder_id=str(root_info.folder_id),
                    provider_folder_path=root_info.path,
                    created_at=utcnow(),
                )
                db.add(root_mapping)
                db.flush()
                existing["root"] = root_mapping
                root_folder_id = str(root_info.folder_id)
            except Exception as e:
                log.warning("Could not create root folder on provider %s: %s", provider_id, e)

        # Child folders
        for purpose, path in paths.items():
            if purpose == "root" or purpose in existing:
                continue

            try:
                folder_info = await adapter.create_or_get_folder(
                    path,
                    parent_folder_id=root_folder_id,
                )
                mapping = EventStorageFolder(
                    event_id=event_id,
                    provider_id=provider_id,
                    folder_purpose=purpose,
                    provider_folder_id=str(folder_info.folder_id),
                    provider_folder_path=folder_info.path,
                    created_at=utcnow(),
                )
                db.add(mapping)
                existing[purpose] = mapping
            except Exception as e:
                log.warning("Could not create folder for purpose %s: %s", purpose, e)

        db.commit()
        return existing

    @classmethod
    async def get_folder_for_upload(
        cls,
        db: Session,
        event_id: int,
        provider_id: int,
        category: str = "memories_photo",
    ) -> EventStorageFolder | None:
        """Resolve the target folder for a specific upload category."""
        purpose_map = {
            "memories_photo": "memories_photos",
            "memories_video": "memories_videos",
            "official_photo": "official_photos",
            "official_video": "official_videos",
            "export": "exports",
        }
        purpose = purpose_map.get(category, "memories_other")

        folder = db.scalar(
            select(EventStorageFolder).where(
                EventStorageFolder.event_id == event_id,
                EventStorageFolder.provider_id == provider_id,
                EventStorageFolder.folder_purpose == purpose,
            )
        )
        if folder:
            return folder

        # Ensure folders on demand
        folders = await cls.ensure_event_folders(db, event_id, provider_id)
        return folders.get(purpose) or folders.get("root")
