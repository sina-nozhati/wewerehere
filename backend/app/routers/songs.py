"""Public & attendee song suggestions and contest winner song selection endpoints."""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Ticket
from app.services.memory_gate import get_valid_session, resolve_event_by_slug
from app.services.song_service import (
    add_song_suggestion,
    check_winner_eligibility,
    get_event_winner_song,
    list_song_suggestions,
    set_winner_song_pick,
    vote_song_suggestion,
)

router = APIRouter(tags=["songs"])
_bearer = HTTPBearer(auto_error=False)


class WinnerPickBody(BaseModel):
    title: str
    artist: str
    note: str = ""
    code: str | None = None
    serial: str | None = None


class SuggestSongBody(BaseModel):
    title: str
    artist: str
    note: str = ""
    suggestedByName: str = ""
    code: str | None = None


class VoteBody(BaseModel):
    voterId: str | None = None
    code: str | None = None


def _bearer_token(creds: HTTPAuthorizationCredentials | None) -> str | None:
    return creds.credentials if creds else None


def _resolve_caller_ticket(
    db: Session,
    event_id: int,
    session_token: str | None = None,
    code_or_serial: str | None = None,
) -> Ticket | None:
    """Resolve ticket from session token or 4-digit code."""
    if session_token:
        sess = get_valid_session(db, session_token)
        if sess:
            ticket = db.get(Ticket, sess.ticket_id)
            if ticket and ticket.status == "active":
                return ticket

    if code_or_serial:
        clean_code = re.sub(r"\D", "", str(code_or_serial)).zfill(4)[-4:]
        # Prioritize matching ticket in this event first
        ticket = db.scalars(
            select(Ticket).where(
                Ticket.event_id == event_id,
                Ticket.public_code == clean_code,
                Ticket.status == "active",
            )
        ).first()
        if ticket:
            return ticket

        # Fall back to matching active ticket in any event (e.g. previous event)
        ticket = db.scalars(
            select(Ticket).where(
                Ticket.public_code == clean_code,
                Ticket.status == "active",
            )
        ).first()
        if ticket:
            return ticket

    return None


def _resolve_voter_id(
    request: Request,
    ticket: Ticket | None = None,
    client_voter_id: str | None = None,
) -> str:
    if ticket:
        return f"ticket:{ticket.id}"
    if client_voter_id and len(client_voter_id.strip()) >= 4:
        return f"guest:{client_voter_id.strip()[:64]}"
    client_ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")[:60]
    raw = f"{client_ip}:{ua}"
    return f"anon:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


@router.get("/api/events/{slug}/songs/winner-pick")
def get_winner_pick(
    slug: str,
    db: Session = Depends(get_db),
):
    """Public endpoint: returns the memory contest winner's chosen song for the event."""
    ev = resolve_event_by_slug(db, slug)
    winner_song = get_event_winner_song(db, ev.id)
    return {
        "ok": True,
        "event": {"id": ev.id, "slug": ev.slug, "title": ev.title},
        "winnerSong": winner_song,
    }


@router.get("/api/events/{slug}/songs/status")
def get_winner_status(
    slug: str,
    code: str | None = Query(None),
    serial: str | None = Query(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    authorization: Annotated[str | None, Header()] = None,
):
    """Check if the caller is the winner of the previous event's memory contest."""
    ev = resolve_event_by_slug(db, slug)
    session_token = _bearer_token(creds) or token
    if not session_token and authorization and authorization.lower().startswith("bearer "):
        session_token = authorization.split(" ", 1)[1].strip()

    ticket = _resolve_caller_ticket(db, ev.id, session_token=session_token, code_or_serial=code or serial)
    ticket_code = ticket.public_code if ticket else (code or serial)
    ticket_id = ticket.id if ticket else None

    eligibility = check_winner_eligibility(
        db,
        current_event_id=ev.id,
        ticket_public_code=ticket_code,
        ticket_id=ticket_id,
    )

    return {
        "ok": True,
        "event": {"id": ev.id, "slug": ev.slug, "title": ev.title},
        "isWinnerEligible": eligibility["isWinnerEligible"],
        "isWinner": eligibility["isWinner"],
        "winnerScope": eligibility.get("winnerScope"),
        "winnerName": eligibility.get("winnerName"),
        "winnerCode": eligibility.get("winnerCode"),
        "winnerEvent": eligibility.get("winnerEvent"),
        "previousEvent": eligibility.get("previousEvent"),
        "likesCount": eligibility.get("likesCount"),
        "winningMemory": eligibility.get("winningMemory"),
        "alreadyPicked": eligibility.get("alreadyPicked", False),
        "currentPick": eligibility.get("currentPick"),
        "winnerSong": get_event_winner_song(db, ev.id),
    }


@router.post("/api/events/{slug}/songs/winner-pick")
def set_winner_pick(
    slug: str,
    body: WinnerPickBody,
    code: str | None = Query(None),
    serial: str | None = Query(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    authorization: Annotated[str | None, Header()] = None,
):
    """Submit the winner's chosen song. Only the contest winner can call this."""
    ev = resolve_event_by_slug(db, slug)
    session_token = _bearer_token(creds) or token
    if not session_token and authorization and authorization.lower().startswith("bearer "):
        session_token = authorization.split(" ", 1)[1].strip()

    candidate_code = body.code or body.serial or code or serial
    ticket = _resolve_caller_ticket(db, ev.id, session_token=session_token, code_or_serial=candidate_code)
    ticket_code = ticket.public_code if ticket else candidate_code
    ticket_id = ticket.id if ticket else None

    eligibility = check_winner_eligibility(
        db,
        current_event_id=ev.id,
        ticket_public_code=ticket_code,
        ticket_id=ticket_id,
    )

    if not eligibility.get("isWinnerEligible"):
        raise HTTPException(
            403,
            detail={
                "error": "not_winner",
                "message": "تنها برنده مسابقه خاطرات مجاز به انتخاب قطعه است.",
            },
        )

    try:
        winner_ev_info = eligibility.get("winnerEvent") or eligibility.get("previousEvent")
        target_winner_ev_id = winner_ev_info.get("id") if winner_ev_info else None
        song = set_winner_song_pick(
            db,
            current_event_id=ev.id,
            ticket_id=eligibility["winnerTicketId"],
            title=body.title,
            artist=body.artist,
            note=body.note,
            winner_event_id=target_winner_ev_id,
        )
        return {
            "ok": True,
            "winnerSong": song,
            "message": "قطعه انتخابی شما با موفقیت برای اجرا در این رویداد ثبت شد!",
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "invalid_input", "message": str(e)})


@router.get("/api/events/{slug}/songs/suggestions")
def get_song_suggestions(
    slug: str,
    voterId: str | None = Query(None),
    code: str | None = Query(None),
    serial: str | None = Query(None),
    token: str | None = Query(None),
    request: Request = None,
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    """List active song suggestions for the band rehearsal/practice list."""
    ev = resolve_event_by_slug(db, slug)
    session_token = _bearer_token(creds) or token
    ticket = _resolve_caller_ticket(db, ev.id, session_token=session_token, code_or_serial=code or serial)
    voter_id = _resolve_voter_id(request, ticket=ticket, client_voter_id=voterId)

    items = list_song_suggestions(db, ev.id, voter_identifier=voter_id)
    return {
        "ok": True,
        "event": {"id": ev.id, "slug": ev.slug, "title": ev.title},
        "count": len(items),
        "items": items,
    }


@router.post("/api/events/{slug}/songs/suggest")
def create_song_suggestion(
    slug: str,
    body: SuggestSongBody,
    token: str | None = Query(None),
    code: str | None = Query(None),
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    """Add a song suggestion to the band's practice list."""
    ev = resolve_event_by_slug(db, slug)
    session_token = _bearer_token(creds) or token
    ticket = _resolve_caller_ticket(db, ev.id, session_token=session_token, code_or_serial=body.code or code)

    try:
        item = add_song_suggestion(
            db,
            event_id=ev.id,
            title=body.title,
            artist=body.artist,
            note=body.note,
            suggested_by_name=body.suggestedByName,
            ticket_id=ticket.id if ticket else None,
        )
        return {
            "ok": True,
            "suggestion": item,
            "message": "پیشنهاد شما با موفقیت برای تمرین گروه ثبت شد.",
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "invalid_input", "message": str(e)})


@router.post("/api/events/{slug}/songs/suggestions/{suggestion_id}/vote")
def toggle_song_vote(
    slug: str,
    suggestion_id: int,
    request: Request,
    body: VoteBody | None = None,
    voterId: str | None = Query(None),
    code: str | None = Query(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
):
    """Toggle a vote on a song suggestion."""
    ev = resolve_event_by_slug(db, slug)
    client_voter_id = (body.voterId if body else None) or voterId
    candidate_code = (body.code if body else None) or code
    session_token = _bearer_token(creds) or token

    ticket = _resolve_caller_ticket(db, ev.id, session_token=session_token, code_or_serial=candidate_code)
    voter_id = _resolve_voter_id(request, ticket=ticket, client_voter_id=client_voter_id)

    try:
        res = vote_song_suggestion(
            db,
            suggestion_id=suggestion_id,
            voter_identifier=voter_id,
            ticket_id=ticket.id if ticket else None,
        )
        return res
    except ValueError as e:
        raise HTTPException(404, detail={"error": "not_found", "message": str(e)})
