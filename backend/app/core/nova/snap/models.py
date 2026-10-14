"""Private Snap tables. No public media URLs and no Synapse or Casting rows."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SnapContact(Base):
    __tablename__ = "nova_snap_contacts"
    __table_args__ = (UniqueConstraint("organization_id", "pair_key", name="uq_snap_contact_pair"),)
    contact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    pair_key: Mapped[str] = mapped_column(String(80), index=True)
    requester_user_id: Mapped[str] = mapped_column(String(36), index=True)
    target_user_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapBlock(Base):
    __tablename__ = "nova_snap_blocks"
    __table_args__ = (UniqueConstraint("organization_id", "blocker_user_id", "blocked_user_id", name="uq_snap_block"),)
    block_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    blocker_user_id: Mapped[str] = mapped_column(String(36), index=True)
    blocked_user_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapConversation(Base):
    __tablename__ = "nova_snap_conversations"
    __table_args__ = (UniqueConstraint("organization_id", "pair_key", name="uq_snap_direct_pair"),)
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(80))
    pair_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    next_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapMember(Base):
    __tablename__ = "nova_snap_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_snap_member"),)
    member_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(16))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_read_seq: Mapped[int] = mapped_column(Integer, default=0)


class SnapMessage(Base):
    __tablename__ = "nova_snap_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sender_user_id", "client_message_id", name="uq_snap_message_client"),
        UniqueConstraint("conversation_id", "seq", name="uq_snap_message_seq"),
    )
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    sender_user_id: Mapped[str] = mapped_column(String(36), index=True)
    client_message_id: Mapped[str] = mapped_column(String(80))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    capture_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    untrusted_links: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SnapReceipt(Base):
    __tablename__ = "nova_snap_receipts"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_snap_receipt"),)
    receipt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SnapReport(Base):
    __tablename__ = "nova_snap_reports"
    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    reporter_user_id: Mapped[str] = mapped_column(String(36), index=True)
    target_user_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapCall(Base):
    __tablename__ = "nova_snap_calls"
    call_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    caller_user_id: Mapped[str] = mapped_column(String(36), index=True)
    media: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), index=True)
    ended_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SnapCallParticipant(Base):
    __tablename__ = "nova_snap_call_participants"
    __table_args__ = (UniqueConstraint("call_id", "user_id", name="uq_snap_call_participant"),)
    participant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(16))
    last_quality: Mapped[str] = mapped_column(String(24), default="unknown")
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapSignal(Base):
    __tablename__ = "nova_snap_signals"
    __table_args__ = (
        UniqueConstraint("call_id", "sender_user_id", "client_signal_id", name="uq_snap_signal_client"),
        UniqueConstraint("call_id", "seq", name="uq_snap_signal_seq"),
    )
    signal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(36), index=True)
    sender_user_id: Mapped[str] = mapped_column(String(36))
    seq: Mapped[int] = mapped_column(Integer)
    client_signal_id: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapCapture(Base):
    __tablename__ = "nova_snap_captures"
    capture_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(40))
    content_type: Mapped[str] = mapped_column(String(40))
    byte_size: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
