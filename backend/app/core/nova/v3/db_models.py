"""Canonical V3 SQLAlchemy models on the shared V2 Base. Additive nova_v3_* only."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class _V3Scoped:
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaV3Opportunity(_V3Scoped, Base):
    __tablename__ = "nova_v3_opportunities"
    __table_args__ = (
        Index("ix_nova_v3_opp_id", "opportunity_id", unique=True),
        Index("ix_nova_v3_opp_org_fp", "organization_id", "fingerprint", unique=True),
        Index("ix_nova_v3_opp_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    opportunity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaV3OpportunitySource(_V3Scoped, Base):
    __tablename__ = "nova_v3_opportunity_sources"
    __table_args__ = (
        Index("ix_nova_v3_src_id", "source_id", unique=True),
        Index("ix_nova_v3_src_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Classification(_V3Scoped, Base):
    __tablename__ = "nova_v3_classifications"
    __table_args__ = (
        Index("ix_nova_v3_cls_id", "classification_id", unique=True),
        Index("ix_nova_v3_cls_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    classification_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Client(_V3Scoped, Base):
    __tablename__ = "nova_v3_clients"
    __table_args__ = (
        Index("ix_nova_v3_client_id", "client_id", unique=True),
        Index("ix_nova_v3_client_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    client_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Engagement(_V3Scoped, Base):
    __tablename__ = "nova_v3_engagements"
    __table_args__ = (
        Index("ix_nova_v3_eng_id", "engagement_id", unique=True),
        Index("ix_nova_v3_eng_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    engagement_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Proposal(_V3Scoped, Base):
    __tablename__ = "nova_v3_proposals"
    __table_args__ = (
        Index("ix_nova_v3_prop_id", "proposal_id", unique=True),
        Index("ix_nova_v3_prop_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    proposal_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Approval(_V3Scoped, Base):
    __tablename__ = "nova_v3_approvals"
    __table_args__ = (
        Index("ix_nova_v3_apv_id", "approval_id", unique=True),
        Index("ix_nova_v3_apv_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    approval_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3WorkItem(_V3Scoped, Base):
    __tablename__ = "nova_v3_work_items"
    __table_args__ = (
        Index("ix_nova_v3_work_id", "work_item_id", unique=True),
        Index("ix_nova_v3_work_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    work_item_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Message(_V3Scoped, Base):
    __tablename__ = "nova_v3_messages"
    __table_args__ = (
        Index("ix_nova_v3_msg_id", "message_id", unique=True),
        Index("ix_nova_v3_msg_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    message_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Invoice(_V3Scoped, Base):
    __tablename__ = "nova_v3_invoices"
    __table_args__ = (
        Index("ix_nova_v3_inv_id", "invoice_id", unique=True),
        Index("ix_nova_v3_inv_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    invoice_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3PaymentEvent(_V3Scoped, Base):
    __tablename__ = "nova_v3_payment_events"
    __table_args__ = (
        Index("ix_nova_v3_pay_owner_evt", "organization_id", "owner_user_id", "event_id", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Correction(_V3Scoped, Base):
    __tablename__ = "nova_v3_corrections"
    __table_args__ = (
        Index("ix_nova_v3_cor_id", "correction_id", unique=True),
        Index("ix_nova_v3_cor_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    correction_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Reconciliation(_V3Scoped, Base):
    __tablename__ = "nova_v3_reconciliation"
    __table_args__ = (
        Index("ix_nova_v3_recon_id", "reconciliation_id", unique=True),
        Index("ix_nova_v3_recon_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    reconciliation_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3SchedulerJob(_V3Scoped, Base):
    __tablename__ = "nova_v3_scheduler_jobs"
    __table_args__ = (
        Index("ix_nova_v3_job_id", "job_id", unique=True),
        Index("ix_nova_v3_job_period", "organization_id", "owner_user_id", "kind", "period_key", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    job_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    period_key: Mapped[str] = mapped_column(String(120), nullable=False)


class NovaV3SchedulerRun(_V3Scoped, Base):
    __tablename__ = "nova_v3_scheduler_runs"
    __table_args__ = (
        Index("ix_nova_v3_run_id", "run_id", unique=True),
        Index("ix_nova_v3_run_owner", "organization_id", "owner_user_id", "job_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False)
    job_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Connector(_V3Scoped, Base):
    __tablename__ = "nova_v3_connectors"
    __table_args__ = (
        Index("ix_nova_v3_con_owner", "organization_id", "owner_user_id", "connector_id", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    connector_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Credential(_V3Scoped, Base):
    __tablename__ = "nova_v3_credentials"
    __table_args__ = (
        Index("ix_nova_v3_crd_id", "credential_id", unique=True),
        Index("ix_nova_v3_crd_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    credential_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Webhook(_V3Scoped, Base):
    __tablename__ = "nova_v3_webhooks"
    __table_args__ = (
        Index("ix_nova_v3_wh_owner_evt", "organization_id", "owner_user_id", "event_id", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaV3Monitoring(_V3Scoped, Base):
    __tablename__ = "nova_v3_monitoring"
    __table_args__ = (Index("ix_nova_v3_mon_owner", "organization_id", "owner_user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)


class NovaV3Audit(Base):
    __tablename__ = "nova_v3_audit"
    __table_args__ = (Index("ix_nova_v3_audit_org", "organization_id", "owner_user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaV3Idempotency(_V3Scoped, Base):
    __tablename__ = "nova_v3_idempotency"
    __table_args__ = (
        Index(
            "ix_nova_v3_idem_owner",
            "organization_id",
            "owner_user_id",
            "scope",
            "idempotency_key",
            unique=True,
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class NovaV3Lead(_V3Scoped, Base):
    __tablename__ = "nova_v3_leads"
    __table_args__ = (
        Index("ix_nova_v3_lead_id", "lead_id", unique=True),
        Index("ix_nova_v3_lead_org_fp", "organization_id", "fingerprint", unique=True),
        Index("ix_nova_v3_lead_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    lead_id: Mapped[str] = mapped_column(String(80), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaV3OutreachMessage(_V3Scoped, Base):
    __tablename__ = "nova_v3_outreach_messages"
    __table_args__ = (
        Index("ix_nova_v3_omsg_id", "message_id", unique=True),
        Index("ix_nova_v3_omsg_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    message_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Sequence(_V3Scoped, Base):
    __tablename__ = "nova_v3_sequences"
    __table_args__ = (
        Index("ix_nova_v3_seq_id", "sequence_id", unique=True),
        Index("ix_nova_v3_seq_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Demo(_V3Scoped, Base):
    __tablename__ = "nova_v3_demos"
    __table_args__ = (
        Index("ix_nova_v3_demo_id", "demo_id", unique=True),
        Index("ix_nova_v3_demo_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    demo_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Quote(_V3Scoped, Base):
    __tablename__ = "nova_v3_quotes"
    __table_args__ = (
        Index("ix_nova_v3_quote_id", "quote_id", unique=True),
        Index("ix_nova_v3_quote_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    quote_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3Customer(_V3Scoped, Base):
    __tablename__ = "nova_v3_customers"
    __table_args__ = (
        Index("ix_nova_v3_cust_id", "customer_id", unique=True),
        Index("ix_nova_v3_cust_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    customer_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3ShieldDecision(_V3Scoped, Base):
    __tablename__ = "nova_v3_shield_decisions"
    __table_args__ = (
        Index("ix_nova_v3_shd_id", "decision_id", unique=True),
        Index("ix_nova_v3_shd_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    decision_id: Mapped[str] = mapped_column(String(80), nullable=False)


class NovaV3GrowthApproval(_V3Scoped, Base):
    __tablename__ = "nova_v3_growth_approvals"
    __table_args__ = (
        Index("ix_nova_v3_gap_id", "approval_id", unique=True),
        Index("ix_nova_v3_gap_owner", "organization_id", "owner_user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    approval_id: Mapped[str] = mapped_column(String(80), nullable=False)


V3_MODEL_BY_TABLE = {
    "nova_v3_opportunities": NovaV3Opportunity,
    "nova_v3_opportunity_sources": NovaV3OpportunitySource,
    "nova_v3_classifications": NovaV3Classification,
    "nova_v3_clients": NovaV3Client,
    "nova_v3_engagements": NovaV3Engagement,
    "nova_v3_proposals": NovaV3Proposal,
    "nova_v3_approvals": NovaV3Approval,
    "nova_v3_work_items": NovaV3WorkItem,
    "nova_v3_messages": NovaV3Message,
    "nova_v3_invoices": NovaV3Invoice,
    "nova_v3_payment_events": NovaV3PaymentEvent,
    "nova_v3_corrections": NovaV3Correction,
    "nova_v3_reconciliation": NovaV3Reconciliation,
    "nova_v3_scheduler_jobs": NovaV3SchedulerJob,
    "nova_v3_scheduler_runs": NovaV3SchedulerRun,
    "nova_v3_connectors": NovaV3Connector,
    "nova_v3_credentials": NovaV3Credential,
    "nova_v3_webhooks": NovaV3Webhook,
    "nova_v3_monitoring": NovaV3Monitoring,
    "nova_v3_audit": NovaV3Audit,
    "nova_v3_idempotency": NovaV3Idempotency,
    "nova_v3_leads": NovaV3Lead,
    "nova_v3_outreach_messages": NovaV3OutreachMessage,
    "nova_v3_sequences": NovaV3Sequence,
    "nova_v3_demos": NovaV3Demo,
    "nova_v3_quotes": NovaV3Quote,
    "nova_v3_customers": NovaV3Customer,
    "nova_v3_shield_decisions": NovaV3ShieldDecision,
    "nova_v3_growth_approvals": NovaV3GrowthApproval,
}

V3_TABLES = tuple(V3_MODEL_BY_TABLE.keys())
V3_ORM_TABLES = tuple(model.__table__ for model in V3_MODEL_BY_TABLE.values())
APPEND_ONLY_TABLES = frozenset({"nova_v3_audit", "nova_v3_monitoring", "nova_v3_scheduler_runs"})
