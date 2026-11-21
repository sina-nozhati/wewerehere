"""Song suggestions and memory contest winner song service."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Event, MemoryItem, MemoryLike, SongSuggestion, SongVote, Ticket, utcnow


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _song_to_dict(item: SongSuggestion, winner_event_title: str = "") -> dict[str, Any]:
    return {
        "id": item.id,
        "eventId": item.event_id,
        "title": item.title,
        "artist": item.artist,
        "note": item.note or "",
        "suggestedByName": item.suggested_by_name,
        "ticketId": item.ticket_id,
        "ticketPublicCode": item.ticket.public_code if item.ticket else None,
        "isWinnerPick": item.is_winner_pick,
        "winnerEventId": item.winner_event_id,
        "winnerEventTitle": winner_event_title,
        "status": item.status,
        "createdAt": _iso(item.created_at),
        "updatedAt": _iso(item.updated_at),
    }


def get_previous_event(db: Session, event_id: int) -> Event | None:
    """Find the event immediately prior to event_id.

    Prioritizes event_id - 1, then falls back to highest ID < event_id,
    or chronological order if timestamps are available.
    """
    # 1. Direct sequential predecessor (event_id - 1)
    if event_id > 1:
        exact_prev = db.get(Event, event_id - 1)
        if exact_prev:
            return exact_prev

    # 2. Predecessor by ID
    prev_by_id = db.scalars(
        select(Event)
        .where(Event.id < event_id)
        .order_by(Event.id.desc())
    ).first()
    if prev_by_id:
        return prev_by_id

    # 3. Fallback by event_at if current event exists
    curr = db.get(Event, event_id)
    if curr and curr.event_at:
        return db.scalars(
            select(Event)
            .where(Event.event_at < curr.event_at, Event.id != event_id)
            .order_by(Event.event_at.desc())
        ).first()

    return None


def get_event_memory_winner(db: Session, event_id: int) -> dict[str, Any] | None:
    """Find the approved MemoryItem with the highest like count for event_id.

    Returns the winner Ticket, MemoryItem info, and like count, or None if no valid approved memories exist.
    """
    # Query approved memory items that have a valid linked ticket
    approved_items = db.scalars(
        select(MemoryItem)
        .where(
            MemoryItem.event_id == event_id,
            MemoryItem.status == "approved",
            MemoryItem.ticket_id.isnot(None),
        )
    ).all()

    if not approved_items:
        return None

    item_ids = [m.id for m in approved_items]
    likes_map = dict(
        db.execute(
            select(MemoryLike.item_id, func.count(MemoryLike.id))
            .where(MemoryLike.item_id.in_(item_ids))
            .group_by(MemoryLike.item_id)
        ).all()
    )

    # Sort by likeCount descending, then created_at ascending (earlier submission breaks tie), then ID
    ranked = sorted(
        approved_items,
        key=lambda m: (-likes_map.get(m.id, 0), m.created_at or datetime.max.replace(tzinfo=timezone.utc), m.id),
    )

    for top_item in ranked:
        ticket = db.get(Ticket, top_item.ticket_id)
        if ticket and ticket.status == "active":
            return {
                "ticket": {
                    "id": ticket.id,
                    "public_code": ticket.public_code,
                    "holder_name": ticket.holder_name,
                },
                "memory": {
                    "id": top_item.id,
                    "title": top_item.title or "",
                    "stored_name": top_item.stored_name,
                    "media_kind": top_item.media_kind,
                },
                "likes_count": likes_map.get(top_item.id, 0),
                "event_id": event_id,
            }

    return None


def get_event_winner_song(db: Session, event_id: int) -> dict[str, Any] | None:
    """Get the definitive winner song chosen for an event, or None."""
    item = db.scalars(
        select(SongSuggestion)
        .where(
            SongSuggestion.event_id == event_id,
            SongSuggestion.is_winner_pick == True,
            SongSuggestion.status != "archived",
        )
    ).first()

    if not item:
        return None

    winner_event_title = ""
    if item.winner_event_id:
        prev_ev = db.get(Event, item.winner_event_id)
        if prev_ev:
            winner_event_title = prev_ev.title

    return _song_to_dict(item, winner_event_title)


def check_winner_eligibility(
    db: Session,
    current_event_id: int,
    ticket_public_code: str | None = None,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    """Check if the given ticket / code belongs to the winner of the previous event."""
    prev_event = get_previous_event(db, current_event_id)
    current_pick = get_event_winner_song(db, current_event_id)

    if not prev_event:
        return {
            "isWinnerEligible": False,
            "isWinner": False,
            "winnerTicketId": None,
            "winnerCode": None,
            "winnerName": None,
            "previousEvent": None,
            "alreadyPicked": current_pick is not None,
            "currentPick": current_pick,
            "reason": "no_previous_event",
        }

    winner = get_event_memory_winner(db, prev_event.id)
    prev_info = {"id": prev_event.id, "title": prev_event.title, "slug": prev_event.slug}

    if not winner:
        return {
            "isWinnerEligible": False,
            "isWinner": False,
            "winnerTicketId": None,
            "winnerCode": None,
            "winnerName": None,
            "previousEvent": prev_info,
            "alreadyPicked": current_pick is not None,
            "currentPick": current_pick,
            "reason": "no_winner_in_previous_event",
        }

    winner_ticket = winner["ticket"]
    is_match = False

    if ticket_id and ticket_id == winner_ticket["id"]:
        is_match = True

    if ticket_public_code:
        raw_code = ticket_public_code.strip()
        clean_code = re.sub(r"\D", "", raw_code).zfill(4)[-4:]
        if raw_code == winner_ticket["public_code"] or clean_code == winner_ticket["public_code"]:
            is_match = True

    if is_match:
        return {
            "isWinnerEligible": True,
            "isWinner": True,
            "winnerTicketId": winner_ticket["id"],
            "winnerCode": winner_ticket["public_code"],
            "winnerName": winner_ticket["holder_name"],
            "previousEvent": prev_info,
            "likesCount": winner["likes_count"],
            "winningMemory": winner["memory"],
            "alreadyPicked": current_pick is not None,
            "currentPick": current_pick,
        }

    return {
        "isWinnerEligible": False,
        "isWinner": False,
        "winnerTicketId": None,
        "winnerCode": None,
        "winnerName": None,
        "previousEvent": prev_info,
        "alreadyPicked": current_pick is not None,
        "currentPick": current_pick,
        "reason": "code_does_not_match_winner",
    }


def set_winner_song_pick(
    db: Session,
    current_event_id: int,
    ticket_id: int,
    title: str,
    artist: str,
    note: str = "",
) -> dict[str, Any]:
    """Create or update the winner's chosen song for current_event_id."""
    clean_title = (title or "").strip()
    clean_artist = (artist or "").strip()
    clean_note = (note or "").strip()

    if not clean_title:
        raise ValueError("عنوان قطعه الزامی است.")
    if not clean_artist:
        raise ValueError("نام خواننده یا گروه الزامی است.")

    ticket = db.get(Ticket, ticket_id)
    holder_name = ticket.holder_name if ticket else "برنده مسابقه خاطرات"

    prev_event = get_previous_event(db, current_event_id)
    prev_id = prev_event.id if prev_event else None
    prev_title = prev_event.title if prev_event else ""

    existing = db.scalars(
        select(SongSuggestion)
        .where(
            SongSuggestion.event_id == current_event_id,
            SongSuggestion.is_winner_pick == True,
        )
    ).first()

    if existing:
        existing.ticket_id = ticket_id
        existing.suggested_by_name = holder_name
        existing.title = clean_title[:200]
        existing.artist = clean_artist[:200]
        existing.note = clean_note[:500]
        existing.winner_event_id = prev_id
        existing.status = "active"
        existing.updated_at = utcnow()
        db.commit()
        db.refresh(existing)
        return _song_to_dict(existing, prev_title)

    item = SongSuggestion(
        event_id=current_event_id,
        ticket_id=ticket_id,
        suggested_by_name=holder_name[:200],
        title=clean_title[:200],
        artist=clean_artist[:200],
        note=clean_note[:500],
        is_winner_pick=True,
        winner_event_id=prev_id,
        status="active",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _song_to_dict(item, prev_title)


def add_song_suggestion(
    db: Session,
    event_id: int,
    title: str,
    artist: str,
    note: str = "",
    suggested_by_name: str = "",
    ticket_id: int | None = None,
) -> dict[str, Any]:
    """Add an attendee song suggestion to the band's rehearsal/practice list."""
    clean_title = (title or "").strip()
    clean_artist = (artist or "").strip()
    clean_note = (note or "").strip()

    if not clean_title:
        raise ValueError("عنوان قطعه الزامی است.")
    if not clean_artist:
        raise ValueError("نام خواننده یا گروه الزامی است.")

    name = (suggested_by_name or "").strip()
    if not name and ticket_id:
        t = db.get(Ticket, ticket_id)
        if t:
            name = t.holder_name
    if not name:
        name = "مهمان رویداد"

    item = SongSuggestion(
        event_id=event_id,
        ticket_id=ticket_id,
        suggested_by_name=name[:200],
        title=clean_title[:200],
        artist=clean_artist[:200],
        note=clean_note[:500],
        is_winner_pick=False,
        status="active",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "eventId": item.event_id,
        "title": item.title,
        "artist": item.artist,
        "note": item.note,
        "suggestedByName": item.suggested_by_name,
        "status": item.status,
        "voteCount": 0,
        "votedByMe": False,
        "createdAt": _iso(item.created_at),
    }


def list_song_suggestions(
    db: Session,
    event_id: int,
    voter_identifier: str | None = None,
) -> list[dict[str, Any]]:
    """List active song suggestions for the rehearsal practice list with vote counts."""
    rows = db.scalars(
        select(SongSuggestion)
        .where(
            SongSuggestion.event_id == event_id,
            SongSuggestion.is_winner_pick == False,
            SongSuggestion.status == "active",
        )
    ).all()

    if not rows:
        return []

    ids = [s.id for s in rows]
    vote_counts = dict(
        db.execute(
            select(SongVote.suggestion_id, func.count(SongVote.id))
            .where(SongVote.suggestion_id.in_(ids))
            .group_by(SongVote.suggestion_id)
        ).all()
    )

    voted_ids: set[int] = set()
    if voter_identifier:
        voted_ids = set(
            db.scalars(
                select(SongVote.suggestion_id)
                .where(
                    SongVote.suggestion_id.in_(ids),
                    SongVote.voter_identifier == voter_identifier,
                )
            ).all()
        )

    results = []
    for s in rows:
        results.append(
            {
                "id": s.id,
                "eventId": s.event_id,
                "title": s.title,
                "artist": s.artist,
                "note": s.note or "",
                "suggestedByName": s.suggested_by_name,
                "status": s.status,
                "voteCount": vote_counts.get(s.id, 0),
                "votedByMe": s.id in voted_ids,
                "createdAt": _iso(s.created_at),
            }
        )

    # Sort primarily by voteCount descending, then createdAt descending (stable sort)
    results.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
    results.sort(key=lambda r: r["voteCount"], reverse=True)
    return results


def vote_song_suggestion(
    db: Session,
    suggestion_id: int,
    voter_identifier: str,
    ticket_id: int | None = None,
) -> dict[str, Any]:
    """Toggle a vote on a song suggestion for the given voter_identifier."""
    suggestion = db.get(SongSuggestion, suggestion_id)
    if not suggestion or suggestion.is_winner_pick or suggestion.status != "active":
        raise ValueError("پیشنهاد مورد نظر یافت نشد.")

    existing_vote = db.scalars(
        select(SongVote)
        .where(
            SongVote.suggestion_id == suggestion_id,
            SongVote.voter_identifier == voter_identifier,
        )
    ).first()

    if existing_vote:
        db.delete(existing_vote)
        db.commit()
        voted = False
    else:
        new_vote = SongVote(
            suggestion_id=suggestion_id,
            voter_identifier=voter_identifier,
            ticket_id=ticket_id,
        )
        db.add(new_vote)
        db.commit()
        voted = True

    count = db.scalar(
        select(func.count(SongVote.id)).where(SongVote.suggestion_id == suggestion_id)
    ) or 0

    return {
        "ok": True,
        "voted": voted,
        "voteCount": count,
        "suggestionId": suggestion_id,
    }
