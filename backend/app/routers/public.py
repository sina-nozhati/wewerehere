import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import check_rate_limit
from app.config import ROOT, settings
from app.db import get_db
from app.models import Event, Media, Order, PaymentReceipt, Ticket
from app.services.capacity import capacity_payload, remaining_tickets
from app.services.events import (
    event_at_iso,
    event_to_landing_dict,
    get_featured_event,
    get_featured_event_id,
    public_events_query,
)
from app.services.orders import create_order, status_for_ui
from app.services.phone import normalize_phone, normalize_serial, valid_phone
from app.services.event_display import ticket_venue_from_event
from app.services.jalali_schedule import format_hero_schedule, ticket_city_line
from app.services.tickets import active_rank_map, public_number, verify_ticket_access

router = APIRouter(tags=["public"])

_rate_track: dict[str, list[float]] = {}
_rate_archive: dict[str, list[float]] = {}
_archive_sessions: dict[str, dict] = {}


class OrderCreateBody(BaseModel):
    phone: str
    names: list[str]
    receiptText: str = ""
    receiptImage: dict | None = None
    eventId: int | None = None


class ArchiveAccessBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    eventId: int | None = None
    publicCode: str = Field(alias="publicCode")
    accessToken: str = Field(default="", alias="accessToken")
    serial: str = ""


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(Ticket)) or 0
    from app.services.ticket_render import ticket_png_diagnostics

    return {
        "ok": True,
        "tickets": total,
        "backend": "fastapi",
        "ticketDownload": True,
        "ticketPng": ticket_png_diagnostics(),
    }


@router.get("/api/landing")
def landing(db: Session = Depends(get_db)):
    ev = get_featured_event(db)
    if not ev:
        return {"featured": False, "empty": True, "message": "رویداد اصلی هنوز تنظیم نشده است."}
    payload = event_to_landing_dict(ev)
    payload["capacity"] = capacity_payload(db, ev.id, ev.capacity)
    return {"featured": True, "empty": False, "event": payload}


@router.get("/api/events")
def list_events(db: Session = Depends(get_db)):
    featured_id = get_featured_event_id(db)
    items = []
    for ev in public_events_query(db):
        items.append(
            {
                "id": ev.id,
                "slug": ev.slug,
                "title": ev.title,
                "episodeNumber": ev.episode_number,
                "eventAt": event_at_iso(ev.event_at),
                "city": ev.city,
                "venue": ev.venue,
                "status": ev.status,
                "isFeatured": featured_id is not None and ev.id == featured_id,
                "posterUrl": f"/storage/public/{ev.poster_path}" if ev.poster_path else "",
            }
        )
    return {"events": items}


@router.get("/api/events/{slug}")
def event_detail(slug: str, db: Session = Depends(get_db)):
    ev = db.scalar(select(Event).where(Event.slug == slug))
    if not ev or ev.status in ("draft", "cancelled"):
        raise HTTPException(404, "not found")
    data = event_to_landing_dict(ev)
    data["capacity"] = capacity_payload(db, ev.id, ev.capacity)
    return data


@router.get("/api/capacity")
def capacity_legacy(db: Session = Depends(get_db)):
    ev = get_featured_event(db)
    if not ev:
        return {"capacity": 0, "sold": 0, "pending": 0, "remaining": 0}
    return capacity_payload(db, ev.id, ev.capacity)


@router.get("/api/events/{event_id}/capacity")
def capacity_for_event(event_id: int, db: Session = Depends(get_db)):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, "not found")
    return capacity_payload(db, ev.id, ev.capacity)


@router.get("/api/payment-info")
def payment_info(db: Session = Depends(get_db)):
    ev = get_featured_event(db)
    if not ev:
        return {"cardNumber": "", "cardHolder": "", "bankName": "", "price": 0}
    return {
        "cardNumber": ev.payment_card_number,
        "cardHolder": ev.payment_card_holder,
        "bankName": ev.payment_bank_name,
        "price": ev.ticket_price,
        "eventId": ev.id,
    }


@router.post("/api/orders")
def orders_legacy(body: OrderCreateBody, db: Session = Depends(get_db)):
    ev = get_featured_event(db)
    if not ev:
        raise HTTPException(409, {"error": "فروش بلیت فعال نیست"})
    if body.eventId and body.eventId != ev.id:
        ev = db.get(Event, body.eventId)
        if not ev:
            raise HTTPException(404, "event not found")
    try:
        order = create_order(
            db,
            event_id=ev.id,
            capacity=ev.capacity,
            phone=body.phone,
            names=body.names,
            receipt_text=body.receiptText,
            receipt_image=body.receiptImage,
        )
    except ValueError as e:
        msg = str(e)
        code = 409 if "ظرفیت" in msg or "باقی" in msg else 400
        raise HTTPException(code, {"error": msg})
    return {"orderId": order.id, "status": "pending", "eventId": ev.id}


@router.post("/api/events/{event_id}/orders")
def orders_for_event(event_id: int, body: OrderCreateBody, db: Session = Depends(get_db)):
    ev = db.get(Event, event_id)
    if not ev or ev.sales_status != "open":
        raise HTTPException(409, {"error": "فروش این رویداد باز نیست"})
    try:
        order = create_order(
            db,
            event_id=ev.id,
            capacity=ev.capacity,
            phone=body.phone,
            names=body.names,
            receipt_text=body.receiptText,
            receipt_image=body.receiptImage,
        )
    except ValueError as e:
        msg = str(e)
        code = 409 if "ظرفیت" in msg or "باقی" in msg else 400
        raise HTTPException(code, {"error": msg})
    return {"orderId": order.id, "status": "pending"}


def _ticket_track_payload(t: Ticket, ev: Event | None, rank_map: dict[int, int]) -> dict:
    venue = ticket_venue_from_event(ev)
    sched = format_hero_schedule(
        ev.event_at if ev else None,
        venue=venue,
        city=(ev.city or "") if ev else "",
    )
    number = public_number(t, rank_map)
    if number is None:
        number = t.display_number
    return {
        "number": number,
        "serial": t.public_code,
        "name": t.holder_name,
        "group": t.group_name,
        "eventId": t.event_id,
        "printUrl": f"/api/tickets/{t.id}/download",
        "date": sched.tagline,
        "time": sched.time_hm,
        "venue": venue,
        "city": (ev.city or "") if ev else "",
        "cityLine": ticket_city_line((ev.city or "") if ev else ""),
    }


def _resolve_track_event(db: Session, event_id: int | None) -> Event:
    eid = event_id or get_featured_event_id(db)
    if not eid:
        raise HTTPException(400, {"error": "no featured event configured"})
    ev = db.get(Event, eid)
    if not ev or ev.status in ("draft", "cancelled"):
        raise HTTPException(404, {"error": "event not found"})
    return ev


def _event_track_summary(
    ev: Event,
    featured_id: int | None,
    *,
    include_location: bool = False,
) -> dict:
    out = {
        "id": ev.id,
        "title": ev.title,
        "episodeNumber": ev.episode_number,
        "isFeatured": featured_id is not None and ev.id == featured_id,
    }
    if include_location:
        from app.services.event_location import location_payload_for_track

        loc = location_payload_for_track(ev)
        if loc:
            out["location"] = loc
    return out


def _track_tickets_by_serial(db: Session, serial: str, event_id: int) -> list[dict]:
    tickets = db.scalars(
        select(Ticket)
        .where(
            Ticket.public_code == serial,
            Ticket.status == "active",
            Ticket.event_id == event_id,
        )
        .order_by(Ticket.id.desc())
    ).all()
    events = {
        event.id: event
        for event in db.scalars(
            select(Event).where(Event.id.in_({ticket.event_id for ticket in tickets}))
        ).all()
    } if tickets else {}
    ranks = active_rank_map(db, event_id)
    return [_ticket_track_payload(ticket, events.get(ticket.event_id), ranks) for ticket in tickets]


@router.get("/api/tickets/track")
def track_by_serial(serial: str = Query(""), phone: str = Query(""), db: Session = Depends(get_db)):
    """Lookup active tickets by 4-digit serial and/or phone."""
    check_rate_limit(_rate_track, serial or phone or "x", 30, 60.0)
    phone_n = normalize_phone(phone) if phone else ""
    raw = normalize_serial(serial)
    tickets_out: list[dict] = []
    rank_by_event: dict[int, dict[int, int]] = {}
    if re.fullmatch(r"\d{4}", raw):
        featured_id = get_featured_event_id(db)
        if featured_id:
            tickets_out.extend(_track_tickets_by_serial(db, raw, featured_id))
    if valid_phone(phone_n):
        for t in db.scalars(
            select(Ticket).where(Ticket.phone == phone_n, Ticket.status == "active").order_by(Ticket.id.desc())
        ).all():
            if t.event_id not in rank_by_event:
                rank_by_event[t.event_id] = active_rank_map(db, t.event_id)
            ev_row = db.get(Event, t.event_id)
            payload = _ticket_track_payload(t, ev_row, rank_by_event[t.event_id])
            if not any(x["serial"] == payload["serial"] and x["eventId"] == payload["eventId"] for x in tickets_out):
                tickets_out.append(payload)
    if not tickets_out and not valid_phone(phone_n) and not re.fullmatch(r"\d{4}", raw):
        raise HTTPException(400, {"error": "phone or serial required"})
    return {"tickets": tickets_out}


@router.get("/api/tickets/{ticket_id}/download")
def download_ticket_png(
    ticket_id: int,
    phone: str = Query(""),
    serial: str = Query(""),
    inline: bool = Query(False),
    format: str = Query("png", alias="format"),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response

    from app.services.ticket_render import render_ticket_bytes

    t = db.get(Ticket, ticket_id)
    if not t or t.status != "active":
        raise HTTPException(404, "not found")
    phone_n = normalize_phone(phone) if phone else ""
    raw = normalize_serial(serial)
    if valid_phone(phone_n) and t.phone == phone_n:
        pass
    elif raw == t.public_code:
        pass
    else:
        raise HTTPException(403, "forbidden")
    ev = db.get(Event, t.event_id)
    ranks = active_rank_map(db, t.event_id)
    ticket_number = public_number(t, ranks) or t.display_number
    out_fmt = (format or "png").lower().strip()
    if out_fmt == "svg":
        raise HTTPException(400, {"error": "svg_not_available", "message": "Only PNG download is supported"})
    if out_fmt not in ("png", "pdf"):
        raise HTTPException(400, {"error": "invalid format"})
    from app.services.ticket_render import TicketRenderError

    try:
        body, media_type, ext = render_ticket_bytes(
            t.group_name,
            t.holder_name,
            t.public_code,
            ticket_number,
            event_at=ev.event_at if ev else None,
            venue=ticket_venue_from_event(ev),
            city=ev.city if ev else "",
            output_format=out_fmt,
            prefer_png=True,
            allow_svg_export=False,
        )
    except TicketRenderError as e:
        raise HTTPException(
            503,
            {
                "error": "ticket_png_unavailable",
                "message": str(e),
                "detail": str(e),
            },
        )
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="ticket-{t.public_code}.{ext}"'
                if inline
                else f'attachment; filename="ticket-{t.public_code}.{ext}"'
            ),
            # Ticket art is rendered on each request; avoid stale A/B/W after deploy.
            "Cache-Control": "no-store",
        },
    )


def _track_by_phone(db: Session, ev: Event, phone_n: str, featured_id: int | None) -> dict:
    orders = db.scalars(
        select(Order).where(Order.phone == phone_n, Order.event_id == ev.id).order_by(Order.id.desc())
    ).all()
    order_payload = []
    for o in orders:
        names = json.loads(o.names_json or "[]")
        receipt = o.receipt
        receipt_text = receipt.text if receipt else ""
        receipt_image_url = ""
        if receipt and receipt.file_path:
            receipt_image_url = f"/api/orders/receipt-image?orderId={o.id}&phone={phone_n}"
        order_payload.append(
            {
                "id": o.id,
                "eventId": o.event_id,
                "names": names,
                "status": status_for_ui(o.status),
                "adminNote": o.admin_note or "",
                "createdAt": o.created_at.isoformat() if o.created_at else "",
                "reviewedAt": o.reviewed_at.isoformat() if o.reviewed_at else None,
                "receiptText": receipt_text,
                "receiptImageUrl": receipt_image_url,
                "hasReceiptText": bool(receipt_text),
                "hasReceiptImage": bool(receipt and receipt.file_path),
            }
        )

    tickets = db.scalars(
        select(Ticket)
        .where(Ticket.phone == phone_n, Ticket.status == "active", Ticket.event_id == ev.id)
        .order_by(Ticket.id.desc())
    ).all()
    ranks = active_rank_map(db, ev.id)
    ticket_payload = [_ticket_track_payload(t, ev, ranks) for t in tickets]
    return {
        "orders": order_payload,
        "tickets": ticket_payload,
        "event": _event_track_summary(ev, featured_id, include_location=bool(ticket_payload)),
    }


@router.get("/api/orders/track")
def track_orders(
    phone: str = Query(""),
    serial: str = Query(""),
    eventId: int | None = Query(None),
    request: Request = None,
    db: Session = Depends(get_db),
):
    ip = "unknown"
    featured_id = get_featured_event_id(db)
    ev = _resolve_track_event(db, eventId)
    phone_n = normalize_phone(phone) if phone else ""
    raw = normalize_serial(serial)
    has_serial = bool(raw)
    has_phone = bool(phone_n)

    if has_serial:
        if not re.fullmatch(r"\d{4}", raw):
            raise HTTPException(400, {"error": "invalid serial"})
        check_rate_limit(_rate_track, f"{ip}:serial:{raw}", 30, 60.0)
        tickets = _track_tickets_by_serial(db, raw, ev.id)
        if tickets:
            return {
                "orders": [],
                "tickets": tickets,
                "event": _event_track_summary(ev, featured_id, include_location=True),
            }
        # Wrong/unknown serial but valid phone → fall back to phone lookup
        if has_phone:
            if not valid_phone(phone_n):
                raise HTTPException(400, {"error": "invalid phone"})
            check_rate_limit(_rate_track, f"{ip}:{phone_n}", 30, 60.0)
            return _track_by_phone(db, ev, phone_n, featured_id)
        return {
            "orders": [],
            "tickets": [],
            "event": _event_track_summary(ev, featured_id, include_location=False),
        }

    check_rate_limit(_rate_track, f"{ip}:{phone_n}", 30, 60.0)
    if not valid_phone(phone_n):
        raise HTTPException(400, {"error": "invalid phone"})
    return _track_by_phone(db, ev, phone_n, featured_id)


@router.get("/api/ticket")
def ticket_legacy(serial: str = Query(""), db: Session = Depends(get_db)):
    """Legacy serial lookup — scoped to featured event; prefer archive/access."""
    ev = get_featured_event(db)
    if not ev:
        return {"found": False}
    raw = normalize_serial(serial)
    if not re.fullmatch(r"\d{4}", raw):
        raise HTTPException(400, {"error": "invalid serial"})
    ticket = db.scalar(
        select(Ticket).where(Ticket.event_id == ev.id, Ticket.public_code == raw, Ticket.status == "active")
    )
    if not ticket:
        return {"found": False}
    import secrets

    session = secrets.token_urlsafe(24)
    _archive_sessions[session] = {
        "event_id": ev.id,
        "ticket_id": ticket.id,
        "exp": datetime.now(timezone.utc).timestamp() + 3600,
    }
    media = _archive_media_list(db, ev.id, session=session)
    ranks = active_rank_map(db, ev.id)
    number = public_number(ticket, ranks) or ticket.display_number
    return {
        "found": True,
        "ticket": {
            "number": number,
            "serial": ticket.public_code,
            "name": ticket.holder_name,
            "group": ticket.group_name,
        },
        "media": media,
    }


def _archive_media_list(db: Session, event_id: int, session: str = "") -> list[dict]:
    rows = db.scalars(
        select(Media).where(Media.event_id == event_id, Media.access_level == "archive_private").order_by(Media.id.desc())
    ).all()
    out = []
    for m in rows:
        out.append(
            {
                "id": m.id,
                "url": f"/api/archive/media/{m.id}" + (f"?session={session}" if session else ""),
                "mime": m.mime,
                "caption": m.caption,
                "original_name": m.original_name,
            }
        )
    return out


@router.post("/api/archive/access")
def archive_access(body: ArchiveAccessBody, db: Session = Depends(get_db)):
    check_rate_limit(_rate_archive, body.publicCode or body.serial, 20, 60.0)
    ev = get_featured_event(db)
    event_id = body.eventId or (ev.id if ev else None)
    if not event_id:
        raise HTTPException(400, {"error": "event required"})
    code = normalize_serial(body.publicCode or body.serial)
    if not re.fullmatch(r"\d{4}", code):
        raise HTTPException(400, {"error": "invalid serial"})
    token = body.accessToken
    ticket = None
    if token:
        ticket = verify_ticket_access(db, event_id, code, token)
    else:
        ticket = db.scalar(
            select(Ticket).where(
                Ticket.event_id == event_id, Ticket.public_code == code, Ticket.status == "active"
            )
        )
    if not ticket:
        return {"ok": False, "found": False}
    import secrets

    session = secrets.token_urlsafe(24)
    _archive_sessions[session] = {"event_id": event_id, "ticket_id": ticket.id, "exp": datetime.now(timezone.utc).timestamp() + 3600}
    ranks = active_rank_map(db, event_id)
    number = public_number(ticket, ranks) or ticket.display_number
    return {
        "ok": True,
        "found": True,
        "session": session,
        "ticket": {
            "number": number,
            "serial": ticket.public_code,
            "name": ticket.holder_name,
            "group": ticket.group_name,
        },
        "media": _archive_media_list(db, event_id, session=session),
    }


@router.get("/api/archive/media/{media_id}")
def archive_media_file(media_id: int, session: str = Query(""), db: Session = Depends(get_db)):
    sess = _archive_sessions.get(session)
    if not sess or sess["exp"] < datetime.now(timezone.utc).timestamp():
        raise HTTPException(403, "forbidden")
    m = db.get(Media, media_id)
    if not m or m.event_id != sess["event_id"] or m.access_level != "archive_private":
        raise HTTPException(404, "not found")
    return _file_response(m)


def _file_response(m: Media):
    from fastapi.responses import FileResponse

    path = _resolve_media_path(m.filename)
    if not path.is_file():
        raise HTTPException(404, "file missing")
    return FileResponse(path, media_type=m.mime)


def _resolve_media_path(filename: str) -> Path:
    if filename.startswith("legacy/"):
        return settings.legacy_uploads / filename.replace("legacy/", "", 1)
    p = settings.archive_dir / filename
    if p.is_file():
        return p
    legacy = settings.legacy_uploads / filename
    if legacy.is_file():
        return legacy
    return p


@router.get("/api/orders/receipt-image")
def order_receipt_image(orderId: int = Query(...), phone: str = Query(""), db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse

    from app.storage_paths import receipt_path as _receipt_path

    phone_n = normalize_phone(phone)
    if not valid_phone(phone_n):
        raise HTTPException(400, {"error": "invalid phone"})
    order = db.get(Order, orderId)
    if not order or order.phone != phone_n:
        raise HTTPException(404, "not found")
    receipt = order.receipt
    if not receipt or not receipt.file_path:
        raise HTTPException(404, "not found")
    path = _receipt_path(receipt.file_path)
    if not path.is_file():
        raise HTTPException(404, "file missing")
    return FileResponse(path)


@router.post("/api/register")
def register_removed():
    raise HTTPException(410, {"error": "این مسیر غیرفعال شده است. از فرم ثبت‌نام استفاده کنید."})
