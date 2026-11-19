from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_label: Mapped[str] = mapped_column(String(280), default="", nullable=False)
    location_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    published_memory_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event: Mapped["Event"] = relationship(back_populates="media_items")


class MemorySession(Base):
    """Short-lived upload access after 4-digit ticket gate (token hash only)."""

    __tablename__ = "memory_sessions"

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryItem(Base):
    """Participant photo/video for an event night — pending until admin approves."""

    __tablename__ = "memory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="guest", nullable=False, index=True)
    media_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(300), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consent_publish: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class MemoryLike(Base):
    """One like per ticket per approved memory item."""

    __tablename__ = "memory_likes"
    __table_args__ = (UniqueConstraint("item_id", "ticket_id", name="uq_memory_like_item_ticket"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("memory_items.id"), nullable=False, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryComment(Base):
    __tablename__ = "memory_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("memory_items.id"), nullable=False, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryAuditLog(Base):
    """Append-only activity log for night memories (admin + guest actions)."""

    __tablename__ = "memory_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ticket_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    meta_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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


# ---------------------------------------------------------------------------
# Media Storage Manager Models
# ---------------------------------------------------------------------------

class StorageProvider(Base):
    """Configuration and health state for an external or local storage provider."""

    __tablename__ = "storage_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # files_ir | s3 | local
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    max_file_size_bytes: Mapped[int] = mapped_column(Integer, default=500 * 1024 * 1024, nullable=False)
    file_count_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_capacity_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)  # healthy | degraded | unreachable | full | unknown
    health_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EventStorageConfig(Base):
    """Event-level primary and ordered fallback storage provider assignments."""

    __tablename__ = "event_storage_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), unique=True, nullable=False, index=True)
    primary_provider_id: Mapped[int] = mapped_column(ForeignKey("storage_providers.id"), nullable=False)
    fallback_provider_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    routing_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)  # active | degraded | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EventStorageFolder(Base):
    """Folder mappings per event and per provider."""

    __tablename__ = "event_storage_folders"
    __table_args__ = (UniqueConstraint("event_id", "provider_id", "folder_purpose", name="uq_event_provider_folder"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("storage_providers.id"), nullable=False, index=True)
    folder_purpose: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # memories_photos | memories_videos | memories_other | official_photos | official_videos | exports | root
    provider_folder_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    provider_folder_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MediaAsset(Base):
    """Provider-agnostic registry tracking all stored media assets."""

    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    memory_item_id: Mapped[int | None] = mapped_column(ForeignKey("memory_items.id"), nullable=True, index=True)
    legacy_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id"), nullable=True, index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("storage_providers.id"), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # files_ir | s3 | local
    provider_workspace_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_file_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    provider_folder_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    provider_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    original_name: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    stored_name: Mapped[str] = mapped_column(String(300), unique=True, nullable=False, index=True)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    media_category: Mapped[str] = mapped_column(String(64), default="memories_photo", nullable=False, index=True)  # memories_photo | memories_video | official | export | receipt
    upload_status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False, index=True)  # reserved | uploading | completed | failed | cancelled
    upload_session_ref: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UploadReservation(Base):
    """Tracks active upload sessions, capacity reservations, and direct-to-cloud metadata."""

    __tablename__ = "upload_reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UUID session id
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("storage_providers.id"), nullable=False, index=True)
    upload_mode: Mapped[str] = mapped_column(String(32), default="s3-single", nullable=False)  # s3-single | s3-multipart | single | tus | local
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(16), default="image", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="memories_photo", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="reserved", nullable=False, index=True)  # reserved | completed | expired | cancelled
    provider_session_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    part_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    upload_data_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StorageUsageSnapshot(Base):
    """Historical/cached snapshots of provider usage."""

    __tablename__ = "storage_usage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("storage_providers.id"), nullable=False, index=True)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ok", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StorageRoutingLog(Base):
    """Audit trail for upload routing and fallback decisions."""

    __tablename__ = "storage_routing_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("storage_providers.id"), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # selected | skipped_full | skipped_unreachable | rejected_all
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
