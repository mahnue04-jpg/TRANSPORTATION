"""Real SQL/PostgreSQL synthetic Starter Task payment-to-customer delivery acceptance.

Uses only the isolated loopback CI PostgreSQL service, fake in-memory file
storage, synthetic user identities and synthetic payment records. NEVER
contacts Stripe, creates production accounts or delivers customer files.
"""
from __future__ import annotations

import hashlib
import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import User as PlatformUser
from app.modules.marketing.models import MarketingWebsiteLead
from app.core.nova.work_revenue import operations_customer_csv_jobs as csv
from app.core.nova.work_revenue import operations_customer_delivery as delivery
from app.core.nova.work_revenue.operations_starter_payment_binding import starter_bindings


class MemoryPrivateStore:
    def __init__(self):
        self.objects = {}

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        raw = stream.read()
        self.objects[key] = raw
        return "synthetic-private", key, len(raw)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        self.objects.pop(storage_ref, None)


@pytest.fixture
def isolated_postgres(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if "postgresql" not in url or "127.0.0.1" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("Delivery integration requires ephemeral loopback PostgreSQL")
        pytest.skip("Ephemeral CI PostgreSQL not available")
    engine = sa.create_engine(url)
    tables = [
        PlatformUser.__table__, MarketingWebsiteLead.__table__,
        starter_bindings, csv.jobs, delivery.grants,
    ]
    for table in reversed(tables):
        table.drop(engine, checkfirst=True)
    for table in tables:
        table.create(engine, checkfirst=False)

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    fake = MemoryPrivateStore()
    monkeypatch.setattr(csv, "_store", lambda: fake)
    try:
        yield engine, fake
    finally:
        for table in reversed(tables):
            table.drop(engine, checkfirst=True)
        engine.dispose()


def seed_paid_job(db):
    db.execute(sa.insert(PlatformUser.__table__).values(
        id="synthetic-recipient", email="buyer@example.invalid",
        hashed_password="no-login-test-record", role="staff",
        organization_id="synthetic-customer-org", is_active=True, is_verified=True,
    ))
    db.execute(sa.insert(MarketingWebsiteLead.__table__).values(
        id="synthetic-lead", lead_type="anonymous_operations", status="qualified",
        contact_name="Synthetic Buyer", organization_name="Synthetic Buyer Company",
        work_email="buyer@example.invalid", consent=True,
        service_plan="starter_49", payment_status="paid",
        stripe_customer_id="cus_synthetic", stripe_checkout_session_id="cs_synthetic",
        starter_paid_session_id="cs_synthetic",
        starter_payment_intent_id="pi_synthetic", starter_entitlement_state="active",
    ))
    db.execute(sa.insert(starter_bindings).values(
        lead_id="synthetic-lead", organization_id="synthetic-owner-org",
        owner_user_id="synthetic-owner", engagement_id="synthetic-eng",
        task_id="synthetic-task", stripe_checkout_session_id="cs_synthetic",
    ))
    db.commit()
    result = csv.submit_review_job(
        db, org="synthetic-owner-org", owner="synthetic-owner",
        engagement_id="synthetic-eng", task_id="synthetic-task",
        request_key="synthetic-acceptance-1", raw=b"Name\nAda\nAda\n",
    )
    csv.review_job(
        db, org="synthetic-owner-org", owner="synthetic-owner",
        job_id=result["job_id"], approve=True,
    )
    return result["job_id"]


def test_postgres_payment_bound_approved_csv_customer_download(isolated_postgres):
    engine, fake = isolated_postgres
    with Session(engine) as db:
        job_id = seed_paid_job(db)
        granted = delivery.issue_grant(
            db, job_id=job_id, owner_org="synthetic-owner-org",
            owner_id="synthetic-owner", recipient_user_id="synthetic-recipient",
        )
        assert granted["grant_status"] == "issued"
        assert granted["delivered"] is False
        recipient = db.get(PlatformUser, "synthetic-recipient")
        assert delivery.recipient_download(
            db, job_id=job_id, user=recipient,
        ) == b"Name\nAda\n"
        wrong_recipient = PlatformUser(
            id="different-user", email="buyer@example.invalid",
            hashed_password="synthetic", organization_id="synthetic-customer-org",
            is_active=True, is_verified=True,
        )
        with pytest.raises(delivery.HTTPException) as exc:
            delivery.recipient_download(db, job_id=job_id, user=wrong_recipient)
        assert exc.value.status_code == 404
        delivery.revoke_grant(
            db, job_id=job_id, owner_org="synthetic-owner-org",
            owner_id="synthetic-owner",
        )
        with pytest.raises(delivery.HTTPException) as revoked:
            delivery.recipient_download(db, job_id=job_id, user=recipient)
        assert revoked.value.status_code == 404


def test_postgres_delivery_rejects_changed_payment(isolated_postgres):
    engine, fake = isolated_postgres
    with Session(engine) as db:
        job_id = seed_paid_job(db)
        delivery.issue_grant(
            db, job_id=job_id, owner_org="synthetic-owner-org",
            owner_id="synthetic-owner", recipient_user_id="synthetic-recipient",
        )
        lead = db.get(MarketingWebsiteLead, "synthetic-lead")
        lead.payment_status = "failed"
        db.commit()
        recipient = db.get(PlatformUser, "synthetic-recipient")
        with pytest.raises(delivery.HTTPException) as exc:
            delivery.recipient_download(db, job_id=job_id, user=recipient)
        assert exc.value.status_code == 409


def test_owner_can_reissue_only_to_same_customer_after_revoke(isolated_postgres):
    engine, _ = isolated_postgres
    with Session(engine) as db:
        job_id = seed_paid_job(db)
        kwargs = dict(
            job_id=job_id, owner_org="synthetic-owner-org",
            owner_id="synthetic-owner", recipient_user_id="synthetic-recipient",
        )
        first = delivery.issue_grant(db, **kwargs)
        assert first["grant_status"] == "issued"
        with pytest.raises(delivery.HTTPException) as still_active:
            delivery.issue_grant(db, **kwargs)
        assert still_active.value.status_code == 409
        delivery.revoke_grant(
            db, job_id=job_id, owner_org="synthetic-owner-org",
            owner_id="synthetic-owner",
        )
        second = delivery.issue_grant(db, **kwargs)
        assert second["grant_status"] == "issued"
        row = db.execute(sa.select(delivery.grants).where(
            delivery.grants.c.job_id == job_id,
        )).mappings().one()
        assert row["recipient_user_id"] == "synthetic-recipient"
        assert row["revoked_at"] is None


def test_reissue_does_not_redirect_existing_grant_to_other_account(
    isolated_postgres,
):
    engine, _ = isolated_postgres
    with Session(engine) as db:
        job_id = seed_paid_job(db)
        delivery.issue_grant(
            db, job_id=job_id, owner_org="synthetic-owner-org",
            owner_id="synthetic-owner", recipient_user_id="synthetic-recipient",
        )
        delivery.revoke_grant(
            db, job_id=job_id, owner_org="synthetic-owner-org",
            owner_id="synthetic-owner",
        )
        # Simulate a changed billing email without granting access to the old
        # artifact's recipient; the earlier grant must not be redirected.
        lead = db.get(MarketingWebsiteLead, "synthetic-lead")
        lead.work_email = "other-buyer@example.invalid"
        db.execute(sa.insert(PlatformUser.__table__).values(
            id="unrelated-user", email="other-buyer@example.invalid",
            hashed_password="synthetic", role="staff",
            organization_id="different-customer-org",
            is_active=True, is_verified=True,
        ))
        db.commit()
        with pytest.raises(delivery.HTTPException) as denied:
            delivery.issue_grant(
                db, job_id=job_id, owner_org="synthetic-owner-org",
                owner_id="synthetic-owner", recipient_user_id="unrelated-user",
            )
        assert denied.value.status_code == 409
        row = db.execute(sa.select(delivery.grants).where(
            delivery.grants.c.job_id == job_id,
        )).mappings().one()
        assert row["recipient_user_id"] == "synthetic-recipient"
        assert row["revoked_at"] is not None


@pytest.mark.parametrize("state", ["refunded", "disputed"])
def test_postgres_reversed_entitlement_denies_existing_delivery(isolated_postgres, state):
    engine, _ = isolated_postgres
    with Session(engine) as db:
        job_id = seed_paid_job(db)
        delivery.issue_grant(db, job_id=job_id, owner_org="synthetic-owner-org", owner_id="synthetic-owner", recipient_user_id="synthetic-recipient")
        lead = db.get(MarketingWebsiteLead, "synthetic-lead")
        lead.starter_entitlement_state = state
        db.commit()
        with pytest.raises(delivery.HTTPException) as denied:
            delivery.recipient_download(db, job_id=job_id, user=db.get(PlatformUser, "synthetic-recipient"))
        assert denied.value.status_code == 409


def test_owner_grant_resolves_customer_from_paid_order(isolated_postgres, monkeypatch):
    from types import SimpleNamespace
    from app.core.nova.work_revenue import operations_delivery_authorization as api

    engine, _ = isolated_postgres
    monkeypatch.setattr(api, "_check_saved_csv_assignment", lambda *args, **kw: None)
    monkeypatch.setattr(api, "_reject_queued_job_in_legacy_path", lambda *args, **kw: None)
    with Session(engine) as db:
        job_id = seed_paid_job(db)
        result = delivery.owner_issue_customer_delivery_by_paid_order(
            job_id=job_id,
            owner_action="issue-approved-csv-delivery",
            owner=SimpleNamespace(
                user_id="synthetic-owner", organization_id="synthetic-owner-org",
            ),
            db=db,
        )
        assert result["grant_status"] == "issued"
        stored = db.execute(sa.select(delivery.grants).where(
            delivery.grants.c.job_id == job_id,
        )).mappings().one()
        assert stored["recipient_user_id"] == "synthetic-recipient"
        assert stored["recipient_organization_id"] == "synthetic-customer-org"


def test_owner_grant_rejects_missing_verified_customer(isolated_postgres, monkeypatch):
    from types import SimpleNamespace
    from app.core.nova.work_revenue import operations_delivery_authorization as api

    engine, _ = isolated_postgres
    monkeypatch.setattr(api, "_check_saved_csv_assignment", lambda *args, **kw: None)
    monkeypatch.setattr(api, "_reject_queued_job_in_legacy_path", lambda *args, **kw: None)
    with Session(engine) as db:
        job_id = seed_paid_job(db)
        user = db.get(PlatformUser, "synthetic-recipient")
        user.is_verified = False
        db.commit()
        with pytest.raises(delivery.HTTPException) as denied:
            delivery.owner_issue_customer_delivery_by_paid_order(
                job_id=job_id,
                owner_action="issue-approved-csv-delivery",
                owner=SimpleNamespace(
                    user_id="synthetic-owner", organization_id="synthetic-owner-org",
                ),
                db=db,
            )
        assert denied.value.status_code == 409
        assert db.execute(sa.select(delivery.grants)).mappings().all() == []




@pytest.mark.parametrize("plan,amount", [("launch_99", 9900), ("business_299", 29900)])
def test_subscription_execution_and_delivery(isolated_postgres, monkeypatch, plan, amount):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.modules.marketing import operations_billing as billing
    from app.core.nova.work_revenue import operations_delivery_authorization as assignment
    from app.core.nova.work_revenue.operations_package_usage_ledger import (
        AllowanceBlocked, reservations, reserve_staging_task,
    )
    from app.core.nova.work_revenue.operations_package_allowances import VerifiedEntitlement
    from app.core.nova.work_revenue.operations_subscription_approvals import approvals
    from app.core.nova.work_revenue.operations_subscription_csv_binding import (
        bindings, bind_reserved_csv_task, request_key_for_task,
    )
    from app.core.nova.work_revenue.operations_subscription_csv_execution import execute_reserved_subscription_csv
    from app.core.nova.work_revenue.operations_subscription_delivery import (
        issue_subscription_grant, download_subscription_grant, revoke_subscription_grant,
    )

    engine, _ = isolated_postgres
    for flag in ("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED",
                 "NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_STAGING_ENABLED",
                 "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_STAGING_ENABLED",
                 "NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_STAGING_ENABLED",
                 "NOVA_OPERATIONS_SUBSCRIPTION_DELIVERY_STAGING_ENABLED"):
        monkeypatch.setenv(flag, "true")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")
    # Saved-work authorization is tested separately. Here use actual SQL
    # reservation, approval, job and grant tables and the real entitlement guard.
    monkeypatch.setattr(assignment, "_check_saved_csv_assignment", lambda *a, **kw: None)
    monkeypatch.setattr(assignment, "_reject_queued_job_in_legacy_path", lambda *a, **kw: None)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start, end = now-timedelta(days=1), now+timedelta(days=29)
    scope = dict(organization_id="synthetic-owner-org", owner_user_id="synthetic-owner",
                 engagement_id="synthetic-eng", task_id="synthetic-task", lead_id="synthetic-lead")
    owner = SimpleNamespace(user_id=scope["owner_user_id"], organization_id=scope["organization_id"], role="admin")
    buyer = SimpleNamespace(user_id="synthetic-recipient", organization_id="synthetic-customer-org")
    wrong = SimpleNamespace(user_id="synthetic-other", organization_id="synthetic-other-org")
    raw = b"Name\nAda\nAda\n"
    fingerprint = hashlib.sha256(raw).hexdigest()
    entitlement = VerifiedEntitlement(plan=plan, customer_id="cus_synthetic", paid=True,
        status="active", subscription_id="sub_synthetic", period_start=start, period_end=end)
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
    stripe = Mock()
    stripe.retrieve_subscription.return_value = sub
    stripe.verify_subscription_payment.return_value = True
    monkeypatch.setattr(billing, "agent_checkout_mode", lambda: "test")
    monkeypatch.setattr(billing, "subscription_test_price", lambda plan: "price_synthetic")
    monkeypatch.setattr(billing, "get_agent_stripe_client", lambda: stripe)
    tables = [reservations, approvals, bindings]
    for table in tables:
        table.create(engine, checkfirst=True)
    try:
        with Session(engine) as db:
            for user, email in ((buyer, "buyer@example.invalid"), (wrong, "other@example.invalid")):
                db.execute(sa.insert(PlatformUser.__table__).values(
                    id=user.user_id, email=email, hashed_password="synthetic-only",
                    role="staff", organization_id=user.organization_id, is_active=True, is_verified=True))
            db.execute(sa.insert(MarketingWebsiteLead.__table__).values(
                id=scope["lead_id"], lead_type="anonymous_operations", status="qualified",
                contact_name="Synthetic Buyer", organization_name="Synthetic Buyer Company",
                work_email="buyer@example.invalid", consent=True, service_plan=plan,
                payment_status="paid", stripe_customer_id="cus_synthetic",
                stripe_subscription_id="sub_synthetic"))
            db.execute(sa.insert(approvals).values(approval_id="synthetic-approval",
                **scope, task_fingerprint=fingerprint, decision="APPROVED", decided_at=now))
            db.commit()
            reservation = reserve_staging_task(db, entitlement=entitlement,
                customer_id=entitlement.customer_id, request_key=request_key_for_task(**scope),
                task_fingerprint=fingerprint, now=now)
            bind_reserved_csv_task(db, **scope, reservation_id=reservation["reservation_id"],
                customer_id=entitlement.customer_id, subscription_id=entitlement.subscription_id,
                plan=plan, period_key=start.isoformat(), input_sha256=fingerprint)
            db.commit()
            args = dict(authenticated_user=owner, engagement_id=scope["engagement_id"],
                        task_id=scope["task_id"], raw=raw)
            stripe.verify_subscription_payment.return_value = False
            with pytest.raises(AllowanceBlocked, match="subscription_payment_reversed_or_unverified"):
                execute_reserved_subscription_csv(db, **args)
            assert db.scalar(sa.select(sa.func.count()).select_from(csv.jobs)) == 0
            db.rollback()
            stripe.verify_subscription_payment.return_value = True
            result = execute_reserved_subscription_csv(db, **args)
            job = result["job_id"]
            assert result["status"] == "AWAITING_REVIEW"
            assert execute_reserved_subscription_csv(db, **args)["job_id"] == job
            assert db.scalar(sa.select(sa.func.count()).select_from(reservations)) == 1
            assert db.scalar(sa.select(sa.func.count()).select_from(csv.jobs)) == 1
            grant_args = dict(authenticated_owner=owner, job_id=job,
                              recipient_user_id=buyer.user_id, explicit_approval=True)
            with pytest.raises(AllowanceBlocked, match="approved_subscription_artifact_required"):
                issue_subscription_grant(db, **grant_args)
            csv.review_job(db, org=owner.organization_id, owner=owner.user_id, job_id=job, approve=True)
            with pytest.raises(AllowanceBlocked, match="verified_subscription_recipient_required"):
                issue_subscription_grant(db, **{**grant_args, "recipient_user_id":wrong.user_id})
            assert issue_subscription_grant(db, **grant_args)["grant_status"] == "issued"
            assert download_subscription_grant(db, authenticated_recipient=buyer, job_id=job) == b"Name\nAda\n"
            with pytest.raises(delivery.HTTPException) as denied:
                download_subscription_grant(db, authenticated_recipient=wrong, job_id=job)
            assert denied.value.status_code == 404
            stripe.verify_subscription_payment.return_value = False
            with pytest.raises(AllowanceBlocked, match="subscription_payment_reversed_or_unverified"):
                download_subscription_grant(db, authenticated_recipient=buyer, job_id=job)
            db.rollback()
            stripe.verify_subscription_payment.return_value = True
            sub["status"] = "canceled"
            with pytest.raises(AllowanceBlocked, match="subscription_not_currently_entitled"):
                download_subscription_grant(db, authenticated_recipient=buyer, job_id=job)
            assert revoke_subscription_grant(db, authenticated_owner=owner, job_id=job)["grant_status"] == "revoked"
            sub["status"] = "active"
            with pytest.raises(delivery.HTTPException) as revoked:
                download_subscription_grant(db, authenticated_recipient=buyer, job_id=job)
            assert revoked.value.status_code == 404
    finally:
        for table in reversed(tables):
            table.drop(engine, checkfirst=True)
