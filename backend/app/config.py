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

    # Media Storage Manager (Files.ir, S3, Local)
    files_ir_api_endpoint: str = "https://my.files.ir/api/v1"
    files_ir_api_key: str = ""
    files_ir_workspace_id: int = 0
    files_ir_total_capacity_bytes: int = 10 * 1024 * 1024 * 1024
    files_ir_file_count_limit: int = 3000
    files_ir_max_file_size_bytes: int = 500 * 1024 * 1024

    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_force_path_style: bool = True

    storage_warning_threshold: float = 0.80
    storage_critical_threshold: float = 0.90
    storage_reservation_ttl_sec: int = 1800

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
