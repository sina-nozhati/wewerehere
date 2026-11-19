"""StorageProviderAdapter: Base interface and domain models for storage adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class StorageError(Exception):
    """Base exception for storage provider errors."""

    def __init__(self, message: str, code: str = "storage_error", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class StorageAuthError(StorageError):
    """Provider authentication or credential error."""

    def __init__(self, message: str = "Provider authentication failed", details: dict[str, Any] | None = None):
        super().__init__(message, code="auth_failed", details=details)


class StorageQuotaError(StorageError):
    """Storage quota or capacity limit exceeded."""

    def __init__(self, message: str = "Storage quota exceeded", details: dict[str, Any] | None = None):
        super().__init__(message, code="quota_exceeded", details=details)


class StorageUnavailableError(StorageError):
    """Storage service is unreachable or returned server error."""

    def __init__(self, message: str = "Storage provider is unavailable", details: dict[str, Any] | None = None):
        super().__init__(message, code="provider_unavailable", details=details)


@dataclass
class StorageUsage:
    """Current capacity and consumption metrics for a provider."""

    total_bytes: int = 0
    used_bytes: int = 0
    available_bytes: int = 0
    file_count: int = 0
    max_files: int | None = None
    refreshed_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def percent_used(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.used_bytes / self.total_bytes) * 100.0)

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.available_bytes)

    @property
    def has_storage_room(self) -> bool:
        return self.available_bytes > 0 or self.total_bytes == 0

    @property
    def has_file_count_room(self) -> bool:
        if self.max_files is None or self.max_files <= 0:
            return True
        return self.file_count < self.max_files


@dataclass
class ProviderCapabilities:
    """Explicit capabilities supported by a specific provider adapter."""

    provider_type: str  # files_ir | s3 | local
    supports_direct_upload: bool = True
    supports_multipart_upload: bool = True
    supports_resumable_upload: bool = False
    supports_folders: bool = True
    supports_temporary_download_links: bool = True
    supports_space_usage_query: bool = True
    supports_file_count_limit: bool = True
    max_file_size_bytes: int = 500 * 1024 * 1024  # 500 MB default
    default_part_size_bytes: int = 10 * 1024 * 1024  # 10 MB


@dataclass
class FolderInfo:
    """Folder representation in cloud/local storage."""

    folder_id: str
    name: str
    path: str
    parent_id: str | None = None
    workspace_id: str | None = None


@dataclass
class UploadSessionInfo:
    """Direct-to-cloud upload session instructions returned to client."""

    session_id: str
    upload_mode: str  # s3-single | s3-multipart | single | tus | local
    part_size: int = 0
    next_method: str = "PUT"
    next_url: str = ""
    next_headers: dict[str, str] = field(default_factory=dict)
    complete_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileEntryInfo:
    """Metadata of an uploaded or stored file."""

    file_id: str  # Provider internal identifier
    name: str
    size_bytes: int
    mime: str
    stored_path: str = ""
    hash_or_etag: str = ""
    thumbnail_url: str = ""
    created_at: str = ""


class StorageProviderAdapter(ABC):
    """Abstract base class for all storage provider adapters."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Return provider type identifier ('files_ir', 's3', 'local')."""
        ...

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Return explicit capabilities supported by this adapter."""
        ...

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Check if provider credentials are valid and active."""
        ...

    @abstractmethod
    async def check_connectivity(self) -> tuple[bool, str]:
        """Test API reachability; returns (is_healthy, error_or_ok_message)."""
        ...

    @abstractmethod
    async def get_storage_usage(self) -> StorageUsage:
        """Retrieve real-time or configured storage usage and limits."""
        ...

    @abstractmethod
    async def create_or_get_folder(
        self,
        folder_path: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FolderInfo:
        """Ensure a folder hierarchy exists; return FolderInfo of the deepest folder."""
        ...

    @abstractmethod
    async def init_upload(
        self,
        filename: str,
        size_bytes: int,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> UploadSessionInfo:
        """Initialize upload session and return client upload instructions."""
        ...

    @abstractmethod
    async def sign_part(
        self,
        session_id: str,
        part_number: int,
    ) -> str:
        """Sign a specific part URL for multipart uploads."""
        ...

    @abstractmethod
    async def complete_upload(
        self,
        session_id: str,
        parts: list[dict[str, Any]] | None = None,
        upload_key: str | None = None,
    ) -> FileEntryInfo:
        """Finalize upload session and verify object creation on provider."""
        ...

    @abstractmethod
    async def cancel_upload(self, session_id: str) -> bool:
        """Cancel an in-progress upload session."""
        ...

    @abstractmethod
    async def get_file_metadata(self, file_id: str) -> FileEntryInfo:
        """Retrieve metadata of a stored file entry."""
        ...

    @abstractmethod
    async def generate_download_link(self, file_id: str, expires_sec: int = 3600) -> str:
        """Generate a secure, short-lived download link or access URL."""
        ...

    @abstractmethod
    async def delete_file(self, file_id: str) -> bool:
        """Permanently delete a file entry from the provider."""
        ...

    @abstractmethod
    async def upload_direct_bytes(
        self,
        data: bytes,
        filename: str,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FileEntryInfo:
        """Direct server-side upload fallback when browser cannot reach provider directly."""
        ...
