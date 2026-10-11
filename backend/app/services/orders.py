import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, PaymentReceipt
from app.services.capacity import remaining_tickets
from app.services.phone import normalize_phone, valid_phone
from app.services.tickets import issue_ticket

MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

MAX_MEDIA = 40 * 1024 * 1024


def map_legacy_status(status: str) -> str:
    if status == "pending":
        return "payment_submitted"
    return status


def status_for_ui(status: str) -> str:
    if status == "payment_submitted":
        return "pending"
    return status


def create_order(
    db: Session,
    *,
    event_id: int,
    capacity: int,
    phone: str,
    names: list[str],
    receipt_text: str,
    receipt_image: dict | None,
) -> Order:
    phone = normalize_phone(phone)
    if not valid_phone(phone):
        raise ValueError("invalid phone")
    names = [n.strip() for n in names if n and n.strip()]
    if not 1 <= len(names) <= 6:
        raise ValueError("invalid names")

    try:
        remaining = remaining_tickets(db, event_id, capacity)
        if len(names) > remaining:
            if remaining <= 0:
                raise ValueError("ظرفیت تکمیل شده است")
            raise ValueError(f"فقط {remaining} جای خالی باقی مانده است")

        order = Order(
            event_id=event_id,
            phone=phone,
            names_json=json.dumps(names, ensure_ascii=False),
            status="payment_submitted",
        )
        db.add(order)
        db.flush()

        file_path = ""
        if receipt_image and receipt_image.get("data"):
            mime = receipt_image.get("mime") or "image/png"
            if not str(mime).startswith("image/"):
                raise ValueError("فقط عکس برای رسید قابل قبول است")
            ext = MIME_EXT.get(mime)
            if not ext:
                raise ValueError("unsupported mime type")
            try:
                raw = base64.b64decode(str(receipt_image["data"]))
            except Exception:
                raise ValueError("bad base64")
            if not raw:
                raise ValueError("empty file")
            if len(raw) > MAX_MEDIA:
                raise ValueError("file too large")
            settings.receipts_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{int(datetime.now().timestamp() * 1000):x}-{order.id}{ext}"
            path = settings.receipts_dir / fname
            path.write_bytes(raw)
            file_path = str(path.relative_to(settings.storage_root)).replace("\\", "/")

        text = (receipt_text or "").strip()[:500]
        if not text and not file_path:
            raise ValueError("رسید پرداخت (متن یا عکس) لازم است")

        db.add(
            PaymentReceipt(
                order_id=order.id,
                text=text,
                file_path=file_path,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order


def approve_order(db: Session, order_id: int) -> tuple[Order, list[dict]]:
    order = db.get(Order, order_id)
    if not order:
        raise LookupError("not found")
    if order.status == "approved":
        tickets = [
            {
                "serial": t.public_code,
                "name": t.holder_name,
                "group": t.group_name,
            }
            for t in order.tickets
        ]
        return order, tickets
    if order.status != "payment_submitted" and order.status != "pending":
        raise ValueError("این سفارش قبلاً بررسی شده است")

    names = json.loads(order.names_json or "[]")
    if not names:
        raise ValueError("no names on order")

    event = order.event
    try:
        remaining = remaining_tickets(db, event.id, event.capacity)
        if len(names) > remaining:
            raise ValueError("ظرفیت کافی برای تأیید این سفارش نیست")

        issued = []
        for name in names:
            ticket, _token = issue_ticket(
                db,
                event_id=event.id,
                order_id=order.id,
                holder_name=name,
                phone=order.phone,
            )
            issued.append(
                {
                    "serial": ticket.public_code,
                    "name": ticket.holder_name,
                    "group": ticket.group_name,
                }
            )

        order.status = "approved"
        order.reviewed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    return order, issued


def reject_order(db: Session, order_id: int, note: str) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise LookupError("not found")
    if order.status not in ("payment_submitted", "pending", "pending_payment"):
        raise ValueError("این سفارش قبلاً بررسی شده است")
    order.status = "rejected"
    order.admin_note = (note or "")[:500]
    order.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    return order
