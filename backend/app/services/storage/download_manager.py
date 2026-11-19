"""DownloadManager: Secure, authorized media retrieval across all storage providers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Media, MediaAsset, MemoryItem, StorageProvider
from app.services.storage.base_adapter import StorageError
from app.services.storage.local_adapter import LocalStorageAdapter
from app.services.storage.media_registry import MediaRegistry
from app.services.storage.provider_manager import ProviderManager

log = logging.getLogger("wwh.storage.download_manager")


class DownloadManager:
    """Manages authorization validation and download link resolution."""

    @classmethod
    async def resolve_media_response(
        cls,
        db: Session,
        asset: MediaAsset,
        *,
        as_attachment: bool = False,
        prefer_web: bool = True,
        filename_override: str | None = None,
    ) -> Response:
        """Resolve an asset into an authorized FastAPI Response (FileResponse, RedirectResponse, or Proxy)."""
        provider = db.get(StorageProvider, asset.provider_id) if asset.provider_id else None

        if not provider:
            # Fallback to local storage adapter
            adapter = LocalStorageAdapter({"root_dir": str(settings.storage_root)})
        else:
            adapter = ProviderManager.get_adapter_for_provider(provider)

        download_name = filename_override or asset.original_name or asset.stored_name

        # If Local Storage Adapter
        if isinstance(adapter, LocalStorageAdapter):
            path = adapter.resolve_local_path(asset.provider_file_id or asset.stored_name)
            if not path or not path.is_file():
                raise HTTPException(404, "File missing on storage server")
            media_type = asset.mime
            if prefer_web and not as_attachment and asset.media_category == "memories_video":
                web_candidate = path.with_name(f"{path.stem}_web.mp4")
                if web_candidate.is_file():
                    path = web_candidate
                    media_type = "video/mp4"

            headers = {}
            if as_attachment:
                headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
            return FileResponse(path, media_type=media_type, headers=headers)

        # External Cloud Provider (Files.ir, S3)
        try:
            download_url = await adapter.generate_download_link(
                asset.provider_file_id or asset.stored_name,
                expires_sec=3600,
            )
            headers = {"Cache-Control": "private, max-age=300"}
            if as_attachment:
                headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
            return RedirectResponse(url=download_url, status_code=307, headers=headers)
        except Exception as e:
            log.error("Could not generate cloud download link for asset %d: %s", asset.id, e)
            raise HTTPException(502, "Storage provider temporary download link failed")

    @classmethod
    async def resolve_memory_item_response(
        cls,
        db: Session,
        item: MemoryItem,
        *,
        as_attachment: bool = False,
        prefer_web: bool = True,
    ) -> Response:
        """Find or register MediaAsset for a MemoryItem and return its authorized download response."""
        asset = MediaRegistry.get_asset_by_memory_item_id(db, item.id)
        if not asset:
            asset = MediaRegistry.get_or_create_local_asset_for_memory(db, item)

        return await cls.resolve_media_response(
            db,
            asset,
            as_attachment=as_attachment,
            prefer_web=prefer_web,
            filename_override=f"memory-{item.id}{item.stored_name[-4:] if '.' in item.stored_name else ''}",
        )

    @classmethod
    async def resolve_archive_media_response(
        cls,
        db: Session,
        media: Media,
        *,
        as_attachment: bool = False,
    ) -> Response:
        """Find or register MediaAsset for an archive Media row and return authorized download response."""
        asset = MediaRegistry.get_asset_by_legacy_media_id(db, media.id)
        if not asset:
            asset = MediaRegistry.get_or_create_local_asset_for_archive(db, media)

        return await cls.resolve_media_response(
            db,
            asset,
            as_attachment=as_attachment,
            filename_override=media.original_name or media.filename,
        )
