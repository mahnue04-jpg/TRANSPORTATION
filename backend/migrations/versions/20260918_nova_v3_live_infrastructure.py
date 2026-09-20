"""Additive Nova V3 tables on the canonical V2 Alembic head. Not applied to production.

Revision ID: 20260918_nova_v3_live_infra
Revises: 20260918_work_rev_owner_sched
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260918_nova_v3_live_infra"
down_revision = "20260918_work_rev_owner_sched"
branch_labels = None
depends_on = None


def _create_if_missing(inspector, name: str, factory) -> None:
    if name not in set(inspector.get_table_names()):
        factory()


def _scoped_table(name: str, extra_cols: list, indexes: list) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *extra_cols,
    )
    for index_name, cols, unique in indexes:
        op.create_index(index_name, name, cols, unique=unique)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    specs = (
        (
            "nova_v3_opportunities",
            [
                sa.Column("opportunity_id", sa.String(80), nullable=False),
                sa.Column("fingerprint", sa.String(64), nullable=False),
            ],
            [
                ("ix_nova_v3_opp_id", ["opportunity_id"], True),
                ("ix_nova_v3_opp_org_fp", ["organization_id", "fingerprint"], True),
                ("ix_nova_v3_opp_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_opportunity_sources",
            [sa.Column("source_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_src_id", ["source_id"], True),
                ("ix_nova_v3_src_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_classifications",
            [sa.Column("classification_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_cls_id", ["classification_id"], True),
                ("ix_nova_v3_cls_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_clients",
            [sa.Column("client_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_client_id", ["client_id"], True),
                ("ix_nova_v3_client_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_engagements",
            [sa.Column("engagement_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_eng_id", ["engagement_id"], True),
                ("ix_nova_v3_eng_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_proposals",
            [sa.Column("proposal_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_prop_id", ["proposal_id"], True),
                ("ix_nova_v3_prop_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_approvals",
            [sa.Column("approval_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_apv_id", ["approval_id"], True),
                ("ix_nova_v3_apv_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_work_items",
            [sa.Column("work_item_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_work_id", ["work_item_id"], True),
                ("ix_nova_v3_work_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_messages",
            [sa.Column("message_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_msg_id", ["message_id"], True),
                ("ix_nova_v3_msg_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_invoices",
            [sa.Column("invoice_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_inv_id", ["invoice_id"], True),
                ("ix_nova_v3_inv_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_payment_events",
            [sa.Column("event_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_pay_owner_evt", ["organization_id", "owner_user_id", "event_id"], True),
            ],
        ),
        (
            "nova_v3_corrections",
            [sa.Column("correction_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_cor_id", ["correction_id"], True),
                ("ix_nova_v3_cor_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_reconciliation",
            [sa.Column("reconciliation_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_recon_id", ["reconciliation_id"], True),
                ("ix_nova_v3_recon_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_scheduler_jobs",
            [
                sa.Column("job_id", sa.String(80), nullable=False),
                sa.Column("kind", sa.String(64), nullable=False),
                sa.Column("period_key", sa.String(120), nullable=False),
            ],
            [
                ("ix_nova_v3_job_id", ["job_id"], True),
                ("ix_nova_v3_job_period", ["organization_id", "owner_user_id", "kind", "period_key"], True),
            ],
        ),
        (
            "nova_v3_scheduler_runs",
            [
                sa.Column("run_id", sa.String(80), nullable=False),
                sa.Column("job_id", sa.String(80), nullable=False),
            ],
            [
                ("ix_nova_v3_run_id", ["run_id"], True),
                ("ix_nova_v3_run_owner", ["organization_id", "owner_user_id", "job_id"], False),
            ],
        ),
        (
            "nova_v3_connectors",
            [sa.Column("connector_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_con_owner", ["organization_id", "owner_user_id", "connector_id"], True),
            ],
        ),
        (
            "nova_v3_credentials",
            [sa.Column("credential_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_crd_id", ["credential_id"], True),
                ("ix_nova_v3_crd_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_webhooks",
            [
                sa.Column("event_id", sa.String(80), nullable=False),
                sa.Column("payload_hash", sa.String(64), nullable=False),
            ],
            [
                ("ix_nova_v3_wh_owner_evt", ["organization_id", "owner_user_id", "event_id"], True),
            ],
        ),
        (
            "nova_v3_leads",
            [
                sa.Column("lead_id", sa.String(80), nullable=False),
                sa.Column("fingerprint", sa.String(64), nullable=False),
            ],
            [
                ("ix_nova_v3_lead_id", ["lead_id"], True),
                ("ix_nova_v3_lead_org_fp", ["organization_id", "fingerprint"], True),
                ("ix_nova_v3_lead_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_outreach_messages",
            [sa.Column("message_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_omsg_id", ["message_id"], True),
                ("ix_nova_v3_omsg_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_sequences",
            [sa.Column("sequence_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_seq_id", ["sequence_id"], True),
                ("ix_nova_v3_seq_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_demos",
            [sa.Column("demo_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_demo_id", ["demo_id"], True),
                ("ix_nova_v3_demo_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_quotes",
            [sa.Column("quote_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_quote_id", ["quote_id"], True),
                ("ix_nova_v3_quote_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_customers",
            [sa.Column("customer_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_cust_id", ["customer_id"], True),
                ("ix_nova_v3_cust_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_shield_decisions",
            [sa.Column("decision_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_shd_id", ["decision_id"], True),
                ("ix_nova_v3_shd_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
        (
            "nova_v3_growth_approvals",
            [sa.Column("approval_id", sa.String(80), nullable=False)],
            [
                ("ix_nova_v3_gap_id", ["approval_id"], True),
                ("ix_nova_v3_gap_owner", ["organization_id", "owner_user_id"], False),
            ],
        ),
    )
    for name, extra, indexes in specs:
        _create_if_missing(inspector, name, lambda extra=extra, indexes=indexes, name=name: _scoped_table(name, extra, indexes))
        inspector = sa.inspect(op.get_bind())

    _create_if_missing(
        inspector,
        "nova_v3_monitoring",
        lambda: (
            op.create_table(
                "nova_v3_monitoring",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("organization_id", sa.String(36), nullable=False),
                sa.Column("owner_user_id", sa.String(36), nullable=False),
                sa.Column("payload_json", sa.Text(), nullable=False),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            ),
            op.create_index("ix_nova_v3_mon_owner", "nova_v3_monitoring", ["organization_id", "owner_user_id"]),
        ),
    )
    inspector = sa.inspect(op.get_bind())
    _create_if_missing(
        inspector,
        "nova_v3_audit",
        lambda: (
            op.create_table(
                "nova_v3_audit",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("organization_id", sa.String(36), nullable=False),
                sa.Column("owner_user_id", sa.String(36), nullable=True),
                sa.Column("payload_json", sa.Text(), nullable=False),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            ),
            op.create_index("ix_nova_v3_audit_org", "nova_v3_audit", ["organization_id", "owner_user_id"]),
        ),
    )
    inspector = sa.inspect(op.get_bind())
    _create_if_missing(
        inspector,
        "nova_v3_idempotency",
        lambda: (
            op.create_table(
                "nova_v3_idempotency",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("organization_id", sa.String(36), nullable=False),
                sa.Column("owner_user_id", sa.String(36), nullable=False),
                sa.Column("payload_json", sa.Text(), nullable=False),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("scope", sa.String(64), nullable=False),
                sa.Column("idempotency_key", sa.String(120), nullable=False),
                sa.Column("result_json", sa.Text(), nullable=True),
            ),
            op.create_index(
                "ix_nova_v3_idem_owner",
                "nova_v3_idempotency",
                ["organization_id", "owner_user_id", "scope", "idempotency_key"],
                unique=True,
            ),
        ),
    )


def downgrade() -> None:
    tables = [
        "nova_v3_idempotency",
        "nova_v3_audit",
        "nova_v3_monitoring",
        "nova_v3_growth_approvals",
        "nova_v3_shield_decisions",
        "nova_v3_customers",
        "nova_v3_quotes",
        "nova_v3_demos",
        "nova_v3_sequences",
        "nova_v3_outreach_messages",
        "nova_v3_leads",
        "nova_v3_webhooks",
        "nova_v3_credentials",
        "nova_v3_connectors",
        "nova_v3_scheduler_runs",
        "nova_v3_scheduler_jobs",
        "nova_v3_reconciliation",
        "nova_v3_corrections",
        "nova_v3_payment_events",
        "nova_v3_invoices",
        "nova_v3_messages",
        "nova_v3_work_items",
        "nova_v3_approvals",
        "nova_v3_proposals",
        "nova_v3_engagements",
        "nova_v3_clients",
        "nova_v3_classifications",
        "nova_v3_opportunity_sources",
        "nova_v3_opportunities",
    ]
    inspector = sa.inspect(op.get_bind())
    present = set(inspector.get_table_names())
    for name in tables:
        if name in present:
            op.drop_table(name)
