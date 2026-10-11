from pathlib import Path

from app.config import settings


def receipt_path(file_path: str) -> Path:
    if file_path.startswith("legacy/"):
        sub = file_path.replace("legacy/receipts/", "").replace("legacy/", "")
        return settings.legacy_uploads / "receipts" / sub
    return settings.storage_root / file_path
