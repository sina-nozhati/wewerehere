"""UploadManager: Orchestrates direct-to-cloud uploads, part signing, completion, and server fallbacks."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import Event, MediaAsset, MemoryItem, StorageProvider, UploadReservation, utcnow
from app.services.storage.base_adapter import (
    FileEntryInfo,
    StorageError,
    StorageQuotaError,
    StorageUnavailableError,
    UploadSessionInfo,
)
from app.services.storage.folder_manager import FolderManager
from app.services.storage.media_registry import MediaRegistry
from app.services.storage.provider_manager import ProviderManager
from app.services.storage.routing_manager import StorageRoutingManager

log = logging.getLogger("wwh.storage.upload_manager")


class UploadManager:
    """High-level upload lifecycle coordinator."""

    @classmethod
    async def init_direct_upload(
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
    ) -> dict[str, Any]:
        """Start a direct-to-cloud upload session."""
        # 1. Routing & concurrency reservation
        routing = await StorageRoutingManager.select_provider_and_reserve(
            db,
            event_id=event_id,
            filename=filename,
            file_size=file_size,
            mime=mime,
            media_kind=media_kind,
            category=category,
            ticket_id=ticket_id,
        )
        provider = routing.provider
        reservation = routing.reservation
        adapter = ProviderManager.get_adapter_for_provider(provider)

        # 2. Target folder resolution
        folder = await FolderManager.get_folder_for_upload(
            db,
            event_id=event_id,
            provider_id=provider.id,
            category=category,
        )
        parent_folder_id = folder.provider_folder_id if folder else None

        # 3. Generate non-guessable stored filename
        stored_name = FolderManager.generate_safe_stored_filename(filename, media_kind=media_kind)

        # 4. Initialize upload on provider
        try:
            session_info = await adapter.init_upload(
                filename=stored_name,
                size_bytes=file_size,
                mime=mime,
                parent_folder_id=parent_folder_id,
            )
        except Exception as e:
            # Release reservation on failure
            StorageRoutingManager.release_reservation(db, reservation.id, new_status="failed")
            raise

        # 5. Update reservation record with provider session details
        reservation.provider_session_id = session_info.session_id
        reservation.upload_mode = session_info.upload_mode
        reservation.part_size = session_info.part_size
        reservation.upload_data_json = json.dumps(
            {
                "stored_name": stored_name,
                "folder_path": folder.provider_folder_path if folder else "",
                "next": {
                    "method": session_info.next_method,
                    "url": session_info.next_url,
                    "headers": session_info.next_headers,
                    "completeUrl": session_info.complete_url,
                    "metadata": session_info.metadata,
                },
            }
        )
        db.commit()

        return {
            "sessionId": reservation.id,
            "providerType": provider.provider_type,
            "uploadMode": session_info.upload_mode,
            "partSize": session_info.part_size,
            "storedName": stored_name,
            "isFallback": routing.is_fallback,
            "fallbackReason": routing.fallback_reason,
            "next": {
                "method": session_info.next_method,
                "url": session_info.next_url,
                "headers": session_info.next_headers,
                "completeUrl": session_info.complete_url,
                "metadata": session_info.metadata,
            },
        }

    @classmethod
    async def sign_part(
        cls,
        db: Session,
        *,
        session_id: str,
        part_number: int,
    ) -> dict[str, Any]:
        """Sign a specific multipart upload part URL."""
        res = db.get(UploadReservation, session_id)
        if not res or res.status != "reserved":
            raise StorageError("Upload session not found or already completed/expired")

        provider = db.get(StorageProvider, res.provider_id)
        if not provider:
            raise StorageError("Provider not found")

        adapter = ProviderManager.get_adapter_for_provider(provider)

        if provider.provider_type == "s3":
            # For S3, read key and uploadId from reservation metadata
            try:
                data = json.loads(res.upload_data_json or "{}")
                metadata = data.get("next", {}).get("metadata", {})
                key = metadata.get("key", "")
                upload_id = metadata.get("uploadId", "")
                from app.services.storage.s3_adapter import S3CompatibleAdapter

                if isinstance(adapter, S3CompatibleAdapter) and key and upload_id:
                    signed_url = adapter.sign_part_with_metadata(key, upload_id, part_number)
                    return {"partNumber": part_number, "url": signed_url}
            except Exception as e:
                log.warning("S3 sign_part_with_metadata error: %s", e)

        signed_url = await adapter.sign_part(res.provider_session_id, part_number)
        return {"partNumber": part_number, "url": signed_url}

    @classmethod
    async def complete_direct_upload(
        cls,
        db: Session,
        *,
        session_id: str,
        parts: list[dict[str, Any]] | None = None,
        upload_key: str | None = None,
    ) -> MediaAsset:
        """Complete upload on provider, create MediaAsset and link to event."""
        res = db.get(UploadReservation, session_id)
        if not res:
            raise StorageError("Upload reservation not found")
        if res.status == "completed":
            # Idempotent retry: return existing asset
            existing = db.scalar(
                select(MediaAsset).where(MediaAsset.upload_session_ref == session_id)
            )
            if existing:
                return existing

        if res.status != "reserved":
            raise StorageError(f"Upload reservation is in state '{res.status}' and cannot be completed")

        provider = db.get(StorageProvider, res.provider_id)
        if not provider:
            raise StorageError("Storage provider not found")

        adapter = ProviderManager.get_adapter_for_provider(provider)

        try:
            extra_data = json.loads(res.upload_data_json or "{}")
        except Exception:
            extra_data = {}

        stored_name = extra_data.get("stored_name") or res.filename
        folder_path = extra_data.get("folder_path") or ""

        # S3 multipart complete needs parts and key
        final_key = extra_data.get("next", {}).get("metadata", {}).get("key") or stored_name

        try:
            file_entry = await adapter.complete_upload(
                session_id=res.provider_session_id,
                parts=parts,
                upload_key=upload_key or final_key,
            )
        except Exception as e:
            StorageRoutingManager.release_reservation(db, session_id, new_status="failed")
            raise StorageError(f"Could not verify completed upload with provider: {e}") from e

        # Register final MediaAsset
        asset = MediaRegistry.register_asset(
            db,
            event_id=res.event_id,
            provider_id=provider.id,
            provider_type=provider.provider_type,
            provider_file_id=file_entry.file_id or file_entry.hash_or_etag or stored_name,
            stored_name=stored_name,
            original_name=res.filename,
            mime=file_entry.mime or res.mime,
            size_bytes=file_entry.size_bytes or res.file_size,
            media_category=res.category,
            ticket_id=res.ticket_id,
            provider_path=folder_path,
            upload_session_ref=session_id,
            upload_status="completed",
        )

        # Mark reservation completed
        StorageRoutingManager.release_reservation(db, session_id, new_status="completed")
        return asset

    @classmethod
    async def cancel_upload_session(cls, db: Session, session_id: str) -> bool:
        res = db.get(UploadReservation, session_id)
        if not res:
            return False

        provider = db.get(StorageProvider, res.provider_id)
        if provider:
            adapter = ProviderManager.get_adapter_for_provider(provider)
            try:
                await adapter.cancel_upload(res.provider_session_id or session_id)
            except Exception as e:
                log.warning("Cancel upload failed on provider: %s", e)

        StorageRoutingManager.release_reservation(db, session_id, new_status="cancelled")
        return True

    @classmethod
    async def upload_server_fallback(
        cls,
        db: Session,
        *,
        event_id: int,
        filename: str,
        data: bytes,
        mime: str,
        media_kind: str = "image",
        category: str = "memories_photo",
        ticket_id: int | None = None,
    ) -> MediaAsset:
        """Direct server-side upload fallback when browser uploads multipart to WE WERE HERE."""
        file_size = len(data)
        routing = await StorageRoutingManager.select_provider_and_reserve(
            db,
            event_id=event_id,
            filename=filename,
            file_size=file_size,
            mime=mime,
            media_kind=media_kind,
            category=category,
            ticket_id=ticket_id,
        )
        provider = routing.provider
        reservation = routing.reservation
        adapter = ProviderManager.get_adapter_for_provider(provider)

        folder = await FolderManager.get_folder_for_upload(
            db,
            event_id=event_id,
            provider_id=provider.id,
            category=category,
        )
        parent_folder_id = folder.provider_folder_id if folder else None
        folder_path = folder.provider_folder_path if folder else ""
        stored_name = FolderManager.generate_safe_stored_filename(filename, media_kind=media_kind)

        try:
            entry = await adapter.upload_direct_bytes(
                data=data,
                filename=stored_name,
                mime=mime,
                parent_folder_id=parent_folder_id,
            )
        except Exception:
            StorageRoutingManager.release_reservation(db, reservation.id, new_status="failed")
            raise

        asset = MediaRegistry.register_asset(
            db,
            event_id=event_id,
            provider_id=provider.id,
            provider_type=provider.provider_type,
            provider_file_id=entry.file_id or stored_name,
            stored_name=stored_name,
            original_name=filename,
            mime=entry.mime or mime,
            size_bytes=entry.size_bytes or file_size,
            media_category=category,
            ticket_id=ticket_id,
            provider_path=folder_path,
            upload_session_ref=reservation.id,
            upload_status="completed",
        )

        StorageRoutingManager.release_reservation(db, reservation.id, new_status="completed")
        return asset
