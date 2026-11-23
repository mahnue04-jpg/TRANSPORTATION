"""Release-candidate import and fail-closed gates; no customer traffic or storage."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.nova.work_revenue import operations_customer_delivery as delivery
from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs


class NoDB:
    def get_bind(self):
        raise AssertionError("DB must not be touched before disabled gate")


def test_customer_delivery_off_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED", raising=False)
    with pytest.raises(HTTPException) as exc:
        delivery._guard(NoDB())
    assert exc.value.status_code == 503


def test_private_csv_off_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", raising=False)
    with pytest.raises(jobs.CustomerCSVBlocked) as exc:
        jobs.require_runtime(NoDB())
    assert exc.value.code == 503


def test_customer_csv_requires_postgres(monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "true")
    fake_db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    with pytest.raises(jobs.CustomerCSVBlocked) as exc:
        jobs.require_runtime(fake_db)
    assert exc.value.code == 503


def test_private_delivery_table_has_customer_and_expiry_scope():
    names = set(delivery.grants.c.keys())
    assert {"job_id", "organization_id", "owner_user_id", "lead_id",
            "recipient_user_id", "recipient_organization_id", "expires_at",
            "revoked_at", "output_sha256"} <= names
    assert delivery.grants.c.job_id.primary_key


def test_approved_csv_jobs_table_requires_unique_idempotency_key():
    assert jobs.jobs.c.id.primary_key
    assert {"organization_id", "owner_user_id", "request_key",
            "output_sha256", "status"} <= set(jobs.jobs.c.keys())
    assert any(c.name == "uq_nova_customer_csv_request" for c in jobs.jobs.constraints)
