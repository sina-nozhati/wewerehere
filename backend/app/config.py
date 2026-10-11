from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    host: str = "127.0.0.1"
    port: int = 5173
    admin_password: str = ""
    # Populated from ADMIN_PASSWORD env via model validator below
    database_url: str = f"sqlite:///{ROOT / 'data.sqlite'}"
    storage_root: Path = ROOT / "storage"
    legacy_uploads: Path = ROOT / "uploads"

    cors_origins: str = ""

    @property
    def receipts_dir(self) -> Path:
        return self.storage_root / "receipts"

    @property
    def archive_dir(self) -> Path:
        return self.storage_root / "archive"

    @property
    def public_media_dir(self) -> Path:
        return self.storage_root / "public"


import os

_settings = Settings()
if not _settings.admin_password:
    _settings.admin_password = os.environ.get("ADMIN_PASSWORD", "")
settings = _settings
