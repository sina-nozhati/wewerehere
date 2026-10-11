"""Resolve support contact display names from tickets/orders."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Ticket

_ACTIVE_SUPPORT_STATUSES = frozenset({"open", "waiting_admin", "waiting_user"})


def resolve_display_name(db: Session, phone_n: str) -> str:
    ticket = db.scalars(
        select(Ticket)
        .where(Ticket.phone == phone_n, Ticket.status == "active")
        .order_by(Ticket.id.desc())
        .limit(1)
    ).first()
    if ticket and (ticket.holder_name or "").strip():
        return ticket.holder_name.strip()[:200]
    order = db.scalars(select(Order).where(Order.phone == phone_n).order_by(Order.id.desc()).limit(1)).first()
    if order and order.names_json:
        try:
            names = json.loads(order.names_json)
            if isinstance(names, list) and names:
                return str(names[0]).strip()[:200]
        except (json.JSONDecodeError, TypeError):
            pass
    return ""


def upsert_support_contact(db: Session, phone_n: str, display_name: str = "") -> None:
    from app.models import SupportContact

    name = (display_name or "").strip()[:200]
    contact = db.get(SupportContact, phone_n)
    if not contact:
        if not name:
            name = resolve_display_name(db, phone_n)
        db.add(SupportContact(phone=phone_n, display_name=name))
        return
    if name:
        contact.display_name = name
    elif not (contact.display_name or "").strip():
        resolved = resolve_display_name(db, phone_n)
        if resolved:
            contact.display_name = resolved


def contact_display_name(db: Session, phone_n: str) -> str:
    from app.models import SupportContact

    contact = db.get(SupportContact, phone_n)
    if contact and (contact.display_name or "").strip():
        return contact.display_name.strip()
    return resolve_display_name(db, phone_n)
