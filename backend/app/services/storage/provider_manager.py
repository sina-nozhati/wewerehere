"""ProviderManager: Manages storage provider lifecycle, registration, and credentials."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event, EventStorageConfig, StorageProvider, utcnow
from app.services.storage.base_adapter import StorageError, StorageProviderAdapter
from app.services.storage.files_ir_adapter import FilesIrAdapter
from app.services.storage.local_adapter import LocalStorageAdapter
from app.services.storage.s3_adapter import S3CompatibleAdapter

log = logging.getLogger("wwh.storage.provider_manager")

SECRET_FIELDS = {"api_key", "secret_key", "access_key"}


def mask_secret(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 6:
        return "******"
    return f"{val[:3]}...{val[-3:]}"


def mask_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a safe copy of config dict with secrets masked for admin UI/API."""
    masked: dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_FIELDS and isinstance(v, str) and v:
            masked[k] = mask_secret(v)
            masked[f"has_{k}"] = True
        else:
            masked[k] = v
    return masked


def unmask_config(new_config: dict[str, Any], old_config: dict[str, Any]) -> dict[str, Any]:
    """Preserve existing secret if new_config contains a masked value."""
    result = dict(new_config)
    for field in SECRET_FIELDS:
        val = str(result.get(field) or "").strip()
        if not val or "..." in val or "*" in val:
            # Keep original secret
            if field in old_config:
                result[field] = old_config[field]
    return result


class ProviderManager:
    """Singleton service for provider registration and adapter instantiation."""

    _adapters_cache: dict[int, StorageProviderAdapter] = {}

    @classmethod
    def get_adapter_for_provider(cls, provider: StorageProvider) -> StorageProviderAdapter:
        try:
            config = json.loads(provider.config_json or "{}")
        except Exception:
            config = {}

        # Merge with global env settings
        if provider.provider_type == "files_ir":
            if not config.get("api_key") and settings.files_ir_api_key:
                config["api_key"] = settings.files_ir_api_key
            if not config.get("api_endpoint") and settings.files_ir_api_endpoint:
                config["api_endpoint"] = settings.files_ir_api_endpoint
            return FilesIrAdapter(config)
        elif provider.provider_type == "s3":
            if not config.get("endpoint") and settings.s3_endpoint:
                config["endpoint"] = settings.s3_endpoint
            if not config.get("bucket") and settings.s3_bucket:
                config["bucket"] = settings.s3_bucket
            if not config.get("access_key") and settings.s3_access_key:
                config["access_key"] = settings.s3_access_key
            if not config.get("secret_key") and settings.s3_secret_key:
                config["secret_key"] = settings.s3_secret_key
            return S3CompatibleAdapter(config)
        elif provider.provider_type == "local":
            return LocalStorageAdapter(config)
        else:
            raise StorageError(f"Unknown provider type: {provider.provider_type}")

    @classmethod
    def get_adapter(cls, db: Session, provider_id: int) -> StorageProviderAdapter:
        provider = db.get(StorageProvider, provider_id)
        if not provider:
            raise StorageError(f"Storage provider with id {provider_id} not found")
        return cls.get_adapter_for_provider(provider)

    @classmethod
    def seed_default_providers(cls, db: Session) -> None:
        """Seed initial storage providers and link events if empty."""
        existing = {p.key: p for p in db.scalars(select(StorageProvider)).all()}

        # 1. Files.ir provider
        if "files_ir_main" not in existing:
            has_key = bool(settings.files_ir_api_key)
            f_config = {
                "api_endpoint": settings.files_ir_api_endpoint,
                "api_key": settings.files_ir_api_key,
                "workspace_id": settings.files_ir_workspace_id,
            }
            p_files = StorageProvider(
                key="files_ir_main",
                name="Files.ir Cloud Storage",
                provider_type="files_ir",
                is_enabled=True,
                priority=1,
                config_json=json.dumps(f_config),
                max_file_size_bytes=settings.files_ir_max_file_size_bytes,
                file_count_limit=settings.files_ir_file_count_limit,
                total_capacity_bytes=settings.files_ir_total_capacity_bytes,
                health_status="unknown" if has_key else "unconfigured",
            )
            db.add(p_files)
            db.flush()
            existing["files_ir_main"] = p_files

        # 2. Local VPS Storage provider (for legacy media & local dev)
        if "local_storage" not in existing:
            p_local = StorageProvider(
                key="local_storage",
                name="Local VPS Storage",
                provider_type="local",
                is_enabled=True,
                priority=99,
                config_json=json.dumps({"root_dir": str(settings.storage_root)}),
                max_file_size_bytes=100 * 1024 * 1024,
                health_status="healthy",
            )
            db.add(p_local)
            db.flush()
            existing["local_storage"] = p_local

        # 3. S3 Storage provider
        if "s3_backup" not in existing:
            s3_config = {
                "endpoint": settings.s3_endpoint,
                "bucket": settings.s3_bucket,
                "access_key": settings.s3_access_key,
                "secret_key": settings.s3_secret_key,
                "region": settings.s3_region,
                "force_path_style": settings.s3_force_path_style,
            }
            has_s3 = bool(settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key)
            p_s3 = StorageProvider(
                key="s3_backup",
                name="S3 Cloud Storage",
                provider_type="s3",
                is_enabled=has_s3,
                priority=2,
                config_json=json.dumps(s3_config),
                max_file_size_bytes=5 * 1024 * 1024 * 1024,
                health_status="unknown" if has_s3 else "unconfigured",
            )
            db.add(p_s3)
            db.flush()
            existing["s3_backup"] = p_s3

        # Default Event Storage Assignments
        files_prov = existing.get("files_ir_main")
        local_prov = existing.get("local_storage")
        s3_prov = existing.get("s3_backup")

        # Determine preferred primary provider
        primary_id = files_prov.id if files_prov and settings.files_ir_api_key else (local_prov.id if local_prov else 1)
        fallback_ids: list[int] = []
        if local_prov and local_prov.id != primary_id:
            fallback_ids.append(local_prov.id)
        if s3_prov and s3_prov.is_enabled and s3_prov.id != primary_id:
            fallback_ids.append(s3_prov.id)

        events = db.scalars(select(Event)).all()
        for ev in events:
            cfg = db.scalar(select(EventStorageConfig).where(EventStorageConfig.event_id == ev.id))
            if not cfg:
                new_cfg = EventStorageConfig(
                    event_id=ev.id,
                    primary_provider_id=primary_id,
                    fallback_provider_ids_json=json.dumps(fallback_ids),
                    routing_status="active",
                )
                db.add(new_cfg)

        db.commit()

    @classmethod
    async def test_provider_health(cls, db: Session, provider_id: int) -> dict[str, Any]:
        """Execute a connectivity and health check for a provider and update its DB record."""
        provider = db.get(StorageProvider, provider_id)
        if not provider:
            raise StorageError(f"Provider {provider_id} not found")

        adapter = cls.get_adapter_for_provider(provider)
        is_healthy, msg = await adapter.check_connectivity()
        usage_data: dict[str, Any] = {}

        if is_healthy:
            provider.health_status = "healthy"
            provider.health_error = ""
            try:
                usage = await adapter.get_storage_usage()
                usage_data = {
                    "totalBytes": usage.total_bytes,
                    "usedBytes": usage.used_bytes,
                    "availableBytes": usage.available_bytes,
                    "percentUsed": round(usage.percent_used, 1),
                }
                if usage.total_bytes > 0:
                    provider.total_capacity_bytes = usage.total_bytes
            except Exception as e:
                log.warning("Provider %s health test usage query error: %s", provider.key, e)
        else:
            provider.health_status = "unreachable"
            provider.health_error = msg

        provider.last_health_check_at = utcnow()
        db.commit()
        db.refresh(provider)

        return {
            "id": provider.id,
            "key": provider.key,
            "name": provider.name,
            "isHealthy": is_healthy,
            "status": provider.health_status,
            "message": msg,
            "checkedAt": provider.last_health_check_at.isoformat(),
            "usage": usage_data,
        }
