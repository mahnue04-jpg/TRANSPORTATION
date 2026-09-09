"""Nova-owned Business OS records. Not Health, Delivery, Freight, or Government copies."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaBusinessProfile(Base):
    __tablename__ = "nova_business_profiles"
    __table_args__ = (
        Index("ix_nova_biz_profile_id", "profile_id", unique=True),
        Index("ix_nova_biz_profile_org", "organization_id", "owner_user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    profile_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_name: Mapped[str] = mapped_column(String(220), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    dba: Mapped[str | None] = mapped_column(String(220), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, default="llc")
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ein_reference: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    website: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ownership_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    formation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    state_of_formation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    tags: Mapped[str | None] = mapped_column(String(400), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    government_item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessCustomer(Base):
    __tablename__ = "nova_business_customers"
    __table_args__ = (
        Index("ix_nova_biz_customer_id", "customer_id", unique=True),
        Index("ix_nova_biz_customer_org", "organization_id", "owner_user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    customer_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assigned_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="company")
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    role_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False, default="customer")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_contact: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_follow_up: Mapped[date | None] = mapped_column(Date, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessOpportunity(Base):
    __tablename__ = "nova_business_opportunities"
    __table_args__ = (
        Index("ix_nova_biz_opp_id", "opportunity_id", unique=True),
        Index("ix_nova_biz_opp_org", "organization_id", "owner_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    opportunity_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assigned_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(240), nullable=True)
    next_action_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessTask(Base):
    __tablename__ = "nova_business_tasks"
    __table_args__ = (
        Index("ix_nova_biz_task_id", "task_id", unique=True),
        Index("ix_nova_biz_task_org", "organization_id", "owner_user_id", "due_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assigned_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="todo")
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    government_item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessVendor(Base):
    __tablename__ = "nova_business_vendors"
    __table_args__ = (Index("ix_nova_biz_vendor_id", "vendor_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    vendor_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(220), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    website: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    services: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    government_item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessDocument(Base):
    __tablename__ = "nova_business_documents"
    __table_args__ = (Index("ix_nova_biz_doc_id", "document_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="contract")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    counterparty: Mapped[str | None] = mapped_column(String(220), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vendor_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    government_item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessExpense(Base):
    __tablename__ = "nova_business_expenses"
    __table_args__ = (Index("ix_nova_biz_expense_id", "expense_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    expense_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    vendor_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expense_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessMeeting(Base):
    __tablename__ = "nova_business_meetings"
    __table_args__ = (Index("ix_nova_biz_meeting_id", "meeting_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    meeting_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaBusinessActivity(Base):
    __tablename__ = "nova_business_activities"
    __table_args__ = (Index("ix_nova_biz_activity_org", "organization_id", "owner_user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    activity_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
