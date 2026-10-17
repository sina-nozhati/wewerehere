"""Public disposable-camera / memories API — gated by event-scoped ticket serial."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import MemoryComment, MemoryItem, MemoryLike, Ticket, utcnow
from app.services.memory_audit import write_audit
from app.services.memory_gate import (
    count_ticket_uploads,
    event_public_card,
    gate_with_serial,
    get_valid_session,
    require_memory_session,
    resolve_event_by_slug,
)
from app.services.memory_media import (
    MemoryMediaError,
    absolute_memory_path,
    max_bytes_for_kind,
    sniff_media,
    store_memory_file,
)
from app.services.tickets import active_rank_map, public_number

router = APIRouter(tags=["memories"])
_bearer = HTTPBearer(auto_error=False)


class GateBody(BaseModel):
    serial: str = ""
    publicCode: str = ""


class CommentBody(BaseModel):
    displayName: str = ""
    body: str = ""


def _bearer_token(creds: HTTPAuthorizationCredentials | None) -> str | None:
    return creds.credentials if creds else None


def _iso(dt) -> str | None:
    from datetime import timezone

    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _ticket_card(db: Session, ticket: Ticket) -> dict:
    ranks = active_rank_map(db, ticket.event_id)
    number = public_number(ticket, ranks) or ticket.display_number
    return {
        "number": number,
        "serial": ticket.public_code,
        "name": ticket.holder_name or "",
        "group": ticket.group_name or "",
    }


def _make_archive_bundle(db: Session, event_id: int, ticket_id: int) -> dict:
    from app.routers.public import _archive_media_list, _archive_sessions

    session = secrets.token_urlsafe(24)
    _archive_sessions[session] = {
        "event_id": event_id,
        "ticket_id": ticket_id,
        "exp": datetime.now(timezone.utc).timestamp() + 3600,
    }
    return {
        "archiveSession": session,
        "archiveMedia": _archive_media_list(db, event_id, session=session),
    }


def _like_counts(db: Session, item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(MemoryLike.item_id, func.count())
        .where(MemoryLike.item_id.in_(item_ids))
        .group_by(MemoryLike.item_id)
    ).all()
    return {int(i): int(c) for i, c in rows}


def _liked_set(db: Session, item_ids: list[int], ticket_id: int | None) -> set[int]:
    if not item_ids or not ticket_id:
        return set()
    rows = db.scalars(
        select(MemoryLike.item_id).where(
            MemoryLike.item_id.in_(item_ids), MemoryLike.ticket_id == ticket_id
        )
    ).all()
    return {int(x) for x in rows}


def _comment_counts(db: Session, item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(MemoryComment.item_id, func.count())
        .where(MemoryComment.item_id.in_(item_ids))
        .group_by(MemoryComment.item_id)
    ).all()
    return {int(i): int(c) for i, c in rows}


@router.post("/api/events/{slug}/memories/gate")
def memories_gate(
    slug: str,
    body: GateBody,
    request: Request,
    db: Session = Depends(get_db),
):
    ev = resolve_event_by_slug(db, slug)
    serial = body.serial or body.publicCode or ""
    token, ticket = gate_with_serial(db, event=ev, serial_raw=serial, request=request)
    remaining = max(0, int(settings.memory_max_files_per_ticket) - count_ticket_uploads(db, ticket.id))
    archive = _make_archive_bundle(db, ev.id, ticket.id)
    return {
        "sessionToken": token,
        "event": event_public_card(ev),
        "ticket": _ticket_card(db, ticket),
        "archiveSession": archive["archiveSession"],
        "archiveMedia": archive["archiveMedia"],
        "uploadsRemaining": remaining,
        "limits": {
            "photoMaxMb": settings.memory_photo_max_mb,
            "videoMaxMb": settings.memory_video_max_mb,
            "maxFilesPerRequest": settings.memory_max_files_per_request,
            "maxFilesPerTicket": settings.memory_max_files_per_ticket,
        },
    }


@router.get("/api/events/{slug}/memories/session")
def memories_session(
    slug: str,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    ev = resolve_event_by_slug(db, slug)
    sess = require_memory_session(db, _bearer_token(creds), ev)
    remaining = max(0, int(settings.memory_max_files_per_ticket) - count_ticket_uploads(db, sess.ticket_id))
    ticket = db.get(Ticket, sess.ticket_id)
    archive = _make_archive_bundle(db, ev.id, sess.ticket_id) if ticket else {
        "archiveSession": "",
        "archiveMedia": [],
    }
    return {
        "ok": True,
        "event": event_public_card(ev),
        "ticket": _ticket_card(db, ticket) if ticket else None,
        "archiveSession": archive["archiveSession"],
        "archiveMedia": archive["archiveMedia"],
        "uploadsRemaining": remaining,
        "expiresAt": _iso(sess.expires_at),
    }


@router.post("/api/events/{slug}/memories/upload")
async def memories_upload(
    slug: str,
    request: Request,
    consentPublish: Annotated[str, Form()] = "false",
    files: Annotated[list[UploadFile], File()] = None,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    authorization: Annotated[str | None, Header()] = None,
):
    ev = resolve_event_by_slug(db, slug)
    # Accept Bearer from dependency or raw header (some clients)
    token = _bearer_token(creds)
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    sess = require_memory_session(db, token, ev)

    consent = str(consentPublish or "").strip().lower() in ("1", "true", "yes", "on")
    if not consent:
        raise HTTPException(400, {"error": "consent_required"})

    upload_list = files or []
    if not upload_list:
        # Starlette may bind single file differently
        form = await request.form()
        upload_list = [v for k, v in form.multi_items() if hasattr(v, "read") and k == "files"]
        if not upload_list:
            upload_list = [v for k, v in form.multi_items() if hasattr(v, "read")]

    if not upload_list:
        raise HTTPException(400, {"error": "no_files"})

    max_n = int(settings.memory_max_files_per_request)
    if len(upload_list) > max_n:
        raise HTTPException(400, {"error": "too_many_files", "max": max_n})

    already = count_ticket_uploads(db, sess.ticket_id)
    room = int(settings.memory_max_files_per_ticket) - already
    if room <= 0:
        raise HTTPException(403, {"error": "ticket_quota_exceeded"})
    if len(upload_list) > room:
        raise HTTPException(400, {"error": "ticket_quota_exceeded", "remaining": room})

    results: list[dict] = []
    for uf in upload_list:
        name = getattr(uf, "filename", "") or ""
        try:
            data = await uf.read()
        except Exception:
            results.append({"ok": False, "error": "read_failed", "name": name})
            continue
        try:
            kind, mime, ext = sniff_media(data, name)
            limit = max_bytes_for_kind(kind)
            if len(data) > limit:
                results.append(
                    {
                        "ok": False,
                        "error": "file_too_large",
                        "name": name,
                        "maxBytes": limit,
                    }
                )
                continue
            stored = store_memory_file(ev.id, data, ext)
            item = MemoryItem(
                event_id=ev.id,
                ticket_id=sess.ticket_id,
                status="pending",
                source="guest",
                media_kind=kind,
                stored_name=stored,
                mime=mime,
                size_bytes=len(data),
                consent_publish=True,
            )
            db.add(item)
            db.flush()
            write_audit(
                db,
                event_id=ev.id,
                item_id=item.id,
                ticket_id=sess.ticket_id,
                actor="ticket",
                action="upload",
                meta={"mediaKind": kind, "sizeBytes": len(data)},
            )
            db.commit()
            db.refresh(item)
            results.append(
                {
                    "ok": True,
                    "id": item.id,
                    "status": item.status,
                    "mediaKind": kind,
                    "sizeBytes": len(data),
                }
            )
        except MemoryMediaError as e:
            results.append({"ok": False, "error": str(e), "name": name})
        except Exception:
            results.append({"ok": False, "error": "store_failed", "name": name})

    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok_count > 0,
        "accepted": ok_count,
        "rejected": len(results) - ok_count,
        "results": results,
        "uploadsRemaining": max(
            0, int(settings.memory_max_files_per_ticket) - count_ticket_uploads(db, sess.ticket_id)
        ),
        "message": "فایل‌ها برای بررسی ثبت شد؛ تا تأیید ادمین خصوصی می‌مونن.",
    }


@router.get("/api/events/{slug}/memories/gallery")
def memories_gallery(
    slug: str,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    ev = resolve_event_by_slug(db, slug)
    rows = db.scalars(
        select(MemoryItem)
        .where(MemoryItem.event_id == ev.id, MemoryItem.status == "approved")
        .order_by(MemoryItem.id.desc())
        .limit(200)
    ).all()
    ids = [m.id for m in rows]
    ticket_id = None
    token = _bearer_token(creds)
    if token:
        sess = get_valid_session(db, token)
        if sess and sess.event_id == ev.id:
            ticket_id = sess.ticket_id
    likes = _like_counts(db, ids)
    liked = _liked_set(db, ids, ticket_id)
    comments = _comment_counts(db, ids)
    return {
        "event": event_public_card(ev),
        "count": len(rows),
        "items": [
            {
                "id": m.id,
                "title": (m.title or "").strip(),
                "mediaKind": m.media_kind,
                "mime": m.mime,
                "url": f"/api/memories/file/{m.id}",
                "createdAt": _iso(m.created_at),
                "likeCount": likes.get(m.id, 0),
                "commentCount": comments.get(m.id, 0),
                "likedByMe": m.id in liked,
            }
            for m in rows
        ],
    }


@router.get("/api/events/{slug}/memories/leaderboard")
def memories_leaderboard(
    slug: str,
    db: Session = Depends(get_db),
):
    ev = resolve_event_by_slug(db, slug)
    rows = db.scalars(
        select(MemoryItem)
        .where(MemoryItem.event_id == ev.id, MemoryItem.status == "approved")
        .limit(200)
    ).all()
    ids = [m.id for m in rows]
    likes = _like_counts(db, ids)
    ranked = sorted(rows, key=lambda m: (likes.get(m.id, 0), m.id), reverse=True)
    top = []
    for m in ranked:
        lc = likes.get(m.id, 0)
        if lc <= 0:
            continue
        top.append(
            {
                "rank": len(top) + 1,
                "id": m.id,
                "title": (m.title or "").strip(),
                "mediaKind": m.media_kind,
                "mime": m.mime,
                "url": f"/api/memories/file/{m.id}",
                "likeCount": lc,
            }
        )
        if len(top) >= 3:
            break
    return {"event": event_public_card(ev), "items": top}


@router.get("/api/events/{slug}/memories/mine")
def memories_mine(
    slug: str,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    ev = resolve_event_by_slug(db, slug)
    sess = require_memory_session(db, _bearer_token(creds), ev)
    rows = db.scalars(
        select(MemoryItem)
        .where(MemoryItem.event_id == ev.id, MemoryItem.ticket_id == sess.ticket_id)
        .order_by(MemoryItem.id.desc())
        .limit(100)
    ).all()
    return {
        "event": event_public_card(ev),
        "count": len(rows),
        "items": [
            {
                "id": m.id,
                "title": (m.title or "").strip(),
                "status": m.status,
                "mediaKind": m.media_kind,
                "mime": m.mime,
                "url": f"/api/memories/file/{m.id}",
                "createdAt": _iso(m.created_at),
            }
            for m in rows
        ],
    }


@router.post("/api/events/{slug}/memories/{item_id}/like")
def memories_like_toggle(
    slug: str,
    item_id: int,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    ev = resolve_event_by_slug(db, slug)
    sess = require_memory_session(db, _bearer_token(creds), ev)
    item = db.get(MemoryItem, item_id)
    if not item or item.event_id != ev.id or item.status != "approved":
        raise HTTPException(404, {"error": "not_found"})
    existing = db.scalar(
        select(MemoryLike).where(
            MemoryLike.item_id == item.id, MemoryLike.ticket_id == sess.ticket_id
        )
    )
    liked = False
    if existing:
        db.delete(existing)
        liked = False
        action = "unlike"
    else:
        db.add(MemoryLike(item_id=item.id, ticket_id=sess.ticket_id))
        liked = True
        action = "like"
    write_audit(
        db,
        event_id=ev.id,
        item_id=item.id,
        ticket_id=sess.ticket_id,
        actor="ticket",
        action=action,
    )
    db.commit()
    count = int(
        db.scalar(select(func.count()).select_from(MemoryLike).where(MemoryLike.item_id == item.id))
        or 0
    )
    return {"ok": True, "liked": liked, "likeCount": count}


@router.get("/api/events/{slug}/memories/{item_id}/comments")
def memories_comments_list(
    slug: str,
    item_id: int,
    db: Session = Depends(get_db),
):
    ev = resolve_event_by_slug(db, slug)
    item = db.get(MemoryItem, item_id)
    if not item or item.event_id != ev.id or item.status != "approved":
        raise HTTPException(404, {"error": "not_found"})
    rows = db.scalars(
        select(MemoryComment)
        .where(MemoryComment.item_id == item.id)
        .order_by(MemoryComment.id.asc())
        .limit(100)
    ).all()
    return {
        "count": len(rows),
        "comments": [
            {
                "id": c.id,
                "displayName": c.display_name,
                "body": c.body,
                "createdAt": _iso(c.created_at),
            }
            for c in rows
        ],
    }


@router.post("/api/events/{slug}/memories/{item_id}/comments")
def memories_comments_create(
    slug: str,
    item_id: int,
    body: CommentBody,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    ev = resolve_event_by_slug(db, slug)
    sess = require_memory_session(db, _bearer_token(creds), ev)
    item = db.get(MemoryItem, item_id)
    if not item or item.event_id != ev.id or item.status != "approved":
        raise HTTPException(404, {"error": "not_found"})
    name = (body.displayName or "").strip()[:40]
    text = (body.body or "").strip()[:400]
    if len(name) < 2:
        raise HTTPException(400, {"error": "display_name_required"})
    if len(text) < 1:
        raise HTTPException(400, {"error": "body_required"})
    c = MemoryComment(
        item_id=item.id,
        ticket_id=sess.ticket_id,
        display_name=name,
        body=text,
    )
    db.add(c)
    db.flush()
    write_audit(
        db,
        event_id=ev.id,
        item_id=item.id,
        ticket_id=sess.ticket_id,
        actor="ticket",
        action="comment",
        meta={"displayName": name, "commentId": c.id},
    )
    db.commit()
    db.refresh(c)
    return {
        "ok": True,
        "comment": {
            "id": c.id,
            "displayName": c.display_name,
            "body": c.body,
            "createdAt": _iso(c.created_at),
        },
    }


@router.get("/api/memories/file/{item_id}")
def memories_file(
    item_id: int,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    item = db.get(MemoryItem, item_id)
    if not item:
        raise HTTPException(404, {"error": "not_found"})

    allowed = False
    if item.status == "approved":
        allowed = True
    else:
        # Owner session (same ticket) may preview own pending; never rejected publicly
        token = _bearer_token(creds)
        sess = get_valid_session(db, token) if token else None
        if (
            sess
            and sess.event_id == item.event_id
            and sess.ticket_id == item.ticket_id
            and item.status == "pending"
        ):
            allowed = True

    if not allowed:
        raise HTTPException(404, {"error": "not_found"})

    path = absolute_memory_path(item.stored_name)
    if not path:
        raise HTTPException(404, {"error": "missing_file"})
    return FileResponse(path, media_type=item.mime, filename=f"memory-{item.id}{path.suffix}")
