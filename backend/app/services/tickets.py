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


def active_rank_map(db: Session, event_id: int) -> dict[int, int]:
    """Dense 1..N ranks among active tickets, ordered by issuance (display_number, id)."""
    rows = db.scalars(
        select(Ticket.id)
        .where(Ticket.event_id == event_id, Ticket.status == "active")
        .order_by(Ticket.display_number.asc(), Ticket.id.asc())
    ).all()
    return {tid: rank for rank, tid in enumerate(rows, start=1)}


def public_number(ticket: Ticket, rank_map: dict[int, int]) -> int | None:
    if ticket.status != "active":
        return None
    return rank_map.get(ticket.id)


def pick_balanced_group(db: Session, event_id: int) -> str:
    count_a = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.event_id == event_id, Ticket.status == "active", Ticket.group_name == "A")
    ) or 0
    count_b = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.event_id == event_id, Ticket.status == "active", Ticket.group_name == "B")
    ) or 0
    if count_a < count_b:
        return "A"
    if count_b < count_a:
        return "B"
    return "A"


def issue_ticket(
    db: Session,
    *,
    event_id: int,
    order_id: int | None,
    holder_name: str,
    phone: str,
    public_code: str | None = None,
    group_name: str | None = None,
    wants_physical_card: bool = False,
) -> tuple[Ticket, str]:
    code = public_code or unique_public_code(db, event_id)
    group = group_name if group_name in ("A", "B") else pick_balanced_group(db, event_id)
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
        wants_physical_card=wants_physical_card,
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


_EN_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_fa_digits(val: int | str) -> str:
    return str(val).translate(_EN_TO_FA)


def ticket_table_info(ticket: Ticket) -> dict:
    """Computes party size, guest index in table, table type label and table ID for a ticket."""
    order = ticket.order
    if order and order.tickets:
        order_tickets = sorted(order.tickets, key=lambda t: t.id)
        party_size = len(order_tickets)
        try:
            guest_index = order_tickets.index(ticket) + 1
        except ValueError:
            guest_index = 1

        table_type = "تک‌نفره" if party_size <= 1 else f"{to_fa_digits(party_size)} نفره"
        guest_position = "تک‌نفره" if party_size <= 1 else f"نفر {to_fa_digits(guest_index)} از {to_fa_digits(party_size)}"
        table_label = f"میز #{order.id}"
        return {
            "order_id": order.id,
            "party_size": party_size,
            "guest_index": guest_index,
            "table_type": table_type,
            "guest_position": guest_position,
            "table_label": table_label,
        }

    return {
        "order_id": None,
        "party_size": 1,
        "guest_index": 1,
        "table_type": "تک‌نفره",
        "guest_position": "تک‌نفره",
        "table_label": "تکی (دستی)",
    }

