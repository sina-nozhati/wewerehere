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
from app.routers import admin, memories, public, support


def _ensure_dirs():
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.receipts_dir.mkdir(parents=True, exist_ok=True)
    settings.archive_dir.mkdir(parents=True, exist_ok=True)
    settings.public_media_dir.mkdir(parents=True, exist_ok=True)
    settings.memories_dir.mkdir(parents=True, exist_ok=True)


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


def _rebuild_memory_child_table(conn, *, table: str, create_sql: str, copy_sql: str) -> None:
    """Recreate a child table so FKs point at current memory_items (not a renamed stub)."""
    import sqlalchemy as sa

    conn.execute(sa.text(f"ALTER TABLE {table} RENAME TO {table}__old"))
    conn.execute(sa.text(create_sql))
    conn.execute(sa.text(copy_sql))
    conn.execute(sa.text(f"DROP TABLE {table}__old"))


def _memory_child_fk_broken(conn, table: str) -> bool:
    import sqlalchemy as sa

    row = conn.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": table},
    ).first()
    if not row or not row[0]:
        return False
    sql = row[0].replace('"', "").lower()
    return "memory_items__old" in sql


def _repair_memory_child_fks(conn) -> None:
    """Fix likes/comments FKs left pointing at memory_items__old after a rename migration."""
    import sqlalchemy as sa

    tables = {r[0] for r in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}
    need_likes = "memory_likes" in tables and _memory_child_fk_broken(conn, "memory_likes")
    need_comments = "memory_comments" in tables and _memory_child_fk_broken(conn, "memory_comments")
    if not need_likes and not need_comments:
        return

    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    if need_likes:
        _rebuild_memory_child_table(
            conn,
            table="memory_likes",
            create_sql="""
                CREATE TABLE memory_likes (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_memory_like_item_ticket UNIQUE (item_id, ticket_id),
                    FOREIGN KEY(item_id) REFERENCES memory_items (id),
                    FOREIGN KEY(ticket_id) REFERENCES tickets (id)
                )
            """,
            copy_sql="""
                INSERT INTO memory_likes (id, item_id, ticket_id, created_at)
                SELECT id, item_id, ticket_id, created_at FROM memory_likes__old
            """,
        )
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_likes_item_id ON memory_likes (item_id)"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_likes_ticket_id ON memory_likes (ticket_id)"))
    if need_comments:
        _rebuild_memory_child_table(
            conn,
            table="memory_comments",
            create_sql="""
                CREATE TABLE memory_comments (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    display_name VARCHAR(80) NOT NULL,
                    body VARCHAR(500) NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES memory_items (id),
                    FOREIGN KEY(ticket_id) REFERENCES tickets (id)
                )
            """,
            copy_sql="""
                INSERT INTO memory_comments (id, item_id, ticket_id, display_name, body, created_at)
                SELECT id, item_id, ticket_id, display_name, body, created_at FROM memory_comments__old
            """,
        )
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_comments_item_id ON memory_comments (item_id)"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_comments_ticket_id ON memory_comments (ticket_id)"))
    conn.execute(sa.text("PRAGMA foreign_keys=ON"))


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
        "memory_items": [
            ("title", "VARCHAR(200) NOT NULL DEFAULT ''"),
            ("source", "VARCHAR(32) NOT NULL DEFAULT 'guest'"),
        ],
        "media": [
            ("published_memory_id", "INTEGER"),
        ],
    }
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}
        for table, cols in needed.items():
            if table not in tables:
                continue
            existing = {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        # Allow NULL ticket_id on memory_items (admin_archive publishes)
        if "memory_items" in tables:
            cols = list(conn.execute(sa.text("PRAGMA table_info(memory_items)")))
            ticket = next((c for c in cols if c[1] == "ticket_id"), None)
            if ticket is not None and int(ticket[3] or 0) == 1:
                conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
                conn.execute(sa.text("ALTER TABLE memory_items RENAME TO memory_items__old"))
                conn.execute(
                    sa.text(
                        """
                        CREATE TABLE memory_items (
                            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                            event_id INTEGER NOT NULL,
                            ticket_id INTEGER,
                            status VARCHAR(16) NOT NULL,
                            source VARCHAR(32) NOT NULL DEFAULT 'guest',
                            media_kind VARCHAR(16) NOT NULL,
                            stored_name VARCHAR(300) NOT NULL,
                            mime VARCHAR(120) NOT NULL,
                            size_bytes INTEGER NOT NULL,
                            width INTEGER,
                            height INTEGER,
                            duration_ms INTEGER,
                            consent_publish BOOLEAN NOT NULL,
                            title VARCHAR(200) NOT NULL DEFAULT '',
                            created_at DATETIME,
                            reviewed_at DATETIME,
                            reviewed_by VARCHAR(64) NOT NULL DEFAULT '',
                            FOREIGN KEY(event_id) REFERENCES events (id),
                            FOREIGN KEY(ticket_id) REFERENCES tickets (id)
                        )
                        """
                    )
                )
                old_cols = {c[1] for c in cols}
                has_source = "source" in old_cols
                has_title = "title" in old_cols
                select_source = "source" if has_source else "'guest'"
                select_title = "title" if has_title else "''"
                conn.execute(
                    sa.text(
                        f"""
                        INSERT INTO memory_items (
                            id, event_id, ticket_id, status, source, media_kind, stored_name, mime,
                            size_bytes, width, height, duration_ms, consent_publish, title,
                            created_at, reviewed_at, reviewed_by
                        )
                        SELECT
                            id, event_id, ticket_id, status, {select_source}, media_kind, stored_name, mime,
                            size_bytes, width, height, duration_ms, consent_publish, {select_title},
                            created_at, reviewed_at, reviewed_by
                        FROM memory_items__old
                        """
                    )
                )
                # Rebuild children while FK off so they don't keep pointing at memory_items__old
                tables_now = {r[0] for r in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}
                if "memory_likes" in tables_now:
                    _rebuild_memory_child_table(
                        conn,
                        table="memory_likes",
                        create_sql="""
                            CREATE TABLE memory_likes (
                                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                                item_id INTEGER NOT NULL,
                                ticket_id INTEGER NOT NULL,
                                created_at DATETIME NOT NULL,
                                CONSTRAINT uq_memory_like_item_ticket UNIQUE (item_id, ticket_id),
                                FOREIGN KEY(item_id) REFERENCES memory_items (id),
                                FOREIGN KEY(ticket_id) REFERENCES tickets (id)
                            )
                        """,
                        copy_sql="""
                            INSERT INTO memory_likes (id, item_id, ticket_id, created_at)
                            SELECT id, item_id, ticket_id, created_at FROM memory_likes__old
                        """,
                    )
                if "memory_comments" in tables_now:
                    _rebuild_memory_child_table(
                        conn,
                        table="memory_comments",
                        create_sql="""
                            CREATE TABLE memory_comments (
                                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                                item_id INTEGER NOT NULL,
                                ticket_id INTEGER NOT NULL,
                                display_name VARCHAR(80) NOT NULL,
                                body VARCHAR(500) NOT NULL,
                                created_at DATETIME NOT NULL,
                                FOREIGN KEY(item_id) REFERENCES memory_items (id),
                                FOREIGN KEY(ticket_id) REFERENCES tickets (id)
                            )
                        """,
                        copy_sql="""
                            INSERT INTO memory_comments (id, item_id, ticket_id, display_name, body, created_at)
                            SELECT id, item_id, ticket_id, display_name, body, created_at FROM memory_comments__old
                        """,
                    )
                conn.execute(sa.text("DROP TABLE memory_items__old"))
                conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_items_event_id ON memory_items (event_id)"))
                conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_items_ticket_id ON memory_items (ticket_id)"))
                conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_items_status ON memory_items (status)"))
                conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memory_items_source ON memory_items (source)"))
                conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        # Repair DBs already broken by an earlier rename that left child FKs on __old
        _repair_memory_child_fks(conn)
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
app.include_router(memories.router)

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


@app.get("/events/{slug}/memories")
def memories_page(slug: str):
    """Stable QR target — page reads slug from path."""
    fp = (ROOT / "memories.html").resolve()
    if not fp.is_file():
        raise HTTPException(404)
    return FileResponse(fp)


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
