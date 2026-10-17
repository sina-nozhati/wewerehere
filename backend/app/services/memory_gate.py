"""Ticket-code gate + durable memory upload sessions."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import check_rate_limit
from app.config import settings
from app.models import Event, MemoryItem, MemorySession, Ticket, utcnow
from app.services.phone import normalize_serial

_gate_attempts: dict[str, list[float]] = {}
_SERIAL_RE = re.compile(r"^\d{4}$")


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def client_fingerprint(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else "") or "unknown"
    ua = (request.headers.get("user-agent") or "")[:180]
    raw = f"{ip}|{ua}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def resolve_event_by_slug(db: Session, slug: str) -> Event:
    ev = db.scalar(select(Event).where(Event.slug == slug))
    if not ev or ev.status in ("draft", "cancelled"):
        raise HTTPException(404, {"error": "event_not_found"})
    return ev


def event_public_card(ev: Event) -> dict:
    return {
        "id": ev.id,
        "slug": ev.slug,
        "title": ev.title,
        "episodeNumber": ev.episode_number,
        "city": (ev.city or "").strip(),
        "venue": (ev.venue or "").strip(),
    }


def create_memory_session(db: Session, *, event: Event, ticket: Ticket) -> str:
    token = secrets.token_urlsafe(32)
    ttl = max(1, int(settings.memory_session_ttl_hours))
    now = utcnow()
    row = MemorySession(
        token_hash=hash_session_token(token),
        event_id=event.id,
        ticket_id=ticket.id,
        expires_at=now + timedelta(hours=ttl),
        created_at=now,
        last_seen_at=now,
    )
    db.add(row)
    db.commit()
    return token


def get_valid_session(db: Session, token: str | None) -> MemorySession | None:
    if not token:
        return None
    row = db.get(MemorySession, hash_session_token(token))
    if not row:
        return None
    now = utcnow()
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        db.delete(row)
        db.commit()
        return None
    row.last_seen_at = now
    db.commit()
    return row


def require_memory_session(db: Session, token: str | None, event: Event) -> MemorySession:
    sess = get_valid_session(db, token)
    if not sess or sess.event_id != event.id:
        raise HTTPException(401, {"error": "session_required"})
    ticket = db.get(Ticket, sess.ticket_id)
    if not ticket or ticket.status != "active" or ticket.event_id != event.id:
        raise HTTPException(403, {"error": "ticket_inactive"})
    return sess


def gate_with_serial(
    db: Session,
    *,
    event: Event,
    serial_raw: str,
    request: Request,
) -> tuple[str, Ticket]:
    """Validate serial for this event; return (session_token, ticket)."""
    fp = client_fingerprint(request)
    key = f"mem-gate:{event.id}:{fp}"
    check_rate_limit(
        _gate_attempts,
        key,
        int(settings.memory_gate_max_attempts),
        float(settings.memory_gate_window_sec),
    )

    serial = normalize_serial(serial_raw)
    if not _SERIAL_RE.fullmatch(serial):
        raise HTTPException(400, {"error": "invalid_code"})

    ticket = db.scalar(
        select(Ticket).where(
            Ticket.event_id == event.id,
            Ticket.public_code == serial,
            Ticket.status == "active",
        )
    )
    if not ticket:
        # Same error shape for wrong event / revoked / unknown — no leakage
        raise HTTPException(403, {"error": "code_rejected"})

    token = create_memory_session(db, event=event, ticket=ticket)
    return token, ticket


def count_ticket_uploads(db: Session, ticket_id: int) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(MemoryItem).where(MemoryItem.ticket_id == ticket_id)
        )
        or 0
    )
