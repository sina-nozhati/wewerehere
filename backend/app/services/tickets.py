import hashlib
import secrets
from random import randint

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ticket


def group_for_code(code: str) -> str:
    try:
        return "A" if int(code) % 2 else "B"
    except ValueError:
        return "A"


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_access_token() -> str:
    return secrets.token_urlsafe(32)


def unique_public_code(db: Session, event_id: int) -> str:
    for _ in range(200):
        serial = f"{randint(0, 9999):04d}"
        exists = db.scalar(
            select(func.count()).select_from(Ticket).where(
                Ticket.event_id == event_id, Ticket.public_code == serial
            )
        )
        if not exists:
            return serial
    raise RuntimeError("could not allocate unique serial")


def next_display_number(db: Session, event_id: int) -> int:
    current = db.scalar(
        select(func.max(Ticket.display_number)).where(Ticket.event_id == event_id)
    )
    return (current or 0) + 1


def issue_ticket(
    db: Session,
    *,
    event_id: int,
    order_id: int | None,
    holder_name: str,
    phone: str,
    public_code: str | None = None,
    group_name: str | None = None,
) -> tuple[Ticket, str]:
    code = public_code or unique_public_code(db, event_id)
    group = group_name if group_name in ("A", "B") else group_for_code(code)
    token = generate_access_token()
    ticket = Ticket(
        event_id=event_id,
        order_id=order_id,
        holder_name=holder_name[:200],
        phone=phone,
        public_code=code,
        display_number=next_display_number(db, event_id),
        group_name=group,
        access_token_hash=hash_access_token(token),
        status="active",
    )
    db.add(ticket)
    db.flush()
    return ticket, token


def verify_ticket_access(db: Session, event_id: int, public_code: str, access_token: str) -> Ticket | None:
    code = public_code.replace("D", "").zfill(4)[-4:]
    th = hash_access_token(access_token)
    return db.scalar(
        select(Ticket).where(
            Ticket.event_id == event_id,
            Ticket.public_code == code,
            Ticket.access_token_hash == th,
            Ticket.status == "active",
        )
    )
