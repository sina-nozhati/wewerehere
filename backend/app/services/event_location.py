"""Event venue coordinates for track map + admin."""

from __future__ import annotations

from typing import Any

from app.models import Event
from app.services.event_display import ticket_venue_from_event


def normalize_coords(
    lat: float | None,
    lng: float | None,
) -> tuple[float | None, float | None]:
    """Return (lat, lng) both set or both None. Raises ValueError if invalid."""
    if lat is None and lng is None:
        return None, None
    if lat is None or lng is None:
        raise ValueError("location_incomplete")
    try:
        la = float(lat)
        ln = float(lng)
    except (TypeError, ValueError) as e:
        raise ValueError("location_invalid") from e
    if not (-90.0 <= la <= 90.0) or not (-180.0 <= ln <= 180.0):
        raise ValueError("location_out_of_range")
    return la, ln


def apply_location_fields(
    ev: Event,
    *,
    lat: float | None,
    lng: float | None,
    label: str,
    published: bool,
) -> None:
    la, ln = normalize_coords(lat, lng)
    ev.location_lat = la
    ev.location_lng = ln
    ev.location_label = (label or "").strip()[:280]
    # Publish only when both coordinates exist
    ev.location_published = bool(published) and la is not None and ln is not None


def location_payload_for_track(ev: Event) -> dict[str, Any] | None:
    """Public location block for track — caller must gate on tickets + published."""
    if not ev.location_published:
        return None
    if ev.location_lat is None or ev.location_lng is None:
        return None
    try:
        la, ln = normalize_coords(ev.location_lat, ev.location_lng)
    except ValueError:
        return None
    if la is None or ln is None:
        return None
    label = (ev.location_label or "").strip()
    if not label:
        venue = ticket_venue_from_event(ev)
        city = (ev.city or "").strip()
        if venue and city:
            label = f"{venue} · {city}"
        else:
            label = venue or city
    return {
        "lat": la,
        "lng": ln,
        "label": label,
        "venue": ticket_venue_from_event(ev),
        "city": (ev.city or "").strip(),
    }
