"""Nova Work & Revenue Engine records. Isolated from Health, Delivery, Freight, Stripe, and Lifesaver."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
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
    fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    quoted_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_payment_frequency: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revenue_status: Mapped[str] = mapped_column(String(40), nullable=False, default="NONE")
    invoice_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner_confirmed_payment_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invoice_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_received: Mapped[float | None] = mapped_column(Float, nullable=True)
    expenses: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_status: Mapped[str] = mapped_column(String(40), nullable=False, default="NONE")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_material_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    engagement_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    actor_category: Mapped[str] = mapped_column(String(24), nullable=False, default="NOVA")
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkEngagement(Base):
    __tablename__ = "nova_work_engagements"
    __table_args__ = (Index("ix_nova_work_eng_id", "engagement_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    engagement_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_name: Mapped[str] = mapped_column(String(220), nullable=False)
    service: Mapped[str] = mapped_column(String(220), nullable=False)
    frequency: Mapped[str] = mapped_column(String(40), nullable=False, default="one_time")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_STARTED")
    expected_payment: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_status: Mapped[str] = mapped_column(String(40), nullable=False, default="NONE")
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(220), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    agreed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    quoted_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracted_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    received_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    risks: Mapped[str | None] = mapped_column(Text, nullable=True)
    blockers: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkTask(Base):
    __tablename__ = "nova_work_tasks"
    __table_args__ = (Index("ix_nova_work_task_id", "task_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    engagement_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    responsible_party: Mapped[str] = mapped_column(String(16), nullable=False, default="NOVA")
    classification: Mapped[str] = mapped_column(String(16), nullable=False, default="NOVA")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="NOT_STARTED")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    required_owner_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    deliverable: Mapped[str | None] = mapped_column(String(220), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    depends_on_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkDeliverable(Base):
    __tablename__ = "nova_work_deliverables"
    __table_args__ = (Index("ix_nova_work_deliv_id", "deliverable_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    deliverable_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    engagement_id: Mapped[str] = mapped_column(String(32), nullable=False)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deliverable_type: Mapped[str] = mapped_column(String(40), nullable=False, default="OTHER")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    draft_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    owner_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    owner_confirmed_delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkRevenueEntry(Base):
    __tablename__ = "nova_work_revenue_entries"
    __table_args__ = (Index("ix_nova_work_rev_id", "entry_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    entry_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    engagement_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="ESTIMATED")
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="USD")
    expected_payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    received_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciliation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkRecurringSeries(Base):
    __tablename__ = "nova_work_recurring_series"
    __table_args__ = (
        Index("ix_nova_work_recur_id", "series_id", unique=True),
        Index("ix_nova_work_recur_org", "organization_id", "status", "next_work_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    series_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    engagement_id: Mapped[str] = mapped_column(String(32), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    frequency: Mapped[str] = mapped_column(String(40), nullable=False, default="weekly")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    next_work_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_period_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkRecurringOccurrence(Base):
    __tablename__ = "nova_work_recurring_occurrences"
    __table_args__ = (
        Index("ix_nova_work_occur_id", "occurrence_id", unique=True),
        Index("ix_nova_work_occur_period", "organization_id", "series_id", "period_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    occurrence_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    series_id: Mapped[str] = mapped_column(String(32), nullable=False)
    engagement_id: Mapped[str] = mapped_column(String(32), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkWeeklyReport(Base):
    __tablename__ = "nova_work_weekly_reports"
    __table_args__ = (
        Index("ix_nova_work_report_id", "report_id", unique=True),
        Index("ix_nova_work_report_org", "organization_id", "status", "period_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    report_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    engagement_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="DRAFT")
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    body_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkInvoiceSupport(Base):
    __tablename__ = "nova_work_invoice_supports"
    __table_args__ = (
        Index("ix_nova_work_inv_id", "invoice_support_id", unique=True),
        Index("ix_nova_work_inv_org", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    invoice_support_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    engagement_id: Mapped[str] = mapped_column(String(32), nullable=False)
    client_name: Mapped[str] = mapped_column(String(220), nullable=False)
    work_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deliverable_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    draft_subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    adjustment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="DRAFT")
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkBusinessFact(Base):
    __tablename__ = "nova_work_business_facts"
    __table_args__ = (
        Index("ix_nova_work_fact_id", "fact_record_id", unique=True),
        Index("ix_nova_work_fact_key", "organization_id", "fact_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    fact_record_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_label: Mapped[str] = mapped_column(String(220), nullable=False)
    value_status: Mapped[str] = mapped_column(String(32), nullable=False, default="MISSING")
    value_display: Mapped[str] = mapped_column(String(400), nullable=False, default="[OWNER INPUT REQUIRED]")
    verification_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkDisclosurePolicy(Base):
    __tablename__ = "nova_work_disclosure_policies"
    __table_args__ = (Index("ix_nova_work_disc_id", "policy_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    policy_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    engagement_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_assistance_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    subcontractor_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disclosure_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_acknowledgment_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy_status: Mapped[str] = mapped_column(String(40), nullable=False, default="MANUAL_REVIEW_REQUIRED")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkPlatformPolicy(Base):
    __tablename__ = "nova_work_platform_policies"
    __table_args__ = (Index("ix_nova_work_plat_id", "policy_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    policy_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    opportunity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_label: Mapped[str] = mapped_column(String(120), nullable=False, default="unknown")
    login_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    captcha_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    human_submission_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    terms_restrict_automation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    external_automation_unknown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
