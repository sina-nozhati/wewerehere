"""Files.ir Storage Provider Adapter using the official Files.ir REST API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

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

log = logging.getLogger("wwh.storage.files_ir")


class FilesIrAdapter(StorageProviderAdapter):
    """Adapter for official Files.ir API (https://my.files.ir/api/v1)."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.endpoint = (
            config.get("api_endpoint")
            or settings.files_ir_api_endpoint
            or "https://my.files.ir/api/v1"
        ).rstrip("/")
        self.api_key = config.get("api_key") or settings.files_ir_api_key or ""
        self.workspace_id = config.get("workspace_id", settings.files_ir_workspace_id or 0)
        self.max_file_size = int(
            config.get("max_file_size_bytes")
            or settings.files_ir_max_file_size_bytes
            or 500 * 1024 * 1024
        )
        self.file_count_limit = int(
            config.get("file_count_limit")
            or settings.files_ir_file_count_limit
            or 3000
        )
        self.total_capacity_bytes = int(
            config.get("total_capacity_bytes")
            or settings.files_ir_total_capacity_bytes
            or 10 * 1024 * 1024 * 1024
        )
        self._folder_cache: dict[tuple[str, str], str] = {}

    @property
    def provider_type(self) -> str:
        return "files_ir"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_type="files_ir",
            supports_direct_upload=True,
            supports_multipart_upload=True,
            supports_resumable_upload=True,
            supports_folders=True,
            supports_temporary_download_links=True,
            supports_space_usage_query=True,
            supports_file_count_limit=True,
            max_file_size_bytes=self.max_file_size,
            default_part_size_bytes=20 * 1024 * 1024,  # Files.ir default partSize is 20MB
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        url = f"{self.endpoint}{path}"
        headers = self._headers()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_data,
                    params=params,
                    files=files,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise StorageUnavailableError(f"Files.ir connection failed: {e}") from e
        except Exception as e:
            raise StorageError(f"Files.ir request error: {e}") from e

        if res.status_code == 401:
            raise StorageAuthError("Invalid Files.ir API token or unauthenticated")
        if res.status_code == 403:
            raise StorageAuthError("Files.ir permission denied for this operation")
        if res.status_code == 422:
            try:
                body = res.json()
            except Exception:
                body = {}
            msg = body.get("message") or "Validation error or insufficient storage space"
            if "storage" in msg.lower() or "space" in msg.lower():
                raise StorageQuotaError(f"Files.ir storage quota reached: {msg}")
            raise StorageError(f"Files.ir validation error: {msg}", details=body)
        if res.status_code >= 500:
            raise StorageUnavailableError(f"Files.ir server error ({res.status_code})")

        if res.status_code not in (200, 201, 204):
            raise StorageError(f"Files.ir error HTTP {res.status_code}: {res.text[:200]}")

        if res.status_code == 204 or not res.content:
            return {}
        try:
            return res.json()
        except Exception as e:
            raise StorageError(f"Files.ir response was not valid JSON: {e}") from e

    async def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            data = await self._request("GET", "/access-token/scopes", timeout=10.0)
            return bool(data.get("status") == "success" or "scopes" in data)
        except StorageAuthError:
            return False
        except Exception as e:
            log.warning("Files.ir validate_credentials check failed: %s", e)
            return False

    async def check_connectivity(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "کلید API مربوط به Files.ir تنظیم نشده است."
        try:
            data = await self._request("GET", "/access-token/scopes", timeout=10.0)
            if data.get("status") == "success" or "scopes" in data:
                return True, "ارتباط با Files.ir برقرار است."
            return True, "پاسخ از Files.ir دریافت شد."
        except StorageAuthError as e:
            return False, f"احراز هویت Files.ir ناموفق بود: {e.message}"
        except StorageUnavailableError as e:
            return False, f"سرویس Files.ir در دسترس نیست: {e.message}"
        except Exception as e:
            return False, f"خطای اتصال به Files.ir: {str(e)}"

    async def get_storage_usage(self) -> StorageUsage:
        try:
            data = await self._request("GET", "/user/space-usage", timeout=10.0)
            used = int(data.get("used") or 0)
            available = int(data.get("available") or 0)
            remaining = int(data.get("remaining") or (available - used if available > used else 0))
            total = available if available > 0 else (used + remaining if used + remaining > 0 else self.total_capacity_bytes)
            return StorageUsage(
                total_bytes=total,
                used_bytes=used,
                available_bytes=remaining,
                file_count=0,
                max_files=self.file_count_limit,
                refreshed_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            log.warning("Files.ir get_storage_usage fallback to configured limits: %s", e)
            return StorageUsage(
                total_bytes=self.total_capacity_bytes,
                used_bytes=0,
                available_bytes=self.total_capacity_bytes,
                file_count=0,
                max_files=self.file_count_limit,
                refreshed_at=datetime.now(timezone.utc),
            )

    @staticmethod
    def _norm_pid(pid: Any) -> str:
        """Normalize parent folder ID treating 0, '0', None, '' equivalently as root."""
        if pid is None or pid == 0:
            return ""
        s = str(pid).strip()
        return "" if s in ("", "0", "None") else s

    async def _find_folder(
        self,
        name: str,
        parent_id: str | None,
        workspace_id: int | None,
    ) -> str | None:
        clean_name = name.strip()
        norm_pid = self._norm_pid(parent_id)
        cache_key = (clean_name.lower(), norm_pid)
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        params: dict[str, Any] = {
            "type": "folder",
            "query": clean_name,
            "workspaceId": workspace_id or 0,
        }
        if norm_pid:
            params["parentId"] = norm_pid
            params["parentIds[]"] = norm_pid

        try:
            data = await self._request("GET", "/drive/file-entries", params=params, timeout=15.0)
            raw_data = data.get("data") if isinstance(data, dict) and "data" in data else data
            if isinstance(raw_data, dict) and "data" in raw_data:
                entries = raw_data.get("data")
            elif isinstance(raw_data, list):
                entries = raw_data
            elif isinstance(data, list):
                entries = data
            else:
                entries = []

            if isinstance(entries, list):
                name_lower = clean_name.lower()
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    item_name = str(item.get("name") or "").strip().lower()
                    item_type = str(item.get("type") or "").strip().lower()
                    if item_name == name_lower and (item_type == "folder" or item.get("is_dir")):
                        item_pid = self._norm_pid(item.get("parent_id"))
                        if item_pid == norm_pid:
                            fid = str(item.get("id"))
                            self._folder_cache[cache_key] = fid
                            return fid
        except Exception as e:
            log.debug("Files.ir _find_folder search error: %s", e)
        return None

    async def create_or_get_folder(
        self,
        folder_path: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FolderInfo:
        parts = [p.strip() for p in folder_path.replace("\\", "/").split("/") if p.strip()]
        if not parts:
            return FolderInfo(folder_id=parent_folder_id or "0", name="root", path="")

        norm_parent = self._norm_pid(parent_folder_id)

        # Defensive guard: strip any root prefixes if parent_folder_id is already supplied
        if norm_parent:
            lower_parts = [p.lower() for p in parts]
            if parts and lower_parts[0] in ("we were here", "wewerehere"):
                for marker in ("memories", "official-media", "exports", "photos", "videos", "other"):
                    if marker in lower_parts:
                        idx = lower_parts.index(marker)
                        parts = parts[idx:]
                        lower_parts = [p.lower() for p in parts]
                        break

            # Check if parent folder name matches any part or prefix
            parent_name = None
            try:
                parent_meta = await self._request("GET", f"/file-entries/{norm_parent}", timeout=10.0)
                parent_entry = parent_meta.get("file_entry") or parent_meta.get("entry") or parent_meta
                if isinstance(parent_entry, dict):
                    parent_name = str(parent_entry.get("name") or "").strip()
            except Exception:
                pass

            if parent_name:
                p_lower = parent_name.lower()
                if p_lower in lower_parts:
                    idx = lower_parts.index(p_lower)
                    parts = parts[idx + 1:]
                elif parts and parts[0].strip().lower() == p_lower:
                    parts = parts[1:]

            if not parts:
                return FolderInfo(
                    folder_id=str(norm_parent),
                    name=parent_name or "folder",
                    path=folder_path,
                    parent_id=None,
                    workspace_id=str(workspace_id or self.workspace_id or "0"),
                )

        wid = int(workspace_id) if workspace_id and str(workspace_id).isdigit() else int(self.workspace_id or 0)
        curr_parent = norm_parent
        current_path_parts: list[str] = []

        def _extract_id(obj: Any) -> str | None:
            if isinstance(obj, dict):
                for k in ("id", "folder_id", "file_id", "folderId", "fileEntryId"):
                    v = obj.get(k)
                    if v is not None and str(v).strip() not in ("", "None"):
                        return str(v).strip()
            elif obj is not None and str(obj).strip() not in ("", "None"):
                return str(obj).strip()
            return None

        for part in parts:
            current_path_parts.append(part)
            existing_id = await self._find_folder(part, curr_parent, wid)
            if existing_id:
                curr_parent = existing_id
                continue

            # Create folder
            body: dict[str, Any] = {
                "name": part,
                "parentId": int(curr_parent) if curr_parent and curr_parent != "0" else None,
                "targetWorkspaceId": wid if wid > 0 else None,
            }
            parent_before = curr_parent
            try:
                res = await self._request("POST", "/folders", json_data=body, timeout=15.0)
                folder_obj = (
                    res.get("folder")
                    or res.get("fileEntry")
                    or res.get("entry")
                    or res.get("data")
                    or res
                )
                new_id = _extract_id(folder_obj) or _extract_id(res)
                if not new_id or new_id == "None":
                    new_id = await self._find_folder(part, parent_before, wid)
                if not new_id or new_id == "None":
                    raise StorageError(f"Files.ir POST /folders returned no valid folder ID: {res}")
                curr_parent = str(new_id)
                self._folder_cache[(part.strip().lower(), self._norm_pid(parent_before))] = curr_parent
            except Exception as e:
                # If duplicate creation error or conflict, retry finding
                found = await self._find_folder(part, parent_before, wid)
                if found and found != "None":
                    curr_parent = found
                    self._folder_cache[(part.strip().lower(), self._norm_pid(parent_before))] = curr_parent
                else:
                    raise StorageError(f"Could not create folder '{part}' on Files.ir: {e}") from e

        full_path = "/".join(current_path_parts)
        return FolderInfo(
            folder_id=str(curr_parent),
            name=parts[-1],
            path=full_path,
            parent_id=parent_folder_id,
            workspace_id=str(wid),
        )

    async def init_upload(
        self,
        filename: str,
        size_bytes: int,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> UploadSessionInfo:
        if size_bytes > self.max_file_size:
            raise StorageQuotaError(
                f"File size {size_bytes} exceeds Files.ir maximum allowed {self.max_file_size} bytes"
            )

        wid = int(workspace_id) if workspace_id and str(workspace_id).isdigit() else (int(self.workspace_id) if self.workspace_id else None)
        pid = int(parent_folder_id) if parent_folder_id and str(parent_folder_id).isdigit() else None

        body: dict[str, Any] = {
            "filename": filename,
            "size": size_bytes,
            "parentId": pid,
            "workspaceId": wid,
        }
        res = await self._request("POST", "/uploads-new/init", json_data=body, timeout=20.0)

        session_id = res.get("uploadSessionId") or ""
        mode = res.get("uploadMode") or "single"
        part_size = int(res.get("partSize") or 20 * 1024 * 1024)
        next_obj = res.get("next") or {}

        return UploadSessionInfo(
            session_id=session_id,
            upload_mode=mode,
            part_size=part_size,
            next_method=next_obj.get("method", "PUT"),
            next_url=next_obj.get("url", ""),
            next_headers=next_obj.get("headers", {}),
            complete_url=next_obj.get("completeUrl", f"{self.endpoint}/uploads-new/{session_id}/complete"),
            metadata=next_obj.get("metadata", {}),
        )

    async def sign_part(
        self,
        session_id: str,
        part_number: int,
    ) -> str:
        body = {"partNumbers": [int(part_number)]}
        res = await self._request(
            "POST",
            f"/uploads-new/{session_id}/parts/sign",
            json_data=body,
            timeout=15.0,
        )
        urls = res.get("urls") or []
        for entry in urls:
            if entry.get("partNumber") == part_number:
                return entry.get("url") or ""
        if urls:
            return urls[0].get("url") or ""
        raise StorageError(f"No signed part URL returned for part {part_number}")

    async def complete_upload(
        self,
        session_id: str,
        parts: list[dict[str, Any]] | None = None,
        upload_key: str | None = None,
    ) -> FileEntryInfo:
        body: dict[str, Any] = {}
        if parts:
            body["parts"] = parts
        if upload_key:
            body["uploadKey"] = upload_key

        res = await self._request(
            "POST",
            f"/uploads-new/{session_id}/complete",
            json_data=body,
            timeout=30.0,
        )
        file_entry = res.get("fileEntry") or {}
        return FileEntryInfo(
            file_id=str(file_entry.get("id") or ""),
            name=str(file_entry.get("name") or ""),
            size_bytes=int(file_entry.get("file_size") or 0),
            mime=str(file_entry.get("mime") or "application/octet-stream"),
            stored_path=str(file_entry.get("path") or ""),
            hash_or_etag=str(file_entry.get("hash") or ""),
            thumbnail_url=str(file_entry.get("thumbnail") or ""),
            created_at=str(file_entry.get("created_at") or ""),
        )

    async def cancel_upload(self, session_id: str) -> bool:
        try:
            await self._request("DELETE", f"/uploads-new/{session_id}", timeout=10.0)
            return True
        except Exception as e:
            log.warning("Files.ir cancel_upload failed for session %s: %s", session_id, e)
            return False

    async def get_file_metadata(self, file_id: str) -> FileEntryInfo:
        params: dict[str, Any] = {}
        if self.workspace_id:
            params["workspaceId"] = self.workspace_id
        data = await self._request("GET", f"/file-entries/{file_id}", params=params, timeout=15.0)
        entry = data.get("fileEntry") or data
        return FileEntryInfo(
            file_id=str(entry.get("id") or file_id),
            name=str(entry.get("name") or ""),
            size_bytes=int(entry.get("file_size") or 0),
            mime=str(entry.get("mime") or "application/octet-stream"),
            stored_path=str(entry.get("path") or ""),
            hash_or_etag=str(entry.get("hash") or ""),
            thumbnail_url=str(entry.get("thumbnail") or ""),
            created_at=str(entry.get("created_at") or ""),
        )

    async def generate_download_link(self, file_id: str, expires_sec: int = 3600) -> str:
        """Create or reuse shareable link with expiration for authorized download."""
        exp = datetime.now(timezone.utc) + timedelta(seconds=expires_sec)
        body = {
            "allowDownload": True,
            "allowEdit": False,
            "expiresAt": exp.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            "passwordEnabled": False,
        }
        try:
            res = await self._request("POST", f"/file-entries/{file_id}/shareable-link", json_data=body, timeout=15.0)
            link = res.get("link") or {}
            share_hash = link.get("hash") or ""
            if share_hash:
                return f"{self.endpoint}/file-entries/{file_id}?shareable_link={share_hash}"
        except Exception as e:
            log.warning("Files.ir generate_download_link shareable-link error: %s", e)

        # Fallback to direct authenticated endpoint URL
        return f"{self.endpoint}/file-entries/{file_id}"

    async def delete_file(self, file_id: str) -> bool:
        body = {
            "entryIds": [int(file_id) if file_id.isdigit() else file_id],
            "deleteForever": True,
        }
        res = await self._request("POST", "/file-entries/delete", json_data=body, timeout=15.0)
        return bool(res.get("status") == "success")

    async def upload_direct_bytes(
        self,
        data: bytes,
        filename: str,
        mime: str,
        parent_folder_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FileEntryInfo:
        """Server-side upload to Files.ir when proxying is needed."""
        session = await self.init_upload(filename, len(data), mime, parent_folder_id, workspace_id)
        session_id = session.session_id

        try:
            if session.upload_mode == "s3-single":
                # Single PUT to S3 URL
                async with httpx.AsyncClient(timeout=60.0) as client:
                    put_res = await client.put(session.next_url, content=data, headers=session.next_headers)
                    if put_res.status_code not in (200, 201):
                        raise StorageError(f"Files.ir S3 direct PUT failed: HTTP {put_res.status_code}")
                return await self.complete_upload(session_id)

            elif session.upload_mode == "s3-multipart":
                # Split and upload chunks directly to S3
                part_size = session.part_size or (20 * 1024 * 1024)
                chunks = [data[i : i + part_size] for i in range(0, len(data), part_size)]
                parts_result: list[dict[str, Any]] = []

                async with httpx.AsyncClient(timeout=120.0) as client:
                    for idx, chunk in enumerate(chunks, start=1):
                        signed_url = await self.sign_part(session_id, idx)
                        put_res = await client.put(signed_url, content=chunk)
                        if put_res.status_code not in (200, 201):
                            raise StorageError(f"Files.ir S3 part {idx} PUT failed: HTTP {put_res.status_code}")
                        etag = put_res.headers.get("ETag") or f'"{idx}"'
                        parts_result.append({"PartNumber": idx, "ETag": etag})

                return await self.complete_upload(session_id, parts=parts_result)

            elif session.upload_mode == "single":
                # Upload file directly to /uploads-new/{sessionId}/file
                files = {"file": (filename, data, mime)}
                res = await self._request(
                    "POST",
                    f"/uploads-new/{session_id}/file",
                    files=files,
                    timeout=60.0,
                )
                file_entry = res.get("fileEntry") or {}
                return FileEntryInfo(
                    file_id=str(file_entry.get("id") or ""),
                    name=str(file_entry.get("name") or filename),
                    size_bytes=int(file_entry.get("file_size") or len(data)),
                    mime=str(file_entry.get("mime") or mime),
                    stored_path=str(file_entry.get("path") or ""),
                    hash_or_etag=str(file_entry.get("hash") or ""),
                )
            else:
                raise StorageError(f"Unsupported Files.ir upload mode for server proxy: {session.upload_mode}")

        except Exception:
            await self.cancel_upload(session_id)
            raise
