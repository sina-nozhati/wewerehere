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
        """Ensure all standardized folders exist on the provider in clean hierarchy and are recorded in DB."""
        event = db.get(Event, event_id)
        if not event:
            return {}

        provider = db.get(StorageProvider, provider_id)
        if not provider:
            return {}

        adapter = ProviderManager.get_adapter_for_provider(provider)
        paths = cls.get_standard_paths(event)
        base = paths["root"]

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

        # 1. Root folder: "WE WERE HERE/Events/{year}/{slug}"
        root_mapping = existing.get("root")
        root_folder_id = root_mapping.provider_folder_id if (root_mapping and root_mapping.provider_folder_id and root_mapping.provider_folder_id != "None") else None
        if not root_folder_id:
            try:
                root_info = await adapter.create_or_get_folder(base)
                root_folder_id = str(root_info.folder_id)
                if not root_mapping:
                    root_mapping = EventStorageFolder(
                        event_id=event_id,
                        provider_id=provider_id,
                        folder_purpose="root",
                        provider_folder_id=root_folder_id,
                        provider_folder_path=base,
                        created_at=utcnow(),
                    )
                    db.add(root_mapping)
                else:
                    root_mapping.provider_folder_id = root_folder_id
                    root_mapping.provider_folder_path = base
                db.flush()
                existing["root"] = root_mapping
            except Exception as e:
                log.warning("Could not create root folder on provider %s: %s", provider_id, e)

        # Helper to record or update mapping
        def _record_mapping(purpose: str, folder_id: str, canonical_path: str):
            mapping = existing.get(purpose)
            if not mapping:
                mapping = EventStorageFolder(
                    event_id=event_id,
                    provider_id=provider_id,
                    folder_purpose=purpose,
                    provider_folder_id=str(folder_id),
                    provider_folder_path=canonical_path,
                    created_at=utcnow(),
                )
                db.add(mapping)
            else:
                mapping.provider_folder_id = str(folder_id)
                mapping.provider_folder_path = canonical_path
            db.flush()
            existing[purpose] = mapping

        # 2. Branch folders and single-segment relative child folders under root
        # A. Memories branch: "Memories"
        mem_children = [
            ("memories_photos", "Photos", paths["memories_photos"]),
            ("memories_videos", "Videos", paths["memories_videos"]),
            ("memories_other", "Other", paths["memories_other"]),
        ]
        mem_needed = any(
            not (existing.get(p) and existing.get(p).provider_folder_id and existing.get(p).provider_folder_id != "None")
            for p, _, _ in mem_children
        )
        mem_branch_id = None
        if root_folder_id and mem_needed:
            try:
                mem_branch = await adapter.create_or_get_folder("Memories", parent_folder_id=root_folder_id)
                mem_branch_id = str(mem_branch.folder_id)
            except Exception as e:
                log.warning("Could not create Memories branch folder: %s", e)

        for purpose, child_name, canonical_path in mem_children:
            curr = existing.get(purpose)
            if curr and curr.provider_folder_id and curr.provider_folder_id != "None":
                # Ensure canonical path is clean in DB
                curr.provider_folder_path = canonical_path
                continue
            if mem_branch_id:
                try:
                    f_info = await adapter.create_or_get_folder(child_name, parent_folder_id=mem_branch_id)
                    _record_mapping(purpose, str(f_info.folder_id), canonical_path)
                except Exception as e:
                    log.warning("Could not create child folder %s: %s", purpose, e)

        # B. Official-Media branch: "Official-Media"
        off_children = [
            ("official_photos", "Photos", paths["official_photos"]),
            ("official_videos", "Videos", paths["official_videos"]),
        ]
        off_needed = any(
            not (existing.get(p) and existing.get(p).provider_folder_id and existing.get(p).provider_folder_id != "None")
            for p, _, _ in off_children
        )
        off_branch_id = None
        if root_folder_id and off_needed:
            try:
                off_branch = await adapter.create_or_get_folder("Official-Media", parent_folder_id=root_folder_id)
                off_branch_id = str(off_branch.folder_id)
            except Exception as e:
                log.warning("Could not create Official-Media branch folder: %s", e)

        for purpose, child_name, canonical_path in off_children:
            curr = existing.get(purpose)
            if curr and curr.provider_folder_id and curr.provider_folder_id != "None":
                curr.provider_folder_path = canonical_path
                continue
            if off_branch_id:
                try:
                    f_info = await adapter.create_or_get_folder(child_name, parent_folder_id=off_branch_id)
                    _record_mapping(purpose, str(f_info.folder_id), canonical_path)
                except Exception as e:
                    log.warning("Could not create child folder %s: %s", purpose, e)

        # C. Exports branch: "Exports" directly under root
        exp_curr = existing.get("exports")
        if not (exp_curr and exp_curr.provider_folder_id and exp_curr.provider_folder_id != "None"):
            if root_folder_id:
                try:
                    exp_info = await adapter.create_or_get_folder("Exports", parent_folder_id=root_folder_id)
                    _record_mapping("exports", str(exp_info.folder_id), paths["exports"])
                except Exception as e:
                    log.warning("Could not create Exports folder: %s", e)
        elif exp_curr:
            exp_curr.provider_folder_path = paths["exports"]

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
        if folder and folder.provider_folder_id and folder.provider_folder_id != "None":
            return folder

        # Ensure folders on demand
        folders = await cls.ensure_event_folders(db, event_id, provider_id)
        return folders.get(purpose) or folders.get("root")
