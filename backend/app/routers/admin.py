import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_session, require_admin, revoke_session, verify_admin_password
from app.config import settings
from app.storage_paths import receipt_path as _receipt_path
from app.db import get_db
from app.models import Event, Media, Order, PaymentReceipt, SiteSetting, SupportContact, SupportMessage, SupportTicket, Ticket
from app.services.events import FEATURED_KEY, event_at_iso, get_featured_event_id, parse_event_at, set_featured_event_id
from app.services.orders import approve_order, reject_order
from app.services.phone import normalize_phone, valid_phone
from app.services.event_display import ticket_venue_from_event
from app.services.ticket_render import TicketRenderError, render_ticket_bytes
from app.services.support_contacts import contact_display_name
from app.services.tickets import group_for_code, issue_ticket, unique_public_code

_ACTIVE_SUPPORT = frozenset({"open", "waiting_admin", "waiting_user"})

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
    return {
        "tickets": [
            {
                "id": t.id,
                "serial": t.public_code,
                "name": t.holder_name,
                "phone": t.phone,
                "group_name": t.group_name,
                "created_at": t.issued_at.isoformat() if t.issued_at else "",
                "eventId": t.event_id,
                "displayNumber": t.display_number,
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
    group = body.group if body.group in ("A", "B") else group_for_code(serial)
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
    try:
        body, media_type, ext = render_ticket_bytes(
            t.group_name,
            t.holder_name,
            t.public_code,
            t.display_number,
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
    from app.services.tickets import group_for_code

    eid = eventId or _default_event_id(db)
    ev = db.get(Event, eid)
    if not ev:
        raise HTTPException(404, "not found")
    fake = Ticket(
        id=0,
        event_id=eid,
        order_id=None,
        holder_name="نمونه — علی رضایی",
        phone="09120000000",
        public_code="0001",
        display_number=1,
        group_name=group_for_code("0001"),
        access_token_hash="",
        status="active",
    )
    return _ticket_export_response(fake, db, sample=True)


@router.get("/tickets/{ticket_id}/export")
def admin_ticket_export(ticket_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    t = db.get(Ticket, ticket_id)
    if not t:
        raise HTTPException(404, "not found")
    return _ticket_export_response(t, db)


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
        raise HTTPException(404, {"error": "no printable tickets"})
    ev = db.get(Event, eid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in rows:
            body, _, ext = render_ticket_bytes(
                t.group_name,
                t.holder_name,
                t.public_code,
                t.display_number,
                event_at=ev.event_at if ev else None,
                venue=ticket_venue_from_event(ev),
                city=ev.city if ev else "",
            )
            safe_name = re.sub(r"[^\w\-]+", "_", t.holder_name)[:40]
            zf.writestr(f"{t.public_code}-{safe_name}.{ext}", body)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="wewerehere-tickets.zip"'},
    )


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
                "createdAt": o.created_at.isoformat() if o.created_at else "",
                "reviewedAt": o.reviewed_at.isoformat() if o.reviewed_at else None,
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
        order, tickets = approve_order(db, id)
    except LookupError:
        raise HTTPException(404, "not found")
    except ValueError as e:
        raise HTTPException(409, {"error": str(e)})
    return {"id": order.id, "status": "approved", "tickets": tickets}


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
