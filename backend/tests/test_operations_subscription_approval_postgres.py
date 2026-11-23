"""Disposable PostgreSQL tests for owner approval, revoke and append-only audit.

No hosted Neon database, real credentials, customers or Stripe API calls.
"""
import os
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core.nova.work_revenue.operations_package_usage_ledger import AllowanceBlocked
from app.core.nova.work_revenue.operations_subscription_approvals import (
    approvals, approval_events, record_staging_owner_scope_decision,
    require_saved_owner_scope_approval,
)

URL = os.environ.get("NOVA_OPERATIONS_TEST_POSTGRES_URL", "")


class Base(DeclarativeBase):
    pass


class FakeEngagement(Base):
    __tablename__ = "synthetic_ops_engagements"
    engagement_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    organization_id: Mapped[str] = mapped_column(sa.String(36))
    owner_user_id: Mapped[str] = mapped_column(sa.String(36))


class FakeTask(Base):
    __tablename__ = "synthetic_ops_tasks"
    task_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    engagement_id: Mapped[str] = mapped_column(sa.String(32))
    organization_id: Mapped[str] = mapped_column(sa.String(36))
    owner_user_id: Mapped[str] = mapped_column(sa.String(36))
    review_required: Mapped[bool] = mapped_column(sa.Boolean)


class FakeLead(Base):
    __tablename__ = "synthetic_ops_leads"
    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    lead_type: Mapped[str] = mapped_column(sa.String(48))
    service_plan: Mapped[str] = mapped_column(sa.String(32))
    work_email: Mapped[str] = mapped_column(sa.String(120))


OWNER = SimpleNamespace(user_id="owner_synthetic", organization_id="org_synthetic", role="admin")
SCOPE = dict(organization_id="org_synthetic", owner_user_id="owner_synthetic",
             engagement_id="eng_synthetic", task_id="task_synthetic",
             lead_id="lead_synthetic", task_fingerprint="a"*64)


@pytest.fixture
def db(monkeypatch):
    if not URL or "127.0.0.1" not in URL:
        pytest.skip("Only synthetic localhost PostgreSQL is supported")
    for k, v in (
        ("APP_ENV", "staging"), ("AMICOR_ENVIRONMENT", "staging"),
        ("NOVA_STRIPE_LIVE_ENABLED", "false"),
        ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false"),
        ("NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_STAGING_ENABLED", "true"),
    ):
        monkeypatch.setenv(k, v)

    fake_wr = types.ModuleType("app.core.nova.work_revenue.models")
    fake_wr.NovaWorkEngagement = FakeEngagement
    fake_wr.NovaWorkTask = FakeTask
    fake_leads = types.ModuleType("app.modules.marketing.models")
    fake_leads.MarketingWebsiteLead = FakeLead
    monkeypatch.setitem(sys.modules, "app.core.nova.work_revenue.models", fake_wr)
    monkeypatch.setitem(sys.modules, "app.modules.marketing.models", fake_leads)

    engine = sa.create_engine(URL)
    Base.metadata.create_all(engine)
    approvals.create(engine, checkfirst=True)
    approval_events.create(engine, checkfirst=True)
    with Session(engine) as session:
        session.add(FakeEngagement(engagement_id="eng_synthetic", organization_id="org_synthetic", owner_user_id="owner_synthetic"))
        session.add(FakeTask(task_id="task_synthetic", engagement_id="eng_synthetic", organization_id="org_synthetic",
                             owner_user_id="owner_synthetic", review_required=True))
        session.add(FakeLead(id="lead_synthetic", lead_type="anonymous_operations",
                             service_plan="launch_99", work_email="sample.invalid"))
        session.commit()
    yield engine
    approval_events.drop(engine, checkfirst=True)
    approvals.drop(engine, checkfirst=True)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_approve_revoke_audit_and_reject(db):
    with Session(db) as session:
        with pytest.raises(AllowanceBlocked, match="explicit_owner_approval_missing"):
            require_saved_owner_scope_approval(session, **SCOPE)
        approved = record_staging_owner_scope_decision(
            session, authenticated_user=OWNER, decision="APPROVED",
            organization_id=SCOPE["organization_id"], engagement_id=SCOPE["engagement_id"],
            task_id=SCOPE["task_id"], lead_id=SCOPE["lead_id"],
            task_fingerprint=SCOPE["task_fingerprint"],
        )
        assert approved["decision"] == "APPROVED" and not approved["executed"]
        require_saved_owner_scope_approval(session, **SCOPE)

        revoked = record_staging_owner_scope_decision(
            session, authenticated_user=OWNER, decision="REVOKED",
            organization_id=SCOPE["organization_id"], engagement_id=SCOPE["engagement_id"],
            task_id=SCOPE["task_id"], lead_id=SCOPE["lead_id"],
            task_fingerprint=SCOPE["task_fingerprint"],
        )
        assert revoked["decision"] == "REVOKED"
        with pytest.raises(AllowanceBlocked, match="explicit_owner_approval_missing"):
            require_saved_owner_scope_approval(session, **SCOPE)
        decisions = session.execute(sa.select(approval_events.c.decision).order_by(
            approval_events.c.decided_at, approval_events.c.event_id,
        )).scalars().all()
        assert sorted(decisions) == ["APPROVED", "REVOKED"]


def test_wrong_owner_cannot_write(db):
    with Session(db) as session:
        with pytest.raises(AllowanceBlocked, match="synthetic_task_scope_mismatch"):
            record_staging_owner_scope_decision(
                session, authenticated_user=SimpleNamespace(
                    user_id="other_owner", organization_id="org_synthetic", role="admin"),
                decision="APPROVED", organization_id=SCOPE["organization_id"],
                engagement_id=SCOPE["engagement_id"], task_id=SCOPE["task_id"],
                lead_id=SCOPE["lead_id"], task_fingerprint=SCOPE["task_fingerprint"],
            )
        assert session.scalar(sa.select(sa.func.count()).select_from(approval_events)) == 0


def test_wrong_task_fingerprint_cannot_use_approval(db):
    with Session(db) as session:
        record_staging_owner_scope_decision(
            session, authenticated_user=OWNER, decision="APPROVED",
            organization_id=SCOPE["organization_id"], engagement_id=SCOPE["engagement_id"],
            task_id=SCOPE["task_id"], lead_id=SCOPE["lead_id"],
            task_fingerprint=SCOPE["task_fingerprint"],
        )
        with pytest.raises(AllowanceBlocked, match="explicit_owner_approval_missing"):
            require_saved_owner_scope_approval(session, **{**SCOPE, "task_fingerprint": "b"*64})
