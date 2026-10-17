"""Append-only audit helpers for night memories."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import MemoryAuditLog


def write_audit(
    db: Session,
    *,
    event_id: int,
    action: str,
    actor: str = "system",
    item_id: int | None = None,
    ticket_id: int | None = None,
    meta: dict[str, Any] | None = None,
    commit: bool = False,
) -> MemoryAuditLog:
    row = MemoryAuditLog(
        event_id=int(event_id),
        item_id=item_id,
        ticket_id=ticket_id,
        actor=(actor or "system")[:32],
        action=(action or "unknown")[:40],
        meta_json=json.dumps(meta or {}, ensure_ascii=False)[:4000],
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row
