import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

TEHRAN = ZoneInfo("Asia/Tehran")

from app.models import Event, SiteSetting

FEATURED_KEY = "featured_event_id"


def get_featured_event_id(db: Session) -> int | None:
    row = db.get(SiteSetting, FEATURED_KEY)
    if not row or not row.value.strip():
        return None
    try:
        return int(row.value)
    except ValueError:
        return None


def set_featured_event_id(db: Session, event_id: int) -> None:
    row = db.get(SiteSetting, FEATURED_KEY)
    if row:
        row.value = str(event_id)
    else:
        db.add(SiteSetting(key=FEATURED_KEY, value=str(event_id)))
    db.commit()


def get_featured_event(db: Session) -> Event | None:
    eid = get_featured_event_id(db)
    if not eid:
        return None
    ev = db.get(Event, eid)
    if not ev or ev.status in ("draft", "cancelled"):
        return None
    return ev


def event_to_landing_dict(ev: Event) -> dict:
    try:
        setlist = json.loads(ev.setlist_json or "[]")
    except json.JSONDecodeError:
        setlist = []
    try:
        artists = json.loads(ev.artists_json or "[]")
    except json.JSONDecodeError:
        artists = []
    return {
        "id": ev.id,
        "slug": ev.slug,
        "title": ev.title,
        "episodeNumber": ev.episode_number,
        "description": ev.description,
        "eventAt": event_at_iso(ev.event_at),
        "city": ev.city,
        "venue": ev.venue,
        "hostName": ev.host_name or "",
        "hostVenue": ev.host_venue or "",
        "capacity": ev.capacity,
        "ticketPrice": ev.ticket_price,
        "payment": {
            "cardNumber": ev.payment_card_number,
            "cardHolder": ev.payment_card_holder,
            "bankName": ev.payment_bank_name,
            "instructions": ev.payment_instructions,
        },
        "status": ev.status,
        "salesStatus": ev.sales_status,
        "setlist": setlist,
        "artists": artists,
        "posterUrl": f"/storage/public/{ev.poster_path}" if ev.poster_path else "",
    }


def public_events_query(db: Session):
    return db.scalars(
        select(Event)
        .where(Event.status.not_in(["draft", "cancelled"]))
        .order_by(Event.event_at.desc())
    ).all()


def parse_event_at(iso: str) -> datetime:
    dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TEHRAN)
    return dt.astimezone(timezone.utc)


def event_at_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
