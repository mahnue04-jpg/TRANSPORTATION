"""Synthetic Starter payment/CSV/delivery integration on disposable local PostgreSQL only.

This suite deliberately does not contact Stripe or S3, and never runs outside
a dedicated localhost database and explicit CI/test opt-in.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_customer_csv_jobs as csv_jobs
from app.core.nova.work_revenue import operations_customer_delivery as delivery
from app.core.nova.work_revenue import operations_starter_payment_binding as binding


@pytest.fixture
def engine():
    assert os.getenv("NOVA_STARTER_DISPOSABLE_TEST_DB") == "true"
    # Hardcoded loopback and uniquely named throwaway database: no production URL.
    url = "postgresql+psycopg2://starter_test:starter_test@127.0.0.1:5432/nova_starter_disposable"
    db_engine = sa.create_engine(url)
    assert db_engine.dialect.name == "postgresql"
    assert db_engine.url.host == "127.0.0.1"
    assert db_engine.url.database == "nova_starter_disposable"
    for schema in (binding.metadata, csv_jobs.metadata, delivery.metadata):
        schema.create_all(db_engine)
    try:
        yield db_engine
    finally:
        for schema in (delivery.metadata, csv_jobs.metadata, binding.metadata):
            schema.drop_all(db_engine)
        db_engine.dispose()


def test_verified_payment_matches_only_one_owner_task(engine, monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "true")
    paid = SimpleNamespace(
        id="synthetic-lead", lead_type="anonymous_operations",
        service_plan="starter_49", consent=True, payment_status="paid",
        stripe_checkout_session_id="cs_test_synthetic",
        starter_paid_session_id="cs_test_synthetic",
        stripe_customer_id="cus_test_synthetic",
        organization_name="Synthetic Customer", contact_name="Synthetic Customer",
    )
    monkeypatch.setattr(binding, "_paid_lead", lambda db, lead_id: paid)
    args = dict(
        lead_id=paid.id, organization_id="owner-org", owner_user_id="owner-user",
        engagement_id="eng-001", task_id="task-001",
        client_name="Synthetic Customer",
    )
    with Session(engine) as db:
        binding.bind_paid_starter(db, **args)
        binding.bind_paid_starter(db, **args)  # exact retry must be safe
        binding.require_paid_starter(
            db, organization_id="owner-org", owner_user_id="owner-user",
            engagement_id="eng-001", task_id="task-001",
        )
        with pytest.raises(HTTPException) as err:
            binding.bind_paid_starter(db, **{**args, "task_id": "task-002"})
        assert err.value.status_code == 409
        with pytest.raises(HTTPException):
            binding.require_paid_starter(
                db, organization_id="other-org", owner_user_id="owner-user",
                engagement_id="eng-001", task_id="task-001",
            )
        assert db.execute(sa.select(sa.func.count()).select_from(binding.starter_bindings)).scalar_one() == 1


def test_idempotent_csv_job_scope_is_enforced_in_postgres(engine):
    now = datetime.now(timezone.utc)
    base = dict(
        id="job-one", organization_id="owner-org", owner_user_id="owner-user",
        engagement_id="eng-001", task_id="task-001", request_key="req-001",
        input_sha256="a" * 64, status="PROCESSING",
        created_at=now, updated_at=now,
    )
    with Session(engine) as db:
        db.execute(sa.insert(csv_jobs.jobs).values(**base))
        db.commit()
        with pytest.raises(sa.exc.IntegrityError):
            db.execute(sa.insert(csv_jobs.jobs).values(**{**base, "id": "job-two"}))
            db.commit()
        db.rollback()
        db.execute(sa.insert(csv_jobs.jobs).values(**{
            **base, "id": "job-different-tenant", "organization_id": "other-org",
        }))
        db.commit()
        assert db.execute(sa.select(sa.func.count()).select_from(csv_jobs.jobs)).scalar_one() == 2


def test_private_delivery_account_scope_expiration_and_revocation(engine, monkeypatch):
    # The external S3 adapter is replaced with deterministic synthetic bytes.
    # The real auth + expiration + revocation SQL filters remain under test.
    content = b"Name,Status\\nSynthetic,Done\\n"
    checksum = hashlib.sha256(content).hexdigest()
    now = datetime.now(timezone.utc)
    lead = SimpleNamespace(id="synthetic-lead", work_email="customer@example.invalid")
    job = dict(
        status="APPROVED_FOR_DOWNLOAD", engagement_id="eng-001",
        task_id="task-001", output_sha256=checksum,
    )
    monkeypatch.setattr(delivery, "_guard", lambda db: None)
    monkeypatch.setattr(delivery, "_exact_paid_lead", lambda db, **kwargs: lead)
    monkeypatch.setattr(csv_jobs, "_owned", lambda db, *args, **kwargs: job)
    monkeypatch.setattr(csv_jobs, "download_review", lambda db, **kwargs: content)

    with Session(engine) as db:
        db.execute(sa.insert(delivery.grants).values(
            job_id="job-one", organization_id="owner-org", owner_user_id="owner-user",
            engagement_id="eng-001", task_id="task-001",
            lead_id=lead.id, recipient_user_id="customer-user",
            recipient_organization_id="customer-org", output_sha256=checksum,
            created_at=now, expires_at=now + timedelta(hours=24), revoked_at=None,
        ))
        db.commit()
        good = SimpleNamespace(
            id="customer-user", organization_id="customer-org",
            email="customer@example.invalid", is_active=True, is_verified=True,
        )
        assert delivery.recipient_download(db, job_id="job-one", user=good) == content
        for wrong in (
            SimpleNamespace(**{**vars(good), "id": "wrong-user"}),
            SimpleNamespace(**{**vars(good), "organization_id": "other-org"}),
            SimpleNamespace(**{**vars(good), "email": "wrong@example.invalid"}),
        ):
            with pytest.raises(HTTPException):
                delivery.recipient_download(db, job_id="job-one", user=wrong)

        assert delivery.revoke_grant(
            db, job_id="job-one", owner_org="owner-org", owner_id="owner-user",
        )["grant_status"] == "revoked"
        with pytest.raises(HTTPException) as revoked:
            delivery.recipient_download(db, job_id="job-one", user=good)
        assert revoked.value.status_code == 404

        db.execute(sa.update(delivery.grants).where(
            delivery.grants.c.job_id == "job-one",
        ).values(revoked_at=None, expires_at=now - timedelta(minutes=1)))
        db.commit()
        with pytest.raises(HTTPException) as expired:
            delivery.recipient_download(db, job_id="job-one", user=good)
        assert expired.value.status_code == 404
