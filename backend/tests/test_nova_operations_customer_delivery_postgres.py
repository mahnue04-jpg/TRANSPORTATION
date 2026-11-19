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


def test_owner_grant_resolves_customer_from_paid_order(isolated_postgres, monkeypatch):
    from types import SimpleNamespace
    from app.core.nova.work_revenue import operations_owner_csv_api as api

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
    from app.core.nova.work_revenue import operations_owner_csv_api as api

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
