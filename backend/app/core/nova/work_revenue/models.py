"""Nova Work & Revenue Engine records. Isolated from Health, Delivery, Freight, Stripe, and Lifesaver."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaWorkOpportunity(Base):
    __tablename__ = "nova_work_opportunities"
    __table_args__ = (
        Index("ix_nova_work_opp_id", "opportunity_id", unique=True),
        Index("ix_nova_work_opp_org", "organization_id", "owner_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    opportunity_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="manual")
    source_url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    company_name: Mapped[str] = mapped_column(String(220), nullable=False)
    opportunity_title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(220), nullable=True)
    remote_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    engagement_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    compensation_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    compensation_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    compensation_period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    physical_presence_required: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    application_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCOVERED")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualification_outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    qualification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkApplication(Base):
    __tablename__ = "nova_work_applications"
    __table_args__ = (
        Index("ix_nova_work_app_id", "application_id", unique=True),
        Index("ix_nova_work_app_org", "organization_id", "owner_user_id", "approval_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    application_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    opportunity_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    applicant_party: Mapped[str] = mapped_column(String(80), nullable=False, default="AMICOR")
    approval_state: Mapped[str] = mapped_column(String(40), nullable=False, default="DRAFT")
    approved_for_future_submission: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    externally_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_submission_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkMaterial(Base):
    __tablename__ = "nova_work_materials"
    __table_args__ = (Index("ix_nova_work_mat_id", "material_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    material_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    application_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    owner_input_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkOwnerAction(Base):
    __tablename__ = "nova_work_owner_actions"
    __table_args__ = (Index("ix_nova_work_action_org", "organization_id", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    action_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    application_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    display_label: Mapped[str] = mapped_column(String(40), nullable=False, default="OWNER ACTION REQUIRED")
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkStatusHistory(Base):
    __tablename__ = "nova_work_status_history"
    __table_args__ = (Index("ix_nova_work_hist_ref", "organization_id", "ref_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    history_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(24), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkAuditEvent(Base):
    __tablename__ = "nova_work_audit_events"
    __table_args__ = (Index("ix_nova_work_audit_org", "organization_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    event_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    summary: Mapped[str] = mapped_column(String(400), nullable=False)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
