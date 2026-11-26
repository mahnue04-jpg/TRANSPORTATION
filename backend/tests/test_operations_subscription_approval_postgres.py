"""Disposable PostgreSQL tests for owner approval, revoke and append-only audit.

No hosted Neon database, real credentials, customers or Stripe API calls.
"""
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
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
    payment_status: Mapped[str] = mapped_column(sa.String(32), default="paid")
    stripe_customer_id: Mapped[str] = mapped_column(sa.String(128), default="cus_synthetic")
    stripe_subscription_id: Mapped[str] = mapped_column(sa.String(128), default="sub_synthetic")


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
    migration = Path(__file__).resolve().parents[1] / "migrations" / (
        "review_only_operations_subscription_scope_approvals_staging.sql"
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
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


def test_subscription_csv_binding_exact_identity_replay_and_revoke(db, monkeypatch):
    from datetime import timedelta
    from app.core.nova.work_revenue.operations_package_allowances import VerifiedEntitlement
    from app.core.nova.work_revenue.operations_package_usage_ledger import reservations, reserve_staging_task
    from app.core.nova.work_revenue.operations_subscription_csv_binding import (
        bindings, bind_reserved_csv_task, request_key_for_task,
    )
    monkeypatch.setenv("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_STAGING_ENABLED", "true")
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    with db.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for name in ("review_only_operations_package_task_reservations_staging.sql",
                     "review_only_operations_subscription_csv_bindings_staging.sql"):
            connection.exec_driver_sql((migrations / name).read_text(encoding="utf-8"))
    scope = {k: v for k, v in SCOPE.items() if k != "task_fingerprint"}
    now = datetime.now(timezone.utc)
    entitlement = VerifiedEntitlement(plan="launch_99", customer_id="cus_synthetic",
        paid=True, status="active", subscription_id="sub_synthetic",
        period_start=now-timedelta(days=1), period_end=now+timedelta(days=29))
    try:
        with Session(db) as session:
            record_staging_owner_scope_decision(session, authenticated_user=OWNER,
                decision="APPROVED", **{k: v for k,v in SCOPE.items() if k != "owner_user_id"})
            reservation = reserve_staging_task(session, entitlement=entitlement,
                customer_id=entitlement.customer_id, request_key=request_key_for_task(**scope),
                task_fingerprint=SCOPE["task_fingerprint"], now=now)
            args = dict(**scope, reservation_id=reservation["reservation_id"],
                customer_id=entitlement.customer_id, subscription_id=entitlement.subscription_id,
                plan=entitlement.plan, period_key=entitlement.period_start.isoformat(),
                input_sha256=SCOPE["task_fingerprint"])
            with pytest.raises(AllowanceBlocked, match="exact_csv_reservation_required"):
                bind_reserved_csv_task(session, **{**args, "customer_id": "cus_wrong"})
            session.rollback()
            result = bind_reserved_csv_task(session, **args)
            assert not result["replayed"] and not result["executed"] and not result["delivered"]
            session.commit()
            assert bind_reserved_csv_task(session, **args)["replayed"]
            session.commit()
            assert session.scalar(sa.select(sa.func.count()).select_from(bindings)) == 1
            record_staging_owner_scope_decision(session, authenticated_user=OWNER,
                decision="REVOKED", **{k: v for k,v in SCOPE.items() if k != "owner_user_id"})
            with pytest.raises(AllowanceBlocked, match="explicit_owner_approval_missing"):
                bind_reserved_csv_task(session, **args)
            session.rollback()
            monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "true")
            with pytest.raises(AllowanceBlocked):
                bind_reserved_csv_task(session, **args)
    finally:
        bindings.drop(db, checkfirst=True)
        reservations.drop(db, checkfirst=True)


@pytest.mark.parametrize("plan,amount", [("launch_99", 9900), ("business_299", 29900)])
def test_current_subscription_execution_guard(db, monkeypatch, plan, amount):
    from datetime import timedelta
    from unittest.mock import Mock
    from app.core.nova.work_revenue.operations_package_allowances import VerifiedEntitlement
    from app.core.nova.work_revenue.operations_package_usage_ledger import reservations, reserve_staging_task
    from app.core.nova.work_revenue.operations_subscription_csv_binding import (
        bindings, bind_reserved_csv_task, request_key_for_task,
    )
    from app.core.nova.work_revenue.operations_subscription_execution_guard import (
        require_current_bound_subscription,
    )
    for flag in ("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED",
                 "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_STAGING_ENABLED",
                 "NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_STAGING_ENABLED"):
        monkeypatch.setenv(flag, "true")
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    with db.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for name in ("review_only_operations_package_task_reservations_staging.sql",
                     "review_only_operations_subscription_csv_bindings_staging.sql"):
            connection.exec_driver_sql((migrations / name).read_text(encoding="utf-8"))
    now = datetime(2026, 11, 25, tzinfo=timezone.utc)
    start, end = now-timedelta(days=1), now+timedelta(days=29)
    scope = {k:v for k,v in SCOPE.items() if k != "task_fingerprint"}
    guard_scope = {k:v for k,v in scope.items() if k != "lead_id"}
    guard_scope.update(input_sha256=SCOPE["task_fingerprint"], now=now)
    decision_scope = {k:v for k,v in SCOPE.items() if k != "owner_user_id"}
    entitlement = VerifiedEntitlement(plan=plan, customer_id="cus_synthetic",
        paid=True, status="active", subscription_id="sub_synthetic",
        period_start=start, period_end=end)
    sub = dict(id="sub_synthetic", customer="cus_synthetic", livemode=False, status="active",
        metadata=dict(nova_product="nova_anonymous_operations_agent",
                      nova_agent_lead_id=scope["lead_id"], nova_agent_plan=plan),
        items={"data":[dict(quantity=1, price="price_synthetic",
                             current_period_start=int(start.timestamp()),
                             current_period_end=int(end.timestamp()))]},
        latest_invoice=dict(status="paid", paid=True, livemode=False, currency="usd",
            amount_paid=amount, subscription="sub_synthetic", customer="cus_synthetic",
            lines={"data":[dict(subscription="sub_synthetic",
                               period=dict(start=int(start.timestamp()), end=int(end.timestamp())))]}))
    client = Mock()
    client.retrieve_subscription.return_value = sub
    client.verify_subscription_payment.return_value = True
    billing = types.ModuleType("app.modules.marketing.operations_billing")
    billing.agent_checkout_mode = lambda: "test"
    billing.subscription_test_price = lambda plan: "price_synthetic"
    billing.get_agent_stripe_client = lambda: client
    monkeypatch.setitem(sys.modules, "app.modules.marketing.operations_billing", billing)
    try:
        with Session(db) as session:
            session.get(FakeLead, scope["lead_id"]).service_plan = plan
            session.commit()
            record_staging_owner_scope_decision(session, authenticated_user=OWNER,
                decision="APPROVED", **decision_scope)
            result = reserve_staging_task(session, entitlement=entitlement,
                customer_id=entitlement.customer_id, request_key=request_key_for_task(**scope),
                task_fingerprint=SCOPE["task_fingerprint"], now=now)
            bind_reserved_csv_task(session, **scope, reservation_id=result["reservation_id"],
                customer_id=entitlement.customer_id, subscription_id=entitlement.subscription_id,
                plan=plan, period_key=start.isoformat(), input_sha256=SCOPE["task_fingerprint"])
            session.commit()
            assert require_current_bound_subscription(session, **guard_scope)["authorized"]
            session.rollback()
            client.verify_subscription_payment.return_value = False
            with pytest.raises(AllowanceBlocked, match="subscription_payment_reversed_or_unverified"):
                require_current_bound_subscription(session, **guard_scope)
            session.rollback()
            client.verify_subscription_payment.return_value = True
            for field, value in (("status", "canceled"), ("livemode", True),
                                 ("customer", "cus_wrong")):
                previous = sub[field]
                sub[field] = value
                with pytest.raises(AllowanceBlocked, match="subscription_not_currently_entitled"):
                    require_current_bound_subscription(session, **guard_scope)
                session.rollback()
                sub[field] = previous
            sub["latest_invoice"]["status"] = "open"
            with pytest.raises(AllowanceBlocked, match="subscription_not_currently_entitled"):
                require_current_bound_subscription(session, **guard_scope)
            session.rollback()
            sub["latest_invoice"]["status"] = "paid"
            with pytest.raises(AllowanceBlocked, match="exact_csv_binding_required"):
                require_current_bound_subscription(session, **{**guard_scope, "input_sha256":"b"*64})
            session.rollback()
            record_staging_owner_scope_decision(session, authenticated_user=OWNER,
                decision="REVOKED", **decision_scope)
            with pytest.raises(AllowanceBlocked, match="explicit_owner_approval_missing"):
                require_current_bound_subscription(session, **guard_scope)
            session.rollback()
    finally:
        bindings.drop(db, checkfirst=True)
        reservations.drop(db, checkfirst=True)
