"""One-off: set guilanshah venue and issue a test ticket; write rendered SVG."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Event, Ticket
from app.services.ticket_render import fill_ticket_svg, render_ticket_bytes
from app.services.tickets import issue_ticket

OUT = Path(__file__).resolve().parents[2] / "admin-test-guilanshah-ticket.svg"


def main() -> None:
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    ev = db.scalar(select(Event).where(Event.slug == "guilanshah"))
    if not ev:
        raise SystemExit("event guilanshah not found")
    ev.venue = ev.venue or "Cafe Anzali · بندر انزلی"
    ev.city = ev.city or "بندر انزلی"
    db.commit()

    ticket = db.scalar(
        select(Ticket).where(Ticket.event_id == ev.id, Ticket.phone == "09121112233")
    )
    if not ticket:
        ticket, _ = issue_ticket(
            db,
            event_id=ev.id,
            order_id=None,
            holder_name="آرش صلاحی",
            phone="09121112233",
            group_name="A",
        )
    else:
        ticket.holder_name = "آرش صلاحی"
    db.commit()
    db.refresh(ticket)

    event_at = ev.event_at
    if event_at and event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=timezone.utc)

    svg = fill_ticket_svg(
        ticket.group_name,
        ticket.holder_name,
        ticket.public_code,
        ticket.display_number,
        event_at=event_at,
        venue=ev.venue or "",
        city=ev.city or "",
    )
    OUT.write_text(svg, encoding="utf-8")
    body, mime, ext = render_ticket_bytes(
        ticket.group_name,
        ticket.holder_name,
        ticket.public_code,
        ticket.display_number,
        prefer_png=False,
        event_at=event_at,
        venue=ev.venue or "",
        city=ev.city or "",
    )
    png_path = OUT.with_suffix(f".{ext}")
    png_path.write_bytes(body)
    print("ticket_id", ticket.id, "code", ticket.public_code, "out", OUT, png_path)


if __name__ == "__main__":
    main()
