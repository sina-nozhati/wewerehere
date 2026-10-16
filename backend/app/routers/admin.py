import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import check_rate_limit, create_session, require_admin, revoke_session, verify_admin_password
from app.config import settings
from app.storage_paths import receipt_path as _receipt_path
from app.db import get_db
from app.models import Event, Media, Order, PaymentReceipt, SiteSetting, SupportContact, SupportMessage, SupportTicket, Ticket
from app.services.events import FEATURED_KEY, event_at_iso, get_featured_event_id, parse_event_at, set_featured_event_id
from app.services.orders import approve_order, reject_order
from app.services import notify as notify_svc
from app.services.notify import list_admin_presets, notify_tickets_issued, send_admin_preset
from app.services.phone import normalize_phone, valid_phone
from app.services.event_display import ticket_venue_from_event
from app.services.ticket_render import TicketRenderError, render_ticket_bytes
from app.services.support_contacts import contact_display_name
from app.services.tickets import active_rank_map, group_for_code, issue_ticket, public_number, unique_public_code

_ACTIVE_SUPPORT = frozenset({"open", "waiting_admin", "waiting_user"})

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _iso_utc(dt: datetime | None) -> str | None:
    """Always emit timezone-aware UTC ISO so JS Date parses correctly."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class LoginBody(BaseModel):
    password: str


class TicketBody(BaseModel):
    name: str = ""
    phone: str = ""
    serial: str = ""
    group: str = ""
    eventId: int | None = None


class TicketUpdateBody(TicketBody):
    pass


class SettingsBody(BaseModel):
    card_number: str | None = None
    card_holder: str | None = None
    bank_name: str | None = None
    ticket_price: str | None = None
    eventId: int | None = None


class MediaUploadBody(BaseModel):
    filename: str
    mime: str
    data: str
    caption: str = ""
    eventId: int | None = None


class MediaCaptionBody(BaseModel):
    caption: str = ""


class RejectBody(BaseModel):
    note: str = ""


class SmsSendBody(BaseModel):
    phone: str = ""
    presetId: str = ""
    value: str = ""


_sms_rate: dict[str, list[float]] = {}


class EventBody(BaseModel):
    slug: str
    title: str
    episodeNumber: int | None = None
    description: str = ""
    eventAt: str
    city: str = ""
    venue: str = ""
    hostName: str = ""
    hostVenue: str = ""
    locationLat: float | None = None
    locationLng: float | None = None
    locationLabel: str = ""
    locationPublished: bool = False
    capacity: int = 50
    ticketPrice: int = 0
    paymentCardNumber: str = ""
    paymentCardHolder: str = ""
    paymentBankName: str = ""
    paymentInstructions: str = ""
    status: str = "draft"
    salesStatus: str = "closed"
    setlistJson: str = "[]"
    artistsJson: str = "[]"


class SupportReplyBody(BaseModel):
    body: str


MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


def _default_event_id(db: Session) -> int:
    eid = get_featured_event_id(db)
    if eid:
        return eid
    ev = db.scalar(select(Event).order_by(Event.id.asc()).limit(1))
    if not ev:
        raise HTTPException(409, "no events")
    return ev.id


@router.post("/login")
def login(body: LoginBody):
    if not verify_admin_password(body.password):
        raise HTTPException(401, {"error": "رمز عبور اشتباه است"})
    return {"token": create_session()}


@router.post("/logout")
def logout(token: str = Depends(require_admin)):
    revoke_session(token)
    return {"ok": True}


def _admin_event_row(e: Event, featured: int | None) -> dict:
    return {
        "id": e.id,
        "slug": e.slug,
        "title": e.title,
        "episodeNumber": e.episode_number,
        "description": e.description or "",
        "eventAt": event_at_iso(e.event_at),
        "city": e.city or "",
        "venue": e.venue or "",
        "hostName": e.host_name or "",
        "hostVenue": e.host_venue or "",
        "locationLat": e.location_lat,
        "locationLng": e.location_lng,
        "locationLabel": e.location_label or "",
        "locationPublished": bool(e.location_published),
        "status": e.status,
        "salesStatus": e.sales_status,
        "capacity": e.capacity,
        "ticketPrice": e.ticket_price,
        "paymentCardNumber": e.payment_card_number or "",
        "paymentCardHolder": e.payment_card_holder or "",
        "paymentBankName": e.payment_bank_name or "",
        "paymentInstructions": e.payment_instructions or "",
        "setlistJson": e.setlist_json or "[]",
        "artistsJson": e.artists_json or "[]",
        "isFeatured": e.id == featured,
    }


@router.get("/events")
def admin_list_events(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    rows = db.scalars(select(Event).order_by(Event.event_at.desc())).all()
    featured = get_featured_event_id(db)
    return {"events": [_admin_event_row(e, featured) for e in rows]}


def _apply_event_location(ev: Event, body: EventBody) -> None:
    from app.services.event_location import apply_location_fields

    try:
        apply_location_fields(
            ev,
            lat=body.locationLat,
            lng=body.locationLng,
            label=body.locationLabel,
            published=body.locationPublished,
        )
    except ValueError as e:
        code = str(e)
        messages = {
            "location_incomplete": "برای مختصات، هم عرض و هم طول جغرافیایی لازم است",
            "location_invalid": "مختصات نامعتبر است",
            "location_out_of_range": "مختصات خارج از بازه مجاز است",
        }
        raise HTTPException(400, {"error": messages.get(code, "location error")}) from e


@router.post("/events")
def admin_create_event(body: EventBody, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    if db.scalar(select(Event).where(Event.slug == body.slug)):
        raise HTTPException(409, {"error": "slug exists"})
    ev = Event(
        slug=body.slug,
        title=body.title,
        episode_number=body.episodeNumber,
        description=body.description,
        event_at=parse_event_at(body.eventAt),
        city=body.city,
        venue=body.venue,
        host_name=body.hostName,
        host_venue=body.hostVenue,
        capacity=body.capacity,
        ticket_price=body.ticketPrice,
        payment_card_number=body.paymentCardNumber,
        payment_card_holder=body.paymentCardHolder,
        payment_bank_name=body.paymentBankName,
        payment_instructions=body.paymentInstructions,
        status=body.status,
        sales_status=body.salesStatus,
        setlist_json=body.setlistJson,
        artists_json=body.artistsJson,
    )
    _apply_event_location(ev, body)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    if not get_featured_event_id(db):
        set_featured_event_id(db, ev.id)
    return {"id": ev.id}


@router.patch("/events/{event_id}")
def admin_update_event(event_id: int, body: EventBody, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, "not found")
    ev.slug = body.slug
    ev.title = body.title
    ev.episode_number = body.episodeNumber
    ev.description = body.description
    ev.event_at = parse_event_at(body.eventAt)
    ev.city = body.city
    ev.venue = body.venue
    ev.host_name = body.hostName
    ev.host_venue = body.hostVenue
    _apply_event_location(ev, body)
    ev.capacity = body.capacity
    ev.ticket_price = body.ticketPrice
    ev.payment_card_number = body.paymentCardNumber
    ev.payment_card_holder = body.paymentCardHolder
    ev.payment_bank_name = body.paymentBankName
    ev.payment_instructions = body.paymentInstructions
    ev.status = body.status
    ev.sales_status = body.salesStatus
    ev.setlist_json = body.setlistJson
    ev.artists_json = body.artistsJson
    ev.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/events/{event_id}/feature")
def admin_feature(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, "not found")
    if ev.status in ("draft", "cancelled"):
        raise HTTPException(409, {"error": "رویداد پیش‌نویس یا لغوشده را بدون تأیید نمی‌توان featured کرد"})
    set_featured_event_id(db, event_id)
    return {"ok": True, "featuredEventId": event_id}


@router.post("/events/{event_id}/publish")
def admin_publish(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, "not found")
    ev.status = "published"
    db.commit()
    return {"ok": True}


@router.post("/events/{event_id}/close-sales")
def admin_close_sales(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, "not found")
    ev.sales_status = "closed"
    db.commit()
    return {"ok": True}


@router.post("/events/{event_id}/open-sales")
def admin_open_sales(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(404, "not found")
    ev.sales_status = "open"
    if ev.status == "draft":
        ev.status = "sales_open"
    db.commit()
    return {"ok": True}


@router.get("/tickets")
def admin_tickets(
    eventId: int | None = Query(None),
    status: str = Query("active"),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    eid = eventId or _default_event_id(db)
    q = select(Ticket).where(Ticket.event_id == eid)
    if status != "all":
        q = q.where(Ticket.status == status)
    rows = db.scalars(q.order_by(Ticket.id.desc())).all()
    ranks = active_rank_map(db, eid)
    return {
        "tickets": [
            {
                "id": t.id,
                "serial": t.public_code,
                "name": t.holder_name,
                "phone": t.phone,
                "group_name": t.group_name,
                "created_at": _iso_utc(t.issued_at) or "",
                "eventId": t.event_id,
                "displayNumber": public_number(t, ranks) if t.status == "active" else None,
                "issuanceNumber": t.display_number,
                "status": t.status,
            }
            for t in rows
        ]
    }


@router.post("/tickets")
def admin_ticket_create(body: TicketBody, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    name = (body.name or "").strip()
    phone = normalize_phone(body.phone)
    if not name:
        raise HTTPException(400, {"error": "name required"})
    if not valid_phone(phone):
        raise HTTPException(400, {"error": "invalid phone"})
    eid = body.eventId or _default_event_id(db)
    serial = None
    if body.serial:
        serial = re.sub(r"\D", "", body.serial).zfill(4)[-4:]
        if not re.match(r"^\d{4}$", serial):
            raise HTTPException(400, {"error": "invalid serial"})
        clash = db.scalar(select(Ticket).where(Ticket.event_id == eid, Ticket.public_code == serial))
        if clash:
            raise HTTPException(409, {"error": "serial already exists"})
    else:
        serial = unique_public_code(db, eid)
    group = body.group if body.group in ("A", "B") else None
    ticket, _ = issue_ticket(
        db,
        event_id=eid,
        order_id=None,
        holder_name=name,
        phone=phone,
        public_code=serial,
        group_name=group,
    )
    db.commit()
    return {
        "id": ticket.id,
        "serial": ticket.public_code,
        "name": ticket.holder_name,
        "phone": ticket.phone,
        "group_name": ticket.group_name,
    }


@router.put("/tickets")
def admin_ticket_update(
    id: int = Query(...),
    body: TicketUpdateBody = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    body = body or TicketUpdateBody()
    t = db.get(Ticket, id)
    if not t:
        raise HTTPException(404, "not found")
    if body.name:
        t.holder_name = body.name.strip()[:200]
    if body.phone:
        phone = normalize_phone(body.phone)
        if not valid_phone(phone):
            raise HTTPException(400, {"error": "invalid phone"})
        t.phone = phone
    if body.serial:
        s = re.sub(r"\D", "", body.serial).zfill(4)[-4:]
        clash = db.scalar(
            select(Ticket).where(Ticket.event_id == t.event_id, Ticket.public_code == s, Ticket.id != id)
        )
        if clash:
            raise HTTPException(409, {"error": "serial already exists"})
        t.public_code = s
    if body.group in ("A", "B"):
        t.group_name = body.group
    db.commit()
    return {"id": t.id, "serial": t.public_code, "name": t.holder_name, "phone": t.phone, "group_name": t.group_name}


def _ticket_export_response(t: Ticket, db: Session, sample: bool = False):
    from fastapi.responses import Response

    if t.status != "active" and not sample:
        raise HTTPException(409, {"error": "ticket not printable"})
    ev = db.get(Event, t.event_id)
    if sample:
        ticket_number = t.display_number
    else:
        ranks = active_rank_map(db, t.event_id)
        ticket_number = public_number(t, ranks) or t.display_number
    try:
        body, media_type, ext = render_ticket_bytes(
            t.group_name,
            t.holder_name,
            t.public_code,
            ticket_number,
            event_at=ev.event_at if ev else None,
            venue=ticket_venue_from_event(ev),
            city=ev.city if ev else "",
            output_format="png",
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
    label = "sample" if sample else t.public_code
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="ticket-{label}.{ext}"'},
    )


@router.get("/tickets/sample")
def admin_ticket_sample(
    eventId: int | None = Query(None),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Sample PNG: A+B tickets on gothic mountain stage (headless), else single A PNG."""
    from fastapi.responses import Response

    from app.services.ticket_png_headless import headless_chromium_available, render_html_png_headless
    from app.services.ticket_render import fill_ticket_svg
    from app.services.tickets import group_for_code

    eid = eventId or _default_event_id(db)
    ev = db.get(Event, eid)
    if not ev:
        raise HTTPException(404, "not found")
    venue = ticket_venue_from_event(ev)
    city = ev.city or ""
    event_at = ev.event_at
    svg_a = fill_ticket_svg("A", "پویان احمدی مقدم", "0001", 1, event_at=event_at, venue=venue, city=city)
    svg_b = fill_ticket_svg("B", "علی رضایی", "0002", 2, event_at=event_at, venue=venue, city=city)
    if headless_chromium_available():
        try:
            html = _gothic_sample_html(svg_a, svg_b)
            body = render_html_png_headless(html, out_w=820, out_h=420)
            return Response(
                content=body,
                media_type="image/png",
                headers={"Content-Disposition": 'attachment; filename="ticket-sample-ab.png"'},
            )
        except Exception:
            pass
    fake = Ticket(
        id=0,
        event_id=eid,
        order_id=None,
        holder_name="پویان احمدی مقدم",
        phone="09120000000",
        public_code="0001",
        display_number=1,
        group_name=group_for_code("0001"),
        access_token_hash="",
        status="active",
    )
    return _ticket_export_response(fake, db, sample=True)


def _gothic_sample_html(svg_a: str, svg_b: str) -> str:
    """Gothic frame with B stacked above A so mountains and pairing W meet at the join."""
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<style>
html,body{{margin:0;padding:0;background:#0b0a0e;}}
.stage{{
  box-sizing:border-box;width:820px;min-height:420px;padding:28px 24px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  background:
    radial-gradient(ellipse 95% 75% at 50% 26%, rgba(104,82,128,0.16), transparent 68%),
    linear-gradient(180deg,#131016,#0b0a0e);
}}
.gothic-frame{{
  position:relative;padding:14px;width:100%;max-width:740px;box-sizing:border-box;
  background:
    radial-gradient(ellipse 95% 75% at 50% 26%, rgba(104,82,128,0.16), transparent 68%),
    linear-gradient(180deg,#131016,#0b0a0e);
  border:1px solid #322a40;
  box-shadow:inset 0 0 70px rgba(0,0,0,0.75),0 24px 60px rgba(0,0,0,0.55),0 0 0 1px rgba(212,63,90,0.12);
}}
.pair-stack{{
  display:flex;flex-direction:column;align-items:stretch;gap:0;width:100%;
}}
.pair-stack svg{{display:block;width:100%;height:auto;}}
.pair-caption{{
  margin:14px 0 0;text-align:center;font:600 13px/1.4 Consolas,'Courier New',monospace;
  color:#c4bcb0;letter-spacing:0.04em;
}}
</style></head><body>
<div class="stage">
  <div class="gothic-frame">
    <div class="pair-stack">
      {svg_b}
      {svg_a}
    </div>
    <p class="pair-caption">B above A — mountains + W</p>
  </div>
</div>
</body></html>"""


@router.get("/tickets/export")
def admin_tickets_export_zip(
    eventId: int | None = Query(None),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    import io
    import zipfile

    from fastapi.responses import Response

    eid = eventId or _default_event_id(db)
    rows = db.scalars(
        select(Ticket).where(Ticket.event_id == eid, Ticket.status == "active").order_by(Ticket.id.asc())
    ).all()
    if not rows:
        raise HTTPException(404, {"error": "no printable tickets", "message": "بلیتی برای خروجی نیست"})
    ev = db.get(Event, eid)
    ranks = active_rank_map(db, eid)
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for t in rows:
                ticket_number = public_number(t, ranks) or t.display_number
                body, _, ext = render_ticket_bytes(
                    t.group_name,
                    t.holder_name,
                    t.public_code,
                    ticket_number,
                    event_at=ev.event_at if ev else None,
                    venue=ticket_venue_from_event(ev),
                    city=ev.city if ev else "",
                )
                safe_name = re.sub(r"[^\w\-]+", "_", t.holder_name)[:40]
                zf.writestr(f"{t.public_code}-{safe_name}.{ext}", body)
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
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="wewerehere-tickets.zip"'},
    )


@router.get("/tickets/{ticket_id}/export")
def admin_ticket_export(ticket_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    t = db.get(Ticket, ticket_id)
    if not t:
        raise HTTPException(404, "not found")
    return _ticket_export_response(t, db)


@router.delete("/tickets")
def admin_ticket_delete(id: int = Query(...), db: Session = Depends(get_db), _: str = Depends(require_admin)):
    t = db.get(Ticket, id)
    if not t:
        raise HTTPException(404, "not found")
    t.status = "revoked"
    t.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/orders")
def admin_orders(
    status: str = Query("all"),
    eventId: int | None = Query(None),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    eid = eventId or _default_event_id(db)
    q = select(Order).where(Order.event_id == eid).order_by(Order.id.desc())
    if status != "all":
        st = status
        if status == "pending":
            st = "payment_submitted"
        q = q.where(Order.status == st)
    rows = db.scalars(q).all()
    orders = []
    for o in rows:
        receipt = o.receipt
        img_url = ""
        if receipt and receipt.file_path:
            img_url = f"/api/admin/receipts/{o.id}"
        names = json.loads(o.names_json or "[]")
        orders.append(
            {
                "id": o.id,
                "phone": o.phone,
                "names": names,
                "ticketCount": len(names),
                "issuedTicketCount": sum(1 for t in o.tickets if t.status == "active"),
                "status": "pending" if o.status == "payment_submitted" else o.status,
                "receiptText": receipt.text if receipt else "",
                "receiptImageUrl": img_url,
                "adminNote": o.admin_note or "",
                "createdAt": _iso_utc(o.created_at) or "",
                "reviewedAt": _iso_utc(o.reviewed_at),
                "eventId": o.event_id,
            }
        )
    return {"orders": orders}


@router.get("/receipts/{order_id}")
def admin_receipt_file(order_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    from fastapi.responses import FileResponse

    receipt = db.scalar(select(PaymentReceipt).where(PaymentReceipt.order_id == order_id))
    if not receipt or not receipt.file_path:
        raise HTTPException(404, "not found")
    path = _receipt_path(receipt.file_path)
    if not path.is_file():
        raise HTTPException(404, "file missing")
    return FileResponse(path)


@router.post("/orders/approve")
def admin_approve(id: int = Query(...), db: Session = Depends(get_db), _: str = Depends(require_admin)):
    try:
        order, tickets, freshly = approve_order(db, id)
    except LookupError:
        raise HTTPException(404, "not found")
    except ValueError as e:
        raise HTTPException(409, {"error": str(e)})
    sms = {"sent": 0, "failed": 0, "skipped": True}
    if freshly and tickets and notify_svc.SMS_ENABLED:
        # Phone only from persisted order — never from request body.
        # (SMS parked until enamad / sms.ir template approval — see notify.SMS_ENABLED)
        sms = notify_tickets_issued(order.phone, tickets)
        sms["skipped"] = False
    elif freshly and tickets and not notify_svc.SMS_ENABLED:
        sms = {"sent": 0, "failed": 0, "skipped": True, "disabled": True}
    return {"id": order.id, "status": "approved", "tickets": tickets, "sms": sms}


@router.post("/orders/resend-sms")
def admin_resend_order_sms(
    id: int = Query(...),
    db: Session = Depends(get_db),
    token: str = Depends(require_admin),
):
    # SMS UI/API parked until enamad / sms.ir template approval
    if not notify_svc.SMS_ENABLED:
        raise HTTPException(503, {"error": "sms_disabled"})
    check_rate_limit(_sms_rate, f"resend:{token}", limit=10, window_sec=60)
    order = db.get(Order, id)
    if not order:
        raise HTTPException(404, "not found")
    if order.status != "approved":
        raise HTTPException(409, {"error": "order not approved"})
    tickets = [
        {"serial": t.public_code, "name": t.holder_name, "group": t.group_name}
        for t in order.tickets
        if t.status == "active"
    ]
    if not tickets:
        raise HTTPException(409, {"error": "no active tickets"})
    sms = notify_tickets_issued(order.phone, tickets)
    return {"id": order.id, "sms": sms}


@router.post("/tickets/resend-sms")
def admin_resend_ticket_sms(
    id: int = Query(...),
    db: Session = Depends(get_db),
    token: str = Depends(require_admin),
):
    """Resend issue SMS for this ticket's phone: all active same-phone tickets in the event."""
    if not notify_svc.SMS_ENABLED:
        raise HTTPException(503, {"error": "sms_disabled"})
    check_rate_limit(_sms_rate, f"resend-ticket:{token}", limit=10, window_sec=60)
    ticket = db.get(Ticket, id)
    if not ticket:
        raise HTTPException(404, "not found")
    if ticket.status != "active":
        raise HTTPException(409, {"error": "ticket not active"})

    rows = db.scalars(
        select(Ticket)
        .where(
            Ticket.event_id == ticket.event_id,
            Ticket.phone == ticket.phone,
            Ticket.status == "active",
        )
        .order_by(Ticket.issued_at.asc(), Ticket.id.asc())
    ).all()
    payload = [
        {"serial": t.public_code, "name": t.holder_name, "group": t.group_name}
        for t in rows
    ]
    if not payload:
        raise HTTPException(409, {"error": "no active tickets"})

    sms = notify_tickets_issued(ticket.phone, payload)
    phone = ticket.phone or ""
    masked = (phone[:4] + "****" + phone[-3:]) if len(phone) >= 7 else "***"
    return {
        "ok": True,
        "phoneMasked": masked,
        "namesCount": len(payload),
        "sms": sms,
    }


@router.get("/sms/presets")
def admin_sms_presets(_: str = Depends(require_admin)):
    if not notify_svc.SMS_ENABLED:
        raise HTTPException(503, {"error": "sms_disabled"})
    presets = list_admin_presets()
    return {
        "provider": (settings.sms_provider or "console"),
        "presets": [
            {"id": p["id"], "label": p["label"], "paramName": p["paramName"]}
            for p in presets
        ],
    }


@router.post("/sms/send")
def admin_sms_send(
    body: SmsSendBody,
    token: str = Depends(require_admin),
):
    if not notify_svc.SMS_ENABLED:
        raise HTTPException(503, {"error": "sms_disabled"})
    check_rate_limit(_sms_rate, f"send:{token}", limit=10, window_sec=60)
    phone = normalize_phone(body.phone)
    if not valid_phone(phone):
        raise HTTPException(400, {"error": "invalid phone"})
    preset_id = (body.presetId or "").strip()
    if not preset_id:
        raise HTTPException(400, {"error": "preset required"})
    result = send_admin_preset(phone, preset_id, body.value or "")
    if not result.get("ok"):
        kind = result.get("failure_kind") or "send_failed"
        status = 400 if kind in ("invalid_phone", "unknown_preset", "empty_value") else 503
        raise HTTPException(status, {"error": kind})
    return {
        "ok": True,
        "provider": result.get("provider"),
        "phoneMasked": result.get("phone_masked"),
        "messageId": result.get("message_id"),
    }


@router.post("/orders/reject")
def admin_reject(
    id: int = Query(...),
    body: RejectBody = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    body = body or RejectBody()
    try:
        reject_order(db, id, body.note)
    except LookupError:
        raise HTTPException(404, "not found")
    except ValueError as e:
        raise HTTPException(409, {"error": str(e)})
    return {"id": id, "status": "rejected"}


@router.get("/settings")
def admin_settings_get(eventId: int | None = Query(None), db: Session = Depends(get_db), _: str = Depends(require_admin)):
    eid = eventId or _default_event_id(db)
    ev = db.get(Event, eid)
    return {
        "card_number": ev.payment_card_number,
        "card_holder": ev.payment_card_holder,
        "bank_name": ev.payment_bank_name,
        "ticket_price": str(ev.ticket_price),
        "eventId": ev.id,
        "featuredEventId": get_featured_event_id(db),
    }


@router.put("/settings")
def admin_settings_put(body: SettingsBody, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    eid = body.eventId or _default_event_id(db)
    ev = db.get(Event, eid)
    if body.card_number is not None:
        ev.payment_card_number = body.card_number[:64]
    if body.card_holder is not None:
        ev.payment_card_holder = body.card_holder[:200]
    if body.bank_name is not None:
        ev.payment_bank_name = body.bank_name[:120]
    if body.ticket_price is not None:
        ev.ticket_price = int(re.sub(r"\D", "", body.ticket_price) or "0")
    db.commit()
    return {"ok": True}


@router.get("/media")
def admin_media_list(eventId: int | None = Query(None), db: Session = Depends(get_db), _: str = Depends(require_admin)):
    eid = eventId or _default_event_id(db)
    rows = db.scalars(select(Media).where(Media.event_id == eid).order_by(Media.id.desc())).all()
    return {
        "media": [
            {
                "id": m.id,
                "filename": m.filename,
                "original_name": m.original_name,
                "mime": m.mime,
                "size": m.size,
                "caption": m.caption,
                "created_at": m.created_at.isoformat() if m.created_at else "",
                "url": f"/api/admin/media-file/{m.id}",
                "eventId": m.event_id,
            }
            for m in rows
        ]
    }


@router.get("/media-file/{media_id}")
def admin_media_file(media_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    from app.routers.public import _file_response

    m = db.get(Media, media_id)
    if not m:
        raise HTTPException(404, "not found")
    return _file_response(m)


@router.post("/media")
def admin_media_upload(body: MediaUploadBody, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    if not re.match(r"^(image|video)/", body.mime):
        raise HTTPException(400, {"error": "unsupported type"})
    ext = MIME_EXT.get(body.mime)
    if not ext:
        raise HTTPException(400, {"error": "unsupported mime type"})
    try:
        raw = base64.b64decode(body.data)
    except Exception:
        raise HTTPException(400, {"error": "bad base64"})
    if len(raw) > 40 * 1024 * 1024:
        raise HTTPException(413, {"error": "file too large"})
    eid = body.eventId or _default_event_id(db)
    settings.archive_dir.mkdir(parents=True, exist_ok=True)
    import secrets

    fname = f"{int(datetime.now().timestamp() * 1000):x}-{secrets.token_hex(4)}{ext}"
    (settings.archive_dir / fname).write_bytes(raw)
    m = Media(
        event_id=eid,
        filename=fname,
        original_name=body.filename[:200],
        mime=body.mime,
        size=len(raw),
        caption=(body.caption or "")[:500],
        access_level="archive_private",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {
        "id": m.id,
        "url": f"/api/admin/media-file/{m.id}",
        "mime": m.mime,
        "caption": m.caption,
        "original_name": m.original_name,
    }


@router.put("/media")
def admin_media_caption(id: int = Query(...), body: MediaCaptionBody = None, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    body = body or MediaCaptionBody()
    m = db.get(Media, id)
    if not m:
        raise HTTPException(404, "not found")
    m.caption = (body.caption or "")[:500]
    db.commit()
    return {"id": m.id, "caption": m.caption}


@router.delete("/media")
def admin_media_delete(id: int = Query(...), db: Session = Depends(get_db), _: str = Depends(require_admin)):
    m = db.get(Media, id)
    if not m:
        raise HTTPException(404, "not found")
    path = settings.archive_dir / m.filename
    if path.is_file():
        path.unlink()
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.get("/support/tickets/{ticket_id}")
def admin_support_detail(ticket_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(404, "not found")
    msgs = db.scalars(
        select(SupportMessage).where(SupportMessage.ticket_id == t.id).order_by(SupportMessage.id.asc())
    ).all()
    return {
        "id": t.id,
        "phone": t.phone,
        "displayName": contact_display_name(db, t.phone),
        "subject": t.subject,
        "status": t.status,
        "eventId": t.event_id,
        "createdAt": t.created_at.isoformat(),
        "messages": [
            {"role": m.author_role, "body": m.body, "createdAt": m.created_at.isoformat()} for m in msgs
        ],
    }


@router.get("/support/tickets")
def admin_support_list(status: str = Query("all"), db: Session = Depends(get_db), _: str = Depends(require_admin)):
    q = select(SupportTicket).order_by(SupportTicket.id.desc())
    if status == "active":
        q = q.where(SupportTicket.status.in_(tuple(_ACTIVE_SUPPORT)))
    elif status != "all":
        q = q.where(SupportTicket.status == status)
    rows = db.scalars(q).all()
    return {
        "tickets": [
            {
                "id": t.id,
                "phone": t.phone,
                "displayName": contact_display_name(db, t.phone),
                "subject": t.subject,
                "status": t.status,
                "eventId": t.event_id,
                "createdAt": t.created_at.isoformat(),
            }
            for t in rows
        ]
    }


@router.post("/support/tickets/{ticket_id}/reply")
def admin_support_reply(
    ticket_id: int,
    body: SupportReplyBody,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(404, "not found")
    db.add(SupportMessage(ticket_id=t.id, author_role="admin", body=body.body[:2000]))
    t.status = "waiting_user"
    db.commit()
    return {"ok": True}


@router.post("/support/tickets/{ticket_id}/close")
def admin_support_close(ticket_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(404, "not found")
    t.status = "closed"
    t.closed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}
