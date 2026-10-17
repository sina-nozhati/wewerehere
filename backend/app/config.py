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

    # SMS (sms.ir Verify) — secrets only via env / EnvironmentFile, never commit keys
    sms_provider: str = "console"
    sms_ir_api_key: str = ""
    sms_ir_template_id_ticket_notify: int = 0
    sms_ir_template_id_admin: int = 0
    sms_ir_verify_parameter_name: str = "CODE"
    sms_ir_timeout: float = 10.0
    sms_ir_admin_presets: str = ""

    # Disposable camera / memories («شبی که اینجا بودیم»)
    memory_photo_max_mb: int = 8
    memory_video_max_mb: int = 25
    memory_video_max_sec: int = 60
    memory_max_files_per_request: int = 5
    memory_max_files_per_ticket: int = 30
    memory_session_ttl_hours: int = 12
    memory_gate_max_attempts: int = 12
    memory_gate_window_sec: float = 600.0
    memory_ffmpeg_bin: str = "ffmpeg"
    memory_ffprobe_bin: str = "ffprobe"

    @property
    def receipts_dir(self) -> Path:
        return self.storage_root / "receipts"

    @property
    def archive_dir(self) -> Path:
        return self.storage_root / "archive"

    @property
    def public_media_dir(self) -> Path:
        return self.storage_root / "public"

    @property
    def memories_dir(self) -> Path:
        return self.storage_root / "memories"


import os

_settings = Settings()
if not _settings.admin_password:
    _settings.admin_password = os.environ.get("ADMIN_PASSWORD", "")
settings = _settings
