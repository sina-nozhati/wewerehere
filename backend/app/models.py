from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    venue: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    host_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    host_venue: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    ticket_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payment_card_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    payment_card_holder: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    payment_bank_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    payment_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    sales_status: Mapped[str] = mapped_column(String(32), default="closed", nullable=False)
    setlist_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    artists_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    poster_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    orders: Mapped[list["Order"]] = relationship(back_populates="event")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="event")
    media_items: Mapped[list["Media"]] = relationship(back_populates="event")


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    names_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="payment_submitted", nullable=False)
    admin_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped["Event"] = relationship(back_populates="orders")
    receipt: Mapped["PaymentReceipt | None"] = relationship(back_populates="order", uselist=False)
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="order")


class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped["Order"] = relationship(back_populates="receipt")


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("event_id", "public_code", name="uq_ticket_event_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    public_code: Mapped[str] = mapped_column(String(16), nullable=False)
    display_number: Mapped[int] = mapped_column(Integer, nullable=False)
    group_name: Mapped[str] = mapped_column(String(1), nullable=False)
    access_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped["Event"] = relationship(back_populates="tickets")
    order: Mapped["Order | None"] = relationship(back_populates="tickets")


class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    original_name: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    caption: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    access_level: Mapped[str] = mapped_column(String(32), default="archive_private", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event: Mapped["Event"] = relationship(back_populates="media_items")


class SupportContact(Base):
    __tablename__ = "support_contacts"

    phone: Mapped[str] = mapped_column(String(16), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tickets: Mapped[list["SupportTicket"]] = relationship(back_populates="contact")


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(ForeignKey("support_contacts.phone"), nullable=False, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contact: Mapped["SupportContact"] = relationship(back_populates="tickets")
    messages: Mapped[list["SupportMessage"]] = relationship(back_populates="ticket")


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id"), nullable=False, index=True)
    author_role: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped["SupportTicket"] = relationship(back_populates="messages")
