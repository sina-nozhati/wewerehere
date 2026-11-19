"""Local VPS Storage Provider Adapter for legacy media preservation and dev fallback."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.storage.base_adapter import (
    FileEntryInfo,
    FolderInfo,
    ProviderCapabilities,
    StorageError,
    StorageProviderAdapter,
    StorageQuotaError,
    StorageUsage,
    UploadSessionInfo,
)


class LocalStorageAdapter(StorageProviderAdapter):
    """Adapter for local VPS filesystem storage (preserves existing media and enables dev fallback)."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config or {})
        self.root_dir = Path(self.config.get("root_dir") or settings.storage_root).resolve()
        self.max_file_size = int(self.config.get("max_file_size_bytes") or 100 * 1024 * 1024)

    @property
    def provider_type(self) -> str:
        return "local"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_type="local",
            supports_direct_upload=False,  # Browser uploads to backend server
            supports_multipart_upload=False,
            supports_resumable_upload=False,
            supports_folders=True,
            supports_temporary_download_links=False,
            supports_space_usage_query=True,
            supports_file_count_limit=False,
            max_file_size_bytes=self.max_file_size,
        )

    async def validate_credentials(self) -> bool:
        return True

    async def check_connectivity(self) -> tuple[bool, str]:
        try:
            self.root_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.root_dir / ".storage_check"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            return True, "فضای ذخیره‌سازی محلی سرور در دسترس و قابل نوشتن است."
        except Exception as e:
            return False, f"خطای دسترسی به حافظه محلی: {str(e)}"

    async def get_storage_usage(self) -> StorageUsage:
        try:
            total, used, free = shutil.disk_usage(self.root_dir)
            return StorageUsage(
                total_bytes=total,
                used_bytes=used,
                available_bytes=free,
                refreshed_at=datetime.now(timezone.utc),
            )
        except Exception:
            return StorageUsage(
                total_bytes=50 * 1024 * 1024 * 1024,
                used_bytes=0,
                available_bytes=50 * 1024 * 1024 * 1024,
                refreshed_at=datetime.now(timezone.utc),
            )

    async def create_or_get_folder(
        self,
        folder_path: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FolderInfo:
        clean = folder_path.strip().replace("\\", "/").strip("/")
        target = (self.root_dir / clean).resolve()
        target.mkdir(parents=True, exist_ok=True)
        return FolderInfo(
            folder_id=clean,
            name=clean.split("/")[-1] if clean else "",
            path=clean,
        )

    async def init_upload(
        self,
        filename: str,
        size_bytes: int,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> UploadSessionInfo:
        session_id = uuid.uuid4().hex
        prefix = (parent_folder_id or "memories").strip("/")
        return UploadSessionInfo(
            session_id=session_id,
            upload_mode="server-proxy",
            part_size=0,
            next_method="POST",
            complete_url="",
            metadata={"folder": prefix, "filename": filename},
        )

    async def sign_part(self, session_id: str, part_number: int) -> str:
        return ""

    async def complete_upload(
        self,
        session_id: str,
        parts: list[dict[str, Any]] | None = None,
        upload_key: str | None = None,
    ) -> FileEntryInfo:
        key = upload_key or session_id
        return FileEntryInfo(
            file_id=key,
            name=key.split("/")[-1],
            size_bytes=0,
            mime="application/octet-stream",
            stored_path=key,
        )

    async def cancel_upload(self, session_id: str) -> bool:
        return True

    def resolve_local_path(self, file_id: str) -> Path | None:
        """Resolve a local path across storage_root, memories_dir, archive_dir, and legacy uploads."""
        raw = file_id.strip().replace("\\", "/").lstrip("/")
        if not raw or ".." in raw.split("/"):
            return None

        # 1. Try memories_dir (standard guest memory uploads)
        p_mem = (settings.memories_dir / raw).resolve()
        if p_mem.is_file():
            return p_mem

        # 2. Try storage_root
        p_root = (self.root_dir / raw).resolve()
        if p_root.is_file():
            return p_root

        # 3. Try archive_dir (admin official media)
        p_arc = (settings.archive_dir / raw).resolve()
        if p_arc.is_file():
            return p_arc

        # 4. Try legacy_uploads
        p_leg = (settings.legacy_uploads / raw).resolve()
        if p_leg.is_file():
            return p_leg

        return None

    async def get_file_metadata(self, file_id: str) -> FileEntryInfo:
        p = self.resolve_local_path(file_id)
        if not p or not p.is_file():
            raise StorageError(f"Local file '{file_id}' not found")
        stat = p.stat()
        return FileEntryInfo(
            file_id=file_id,
            name=p.name,
            size_bytes=stat.st_size,
            mime="application/octet-stream",
            stored_path=str(p),
        )

    async def generate_download_link(self, file_id: str, expires_sec: int = 3600) -> str:
        return f"/api/memories/file/{file_id}"

    async def delete_file(self, file_id: str) -> bool:
        p = self.resolve_local_path(file_id)
        if p and p.is_file():
            try:
                p.unlink()
                return True
            except OSError:
                return False
        return True

    async def upload_direct_bytes(
        self,
        data: bytes,
        filename: str,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FileEntryInfo:
        prefix = (parent_folder_id or "memories").strip("/")
        target_dir = (self.root_dir / prefix).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix.lower() or ".bin"
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest = target_dir / stored_name
        dest.write_bytes(data)

        rel = f"{prefix}/{stored_name}"
        return FileEntryInfo(
            file_id=rel,
            name=filename,
            size_bytes=len(data),
            mime=mime,
            stored_path=rel,
        )
