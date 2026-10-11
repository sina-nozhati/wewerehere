from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SupportMessage, SupportTicket, Ticket
from app.services.phone import normalize_phone, valid_phone
from app.services.support_access import issue_token, phone_from_token, revoke_token
from app.services.support_contacts import contact_display_name, upsert_support_contact
router = APIRouter(prefix="/api/support", tags=["support"])
_support_bearer = HTTPBearer(auto_error=False)


class VerifyBody(BaseModel):
    phone: str


class CreateTicketBody(BaseModel):
    phone: str = ""
    displayName: str = ""
    subject: str
    message: str
    eventId: int | None = None


class UserMessageBody(BaseModel):
    phone: str = ""
    message: str


def _session_payload(db: Session, phone_n: str) -> dict:
    event_tickets = db.scalars(
        select(Ticket).where(Ticket.phone == phone_n, Ticket.status == "active").order_by(Ticket.id.desc())
    ).all()
    display = contact_display_name(db, phone_n)
    holder = event_tickets[0].holder_name if event_tickets else display
    return {
        "phone": phone_n,
        "hasEventTicket": bool(event_tickets),
        "holderName": (holder or "").strip(),
        "displayName": (display or holder or "").strip(),
        "ticketCount": len(event_tickets),
    }


def require_support_phone(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_support_bearer)],
) -> str:
    token = creds.credentials if creds else None
    phone_n = phone_from_token(token)
    if not phone_n:
        raise HTTPException(401, {"error": "support login required"})
    return phone_n


@router.post("/verify")
def support_verify(body: VerifyBody, db: Session = Depends(get_db)):
    """Confirm phone and issue a short-lived access token for chat APIs."""
    phone_n = normalize_phone(body.phone)
    if not valid_phone(phone_n):
        raise HTTPException(400, {"error": "invalid phone"})
    upsert_support_contact(db, phone_n)
    db.commit()
    payload = _session_payload(db, phone_n)
    payload["accessToken"] = issue_token(phone_n)
    return payload


@router.post("/logout")
def support_logout(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_support_bearer)]):
    if creds:
        revoke_token(creds.credentials)
    return {"ok": True}


@router.get("/me")
def support_me(phone_n: str = Depends(require_support_phone), db: Session = Depends(get_db)):
    """Buyer metadata for the authenticated support session (no phone in query)."""
    return _session_payload(db, phone_n)


@router.get("/session")
def support_session_deprecated():
    """Removed public phone lookup — use POST /verify or GET /me with Bearer."""
    raise HTTPException(410, {"error": "deprecated; use POST /api/support/verify or GET /api/support/me"})


@router.get("/tickets")
def list_tickets(phone_n: str = Depends(require_support_phone), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(SupportTicket).where(SupportTicket.phone == phone_n).order_by(SupportTicket.id.desc())
    ).all()
    out = []
    for t in rows:
        msgs = db.scalars(
            select(SupportMessage).where(SupportMessage.ticket_id == t.id).order_by(SupportMessage.id.asc())
        ).all()
        out.append(
            {
                "id": t.id,
                "subject": t.subject,
                "status": t.status,
                "eventId": t.event_id,
                "createdAt": t.created_at.isoformat(),
                "messages": [
                    {"role": m.author_role, "body": m.body, "createdAt": m.created_at.isoformat()} for m in msgs
                ],
            }
        )
    return {"tickets": out}


@router.post("/tickets")
def create_ticket(
    body: CreateTicketBody,
    phone_n: str = Depends(require_support_phone),
    db: Session = Depends(get_db),
):
    subject = (body.subject or "").strip()[:300]
    message = (body.message or "").strip()[:2000]
    if not subject or not message:
        raise HTTPException(400, {"error": "subject and message required"})
    upsert_support_contact(db, phone_n, body.displayName or "")
    ticket = SupportTicket(
        phone=phone_n,
        event_id=body.eventId,
        subject=subject,
        status="open",
    )
    db.add(ticket)
    db.flush()
    db.add(SupportMessage(ticket_id=ticket.id, author_role="user", body=message))
    ticket.status = "waiting_admin"
    db.commit()
    return {"id": ticket.id, "status": ticket.status}


@router.post("/tickets/{ticket_id}/messages")
def add_user_message(
    ticket_id: int,
    body: UserMessageBody,
    phone_n: str = Depends(require_support_phone),
    db: Session = Depends(get_db),
):
    message = (body.message or "").strip()[:2000]
    if not message:
        raise HTTPException(400, {"error": "message required"})
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(404, "not found")
    if t.phone != phone_n:
        raise HTTPException(403, "forbidden")
    if t.status == "closed":
        raise HTTPException(409, {"error": "ticket closed"})
    db.add(SupportMessage(ticket_id=t.id, author_role="user", body=message))
    t.status = "waiting_admin"
    upsert_support_contact(db, phone_n)
    db.commit()
    return {"ok": True, "status": t.status}
