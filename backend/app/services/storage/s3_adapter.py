"""S3-Compatible Storage Provider Adapter with built-in AWS Signature Version 4."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from app.config import settings
from app.services.storage.base_adapter import (
    FileEntryInfo,
    FolderInfo,
    ProviderCapabilities,
    StorageAuthError,
    StorageError,
    StorageProviderAdapter,
    StorageQuotaError,
    StorageUnavailableError,
    StorageUsage,
    UploadSessionInfo,
)

log = logging.getLogger("wwh.storage.s3")


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


class S3CompatibleAdapter(StorageProviderAdapter):
    """Adapter for AWS S3 and S3-compatible object storage services."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.endpoint = (
            config.get("endpoint")
            or settings.s3_endpoint
            or ""
        ).rstrip("/")
        self.bucket = config.get("bucket") or settings.s3_bucket or ""
        self.access_key = config.get("access_key") or settings.s3_access_key or ""
        self.secret_key = config.get("secret_key") or settings.s3_secret_key or ""
        self.region = config.get("region") or settings.s3_region or "us-east-1"
        self.force_path_style = bool(config.get("force_path_style", settings.s3_force_path_style))
        self.max_file_size = int(config.get("max_file_size_bytes") or 5 * 1024 * 1024 * 1024)  # 5 GB default
        self.total_capacity_bytes = int(config.get("total_capacity_bytes") or 100 * 1024 * 1024 * 1024)  # 100 GB default

    @property
    def provider_type(self) -> str:
        return "s3"

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.bucket and self.access_key and self.secret_key)

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_type="s3",
            supports_direct_upload=True,
            supports_multipart_upload=True,
            supports_resumable_upload=False,
            supports_folders=True,
            supports_temporary_download_links=True,
            supports_space_usage_query=False,
            supports_file_count_limit=False,
            max_file_size_bytes=self.max_file_size,
            default_part_size_bytes=10 * 1024 * 1024,  # 10 MB S3 part size
        )

    def _get_object_url(self, key: str) -> str:
        clean_key = key.lstrip("/")
        if self.force_path_style or not self.bucket:
            return f"{self.endpoint}/{self.bucket}/{quote(clean_key, safe='/')}".rstrip("/")
        # Virtual hosted-style
        parsed = urlparse(self.endpoint)
        netloc = f"{self.bucket}.{parsed.netloc}"
        return f"{parsed.scheme}://{netloc}/{quote(clean_key, safe='/')}".rstrip("/")

    def generate_presigned_url(
        self,
        method: str,
        key: str,
        expires_sec: int = 3600,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Generate an AWS SigV4 presigned URL for direct browser uploads/downloads."""
        if not self.is_configured:
            raise StorageAuthError("S3 credentials not fully configured")

        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        credential_scope = f"{datestamp}/{self.region}/s3/aws4_request"

        raw_url = self._get_object_url(key)
        parsed = urlparse(raw_url)
        canonical_uri = parsed.path or "/"

        qp = dict(query_params or {})
        qp["X-Amz-Algorithm"] = "AWS4-HMAC-SHA256"
        qp["X-Amz-Credential"] = f"{self.access_key}/{credential_scope}"
        qp["X-Amz-Date"] = amz_date
        qp["X-Amz-Expires"] = str(expires_sec)
        qp["X-Amz-SignedHeaders"] = "host"

        sorted_qp = sorted(qp.items())
        canonical_querystring = urlencode(sorted_qp)

        canonical_headers = f"host:{parsed.netloc}\n"
        signed_headers = "host"
        payload_hash = "UNSIGNED-PAYLOAD"

        canonical_request = (
            f"{method.upper()}\n"
            f"{canonical_uri}\n"
            f"{canonical_querystring}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        string_to_sign = (
            f"AWS4-HMAC-SHA256\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        signing_key = _get_signature_key(self.secret_key, datestamp, self.region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        return f"{parsed.scheme}://{parsed.netloc}{canonical_uri}?{canonical_querystring}&X-Amz-Signature={signature}"

    async def _authenticated_request(
        self,
        method: str,
        key: str = "",
        query_params: dict[str, str] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        credential_scope = f"{datestamp}/{self.region}/s3/aws4_request"

        raw_url = self._get_object_url(key)
        parsed = urlparse(raw_url)
        canonical_uri = parsed.path or "/"

        qp = dict(query_params or {})
        sorted_qp = sorted(qp.items())
        canonical_querystring = urlencode(sorted_qp)

        payload_bytes = content or b""
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        req_headers = dict(headers or {})
        req_headers["host"] = parsed.netloc
        req_headers["x-amz-date"] = amz_date
        req_headers["x-amz-content-sha256"] = payload_hash

        sorted_headers = sorted((k.lower(), v.strip()) for k, v in req_headers.items())
        canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted_headers)
        signed_headers = ";".join(k for k, _ in sorted_headers)

        canonical_request = (
            f"{method.upper()}\n"
            f"{canonical_uri}\n"
            f"{canonical_querystring}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        string_to_sign = (
            f"AWS4-HMAC-SHA256\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        signing_key = _get_signature_key(self.secret_key, datestamp, self.region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth_header = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        req_headers["Authorization"] = auth_header

        full_url = f"{parsed.scheme}://{parsed.netloc}{canonical_uri}"
        if canonical_querystring:
            full_url = f"{full_url}?{canonical_querystring}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.request(
                    method,
                    full_url,
                    headers=req_headers,
                    content=content,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise StorageUnavailableError(f"S3 connection failed: {e}") from e
        except Exception as e:
            raise StorageError(f"S3 request error: {e}") from e

        if res.status_code in (401, 403):
            raise StorageAuthError(f"S3 authentication failed: HTTP {res.status_code}")
        return res

    async def validate_credentials(self) -> bool:
        if not self.is_configured:
            return False
        try:
            res = await self._authenticated_request("HEAD", timeout=10.0)
            return res.status_code in (200, 204, 301, 307)
        except Exception as e:
            log.warning("S3 validate_credentials failed: %s", e)
            return False

    async def check_connectivity(self) -> tuple[bool, str]:
        if not self.is_configured:
            return False, "تنظیمات S3 هنوز تکمیل نشده است."
        try:
            res = await self._authenticated_request("HEAD", timeout=10.0)
            if res.status_code in (200, 204, 301, 307):
                return True, "اتصال به مخزن S3 با موفقیت برقرار شد."
            return False, f"پاسخ ناموفق از S3: HTTP {res.status_code}"
        except StorageAuthError as e:
            return False, f"احراز هویت S3 ناموفق بود: {e.message}"
        except Exception as e:
            return False, f"خطای اتصال به S3: {str(e)}"

    async def get_storage_usage(self) -> StorageUsage:
        # S3 does not expose instant space usage in standard REST without CloudWatch/billing
        return StorageUsage(
            total_bytes=self.total_capacity_bytes,
            used_bytes=0,
            available_bytes=self.total_capacity_bytes,
            file_count=0,
            refreshed_at=datetime.now(timezone.utc),
        )

    async def create_or_get_folder(
        self,
        folder_path: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FolderInfo:
        clean_path = folder_path.strip().replace("\\", "/").strip("/")
        # S3 folders are virtual key prefixes
        return FolderInfo(
            folder_id=clean_path,
            name=clean_path.split("/")[-1] if clean_path else "",
            path=clean_path,
        )

    async def init_upload(
        self,
        filename: str,
        size_bytes: int,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> UploadSessionInfo:
        import uuid

        session_id = uuid.uuid4().hex
        prefix = (parent_folder_id or "").strip("/")
        key = f"{prefix}/{session_id}-{filename}".strip("/")

        # Below 100MB: s3-single, 100MB or above: s3-multipart
        if size_bytes < 100 * 1024 * 1024:
            direct_url = self.generate_presigned_url(
                "PUT",
                key,
                expires_sec=3600,
            )
            return UploadSessionInfo(
                session_id=session_id,
                upload_mode="s3-single",
                part_size=0,
                next_method="PUT",
                next_url=direct_url,
                next_headers={"Content-Type": mime},
                complete_url="",
                metadata={"key": key},
            )
        else:
            # S3 Multipart
            res = await self._authenticated_request(
                "POST",
                key,
                query_params={"uploads": ""},
                headers={"Content-Type": mime},
                timeout=15.0,
            )
            if res.status_code not in (200, 201):
                raise StorageError(f"Could not initiate S3 multipart upload: HTTP {res.status_code}")
            import re
            m = re.search(r"<UploadId>(.*?)</UploadId>", res.text)
            upload_id = m.group(1) if m else ""
            if not upload_id:
                raise StorageError("Could not extract S3 UploadId from response")

            part_size = 10 * 1024 * 1024  # 10 MB chunks
            return UploadSessionInfo(
                session_id=session_id,
                upload_mode="s3-multipart",
                part_size=part_size,
                next_method="PUT",
                metadata={"key": key, "uploadId": upload_id},
            )

    async def sign_part(
        self,
        session_id: str,
        part_number: int,
    ) -> str:
        # For S3, key and uploadId are needed from session metadata; will be resolved via UploadReservation
        # Fallback helper:
        return ""

    def sign_part_with_metadata(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expires_sec: int = 3600,
    ) -> str:
        return self.generate_presigned_url(
            "PUT",
            key,
            expires_sec=expires_sec,
            query_params={"partNumber": str(part_number), "uploadId": upload_id},
        )

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
            hash_or_etag="",
        )

    async def cancel_upload(self, session_id: str) -> bool:
        return True

    async def get_file_metadata(self, file_id: str) -> FileEntryInfo:
        res = await self._authenticated_request("HEAD", file_id, timeout=10.0)
        if res.status_code not in (200, 204):
            raise StorageError(f"S3 object '{file_id}' not found: HTTP {res.status_code}")
        size = int(res.headers.get("content-length") or 0)
        mime = res.headers.get("content-type") or "application/octet-stream"
        etag = res.headers.get("etag") or ""
        return FileEntryInfo(
            file_id=file_id,
            name=file_id.split("/")[-1],
            size_bytes=size,
            mime=mime,
            stored_path=file_id,
            hash_or_etag=etag,
        )

    async def generate_download_link(self, file_id: str, expires_sec: int = 3600) -> str:
        return self.generate_presigned_url("GET", file_id, expires_sec=expires_sec)

    async def delete_file(self, file_id: str) -> bool:
        res = await self._authenticated_request("DELETE", file_id, timeout=15.0)
        return res.status_code in (200, 204)

    async def upload_direct_bytes(
        self,
        data: bytes,
        filename: str,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FileEntryInfo:
        import uuid
        prefix = (parent_folder_id or "").strip("/")
        key = f"{prefix}/{uuid.uuid4().hex}-{filename}".strip("/")
        res = await self._authenticated_request(
            "PUT",
            key,
            content=data,
            headers={"Content-Type": mime},
            timeout=60.0,
        )
        if res.status_code not in (200, 201):
            raise StorageError(f"S3 PUT failed: HTTP {res.status_code}")
        etag = res.headers.get("etag") or ""
        return FileEntryInfo(
            file_id=key,
            name=filename,
            size_bytes=len(data),
            mime=mime,
            stored_path=key,
            hash_or_etag=etag,
        )
