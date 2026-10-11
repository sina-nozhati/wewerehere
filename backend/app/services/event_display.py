"""Display strings for tickets derived from Event rows."""

from app.models import Event
from app.services.jalali_schedule import venue_display_line


def ticket_venue_from_event(ev: Event | None) -> str:
    if not ev:
        return ""
    return venue_display_line(ev.venue or "", ev.city or "", ev.host_venue or "")
