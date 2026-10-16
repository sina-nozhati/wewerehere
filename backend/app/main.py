import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import hash_admin_password
from app.config import ROOT, settings
from app.db import Base, engine
from app.routers import admin, public, support


def _ensure_dirs():
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.receipts_dir.mkdir(parents=True, exist_ok=True)
    settings.archive_dir.mkdir(parents=True, exist_ok=True)
    settings.public_media_dir.mkdir(parents=True, exist_ok=True)


def _maybe_migrate_legacy():
    if os.environ.get("WW_DISABLE_MIGRATE"):
        return
    db_path = ROOT / "data.sqlite"
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    if "events" in tables:
        return
    if "tickets" not in tables and "orders" not in tables:
        return
    import subprocess
    import sys

    script = ROOT / "backend" / "scripts" / "migrate_legacy.py"
    subprocess.run([sys.executable, str(script)], cwd=str(ROOT / "backend"), check=False)


def _migrate_sqlite_columns():
    """Add columns to existing SQLite DBs without Alembic."""
    if not str(settings.database_url).startswith("sqlite"):
        return
    import sqlalchemy as sa

    needed = {
        "events": [
            ("host_name", "VARCHAR(200) NOT NULL DEFAULT ''"),
            ("host_venue", "VARCHAR(200) NOT NULL DEFAULT ''"),
            ("location_lat", "FLOAT"),
            ("location_lng", "FLOAT"),
            ("location_label", "VARCHAR(280) NOT NULL DEFAULT ''"),
            ("location_published", "BOOLEAN NOT NULL DEFAULT 0"),
        ],
    }
    with engine.connect() as conn:
        for table, cols in needed.items():
            existing = {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        conn.commit()


def _seed_if_empty():
    from app.db import SessionLocal
    from app.models import Event, SiteSetting
    from app.services.events import FEATURED_KEY, set_featured_event_id
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        from sqlalchemy import func, select

        if db.scalar(select(func.count()).select_from(Event)):
            return
        ev = Event(
            slug="third-shahrivar",
            title="ما اینجا بودیم",
            episode_number=3,
            description="WE WERE HERE — رویداد موسیقی",
            event_at=datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
            city="تهران",
            venue="",
            capacity=int(os.environ.get("CAPACITY", "50")),
            ticket_price=int(os.environ.get("TICKET_PRICE", "0") or 0),
            payment_card_number=os.environ.get("PAYMENT_CARD_NUMBER", ""),
            payment_card_holder=os.environ.get("PAYMENT_CARD_HOLDER", ""),
            payment_bank_name=os.environ.get("PAYMENT_BANK_NAME", ""),
            status="sales_open",
            sales_status="open",
            setlist_json="[]",
            artists_json="[]",
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        set_featured_event_id(db, ev.id)
    finally:
        db.close()


def _ensure_admin_password():
    if not settings.admin_password:
        plain = os.environ.get("ADMIN_PASSWORD", "")
        if not plain:
            plain = "wewerehere-admin"
            print("[wwh] WARNING: set ADMIN_PASSWORD in production")
        os.environ["ADMIN_PASSWORD"] = plain
        # Re-load for bcrypt check path in auth
        from app.config import Settings

        object.__setattr__(settings, "admin_password", plain)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_dirs()
    _ensure_admin_password()
    _maybe_migrate_legacy()
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()
    _seed_if_empty()
    yield


app = FastAPI(title="WE WERE HERE", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

app.include_router(public.router)
app.include_router(admin.router)
app.include_router(support.router)

if settings.public_media_dir.exists():
    app.mount("/storage/public", StaticFiles(directory=str(settings.public_media_dir)), name="public-storage")


def _safe_static_path(rel: str) -> Path:
    rel = rel.lstrip("/")
    if rel in ("", "index", "index.html"):
        rel = "index.html"
    elif rel == "admin":
        rel = "admin.html"
    elif rel == "track":
        rel = "track.html"
    elif rel == "support":
        rel = "support.html"
    elif rel == "episodes":
        rel = "episodes.html"
    file_path = (ROOT / rel).resolve()
    if not str(file_path).startswith(str(ROOT.resolve())):
        raise HTTPException(403, "forbidden")
    return file_path


@app.get("/{full_path:path}")
def spa_static(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    fp = _safe_static_path(full_path)
    if fp.is_file():
        return FileResponse(fp)
    raise HTTPException(404)


def run():
    import uvicorn

    port = int(os.environ.get("PORT", settings.port))
    host = os.environ.get("HOST", settings.host)
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
