"""Nova-owned government organization records. Not Health, Delivery, or Freight."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaGovernmentWorkItem(Base):
    __tablename__ = "nova_government_work_items"
    __table_args__ = (
        Index("ix_nova_gov_item_id", "item_id", unique=True),
        Index("ix_nova_gov_item_org_owner", "organization_id", "owner_user_id", "updated_at"),
        Index("ix_nova_gov_item_org_due", "organization_id", "due_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    item_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assigned_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    agency: Mapped[str | None] = mapped_column(String(220), nullable=True)
    government_level: Mapped[str] = mapped_column(String(24), nullable=False, default="state")
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    county: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="compliance")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="researching")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_filed")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaGovernmentChecklistItem(Base):
    __tablename__ = "nova_government_checklist_items"
    __table_args__ = (Index("ix_nova_gov_check_item", "item_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    checklist_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    item_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    label: Mapped[str] = mapped_column(String(220), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaGovernmentSource(Base):
    __tablename__ = "nova_government_sources"
    __table_args__ = (Index("ix_nova_gov_source_item", "item_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    item_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agency_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    page_title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(180), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unverified")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaGovernmentProgram(Base):
    __tablename__ = "nova_government_programs"
    __table_args__ = (
        Index("ix_nova_gov_program_id", "program_id", unique=True),
        Index("ix_nova_gov_program_org", "organization_id", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    program_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    program_name: Mapped[str] = mapped_column(String(240), nullable=False)
    agency: Mapped[str | None] = mapped_column(String(220), nullable=True)
    eligibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_range: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="researching")
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_info: Mapped[str | None] = mapped_column(String(320), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
