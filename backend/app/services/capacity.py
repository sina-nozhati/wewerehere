import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, Ticket

PENDING_STATUSES = ("pending_payment", "payment_submitted", "pending")


def sold_count(db: Session, event_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.event_id == event_id, Ticket.status == "active"
        )
    ) or 0


def pending_names_count(db: Session, event_id: int) -> int:
    rows = db.scalars(
        select(Order.names_json).where(
            Order.event_id == event_id,
            Order.status.in_(PENDING_STATUSES),
        )
    ).all()
    total = 0
    for raw in rows:
        try:
            total += len(json.loads(raw or "[]"))
        except json.JSONDecodeError:
            pass
    return total


def remaining_tickets(db: Session, event_id: int, capacity: int) -> int:
    return max(0, capacity - sold_count(db, event_id) - pending_names_count(db, event_id))


def capacity_payload(db: Session, event_id: int, capacity: int) -> dict:
    sold = sold_count(db, event_id)
    pending = pending_names_count(db, event_id)
    remaining = max(0, capacity - sold - pending)
    return {
        "capacity": capacity,
        "sold": sold,
        "pending": pending,
        "remaining": remaining,
        "eventId": event_id,
    }
