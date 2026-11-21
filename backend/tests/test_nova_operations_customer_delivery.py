"""Isolated customer delivery HTTP denials; no production DB, private storage or payments."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.work_revenue.operations_customer_delivery import (
    customer_delivery_router, owner_delivery_router,
)
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.auth import get_current_user_context
from app.core.nova.router import require_nova_access
from app.db.session import get_db


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED", raising=False)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=__import__("sqlalchemy").pool.StaticPool,
    )
    user = SimpleNamespace(
        user_id="synthetic-customer", organization_id="customer-org",
        email="customer@example.invalid",
    )
    owner = SimpleNamespace(
        user_id="synthetic-owner", organization_id="owner-org",
        email="owner@example.invalid",
    )
    app = FastAPI()
    app.include_router(customer_delivery_router)
    app.include_router(owner_delivery_router)
    app.dependency_overrides[get_current_user_context] = lambda: user
    app.dependency_overrides[require_nova_access] = lambda: owner
    app.dependency_overrides[require_work_revenue_owner] = lambda: owner

    def session():
        class DenyUnconfiguredDatabase:
            def get(self, model, identifier):
                return None
        yield DenyUnconfiguredDatabase()

    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_delivery_grant_requires_explicit_owner_action(harness):
    response = harness.post(
        "/api/nova/work/operations/owner/jobs/synthetic-job/delivery-grants/recipients/synthetic-user"
    )
    assert response.status_code == 403


def test_delivery_revocation_requires_explicit_owner_action(harness):
    response = harness.post(
        "/api/nova/work/operations/owner/jobs/synthetic-job/delivery-grants/revoke"
    )
    assert response.status_code == 403


def test_customer_download_cannot_reach_unconfigured_database(harness):
    # Identity lookup may reject first, but the route never returns file bytes.
    response = harness.get(
        "/api/nova/work/operations/customer/deliveries/synthetic-job"
    )
    assert response.status_code in {403, 503}
    assert b"synthetic-csv-content" not in response.content


def test_owner_cannot_issue_delivery_while_disabled(harness):
    response = harness.post(
        "/api/nova/work/operations/owner/jobs/synthetic-job/delivery-grants/recipients/synthetic-user",
        headers={"X-Nova-Owner-Action": "issue-approved-csv-delivery"},
    )
    assert response.status_code == 503


def test_owner_cannot_revoke_delivery_without_enabled_private_runtime(harness):
    response = harness.post(
        "/api/nova/work/operations/owner/jobs/synthetic-job/delivery-grants/revoke",
        headers={"X-Nova-Owner-Action": "revoke-csv-delivery"},
    )
    assert response.status_code == 503


class _DeliveryGrantResult:
    def __init__(self, grant):
        self._grant = grant

    def mappings(self):
        return self

    def first(self):
        return self._grant


class _DeliveryGrantDB:
    def __init__(self, grant):
        self.grant = grant

    def execute(self, _statement):
        return _DeliveryGrantResult(self.grant)


def _synthetic_grant():
    from datetime import datetime, timedelta, timezone
    return {
        "job_id": "synthetic-job", "organization_id": "amicor-org",
        "owner_user_id": "amicor-owner", "engagement_id": "eng-1",
        "task_id": "task-1", "lead_id": "lead-1",
        "recipient_user_id": "customer-1",
        "recipient_organization_id": "customer-org",
        "output_sha256": "a" * 64,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
        "revoked_at": None,
    }


def _synthetic_customer(user_id="customer-1", org="customer-org"):
    return SimpleNamespace(
        id=user_id, organization_id=org, email="customer@example.invalid",
        is_active=True, is_verified=True,
    )


def test_customer_delivery_matches_paid_recipient_and_approved_artifact(monkeypatch):
    from app.core.nova.work_revenue import operations_customer_delivery as delivery
    grant = _synthetic_grant()
    monkeypatch.setattr(delivery, "_guard", lambda db: None)
    monkeypatch.setattr(
        delivery, "_exact_paid_lead",
        lambda *args, **kw: SimpleNamespace(id="lead-1", work_email="customer@example.invalid"),
    )
    monkeypatch.setattr(
        delivery.csv_jobs, "_owned",
        lambda *args, **kw: {
            "status": "APPROVED_FOR_DOWNLOAD",
            "engagement_id": "eng-1", "task_id": "task-1",
            "output_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        delivery.csv_jobs, "download_review",
        lambda *args, **kw: b"name\\nSynthetic\\n",
    )
    db = _DeliveryGrantDB(grant)
    assert delivery.recipient_download(
        db, job_id="synthetic-job", user=_synthetic_customer()
    ) == b"name\\nSynthetic\\n"


@pytest.mark.parametrize("invalid", [
    "wrong_recipient", "wrong_tenant", "expired", "revoked",
    "unverified", "inactive",
])
def test_customer_delivery_denies_invalid_grant_before_file_access(monkeypatch, invalid):
    from datetime import datetime, timedelta, timezone
    from app.core.nova.work_revenue import operations_customer_delivery as delivery
    monkeypatch.setattr(delivery, "_guard", lambda db: None)
    grant = _synthetic_grant()
    user = _synthetic_customer()
    if invalid == "wrong_recipient":
        user.id = "other-user"
    elif invalid == "wrong_tenant":
        user.organization_id = "other-org"
    elif invalid == "expired":
        grant["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    elif invalid == "revoked":
        grant["revoked_at"] = datetime.now(timezone.utc)
    elif invalid == "unverified":
        user.is_verified = False
    elif invalid == "inactive":
        user.is_active = False

    # The stub mimics the database WHERE conditions; no underlying artifact
    # should be accessed when the grant is ineligible.
    class ScopedDB(_DeliveryGrantDB):
        def execute(self, stmt):
            eligible = (
                user.id == grant["recipient_user_id"]
                and user.organization_id == grant["recipient_organization_id"]
                and grant["revoked_at"] is None
                and grant["expires_at"] > datetime.now(timezone.utc)
            )
            return _DeliveryGrantResult(grant if eligible else None)

    monkeypatch.setattr(
        delivery.csv_jobs, "download_review",
        lambda *args, **kw: pytest.fail("Unauthorized delivery reached private storage"),
    )
    with pytest.raises(delivery.HTTPException) as exc:
        delivery.recipient_download(ScopedDB(grant), job_id="synthetic-job", user=user)
    assert exc.value.status_code in {403, 404}


def test_customer_delivery_denies_changed_paid_recipient(monkeypatch):
    from app.core.nova.work_revenue import operations_customer_delivery as delivery
    monkeypatch.setattr(delivery, "_guard", lambda db: None)
    monkeypatch.setattr(
        delivery, "_exact_paid_lead",
        lambda *args, **kw: SimpleNamespace(id="lead-1", work_email="other@example.invalid"),
    )
    monkeypatch.setattr(
        delivery.csv_jobs, "download_review",
        lambda *args, **kw: pytest.fail("Mismatched paid order reached private storage"),
    )
    with pytest.raises(delivery.HTTPException) as exc:
        delivery.recipient_download(
            _DeliveryGrantDB(_synthetic_grant()),
            job_id="synthetic-job", user=_synthetic_customer(),
        )
    assert exc.value.status_code == 403


def test_my_deliverables_requires_verified_customer(monkeypatch):
    from app.core.nova.work_revenue import operations_customer_delivery as delivery
    monkeypatch.setattr(delivery, "_guard", lambda db: None)

    class FakeDB:
        def get(self, model, user_id):
            return SimpleNamespace(
                id=user_id, organization_id="customer-org",
                email="customer@example.invalid", is_active=True,
                is_verified=False,
            )

        def execute(self, statement):
            pytest.fail("Unverified account accessed delivery grants")

    with pytest.raises(delivery.HTTPException) as exc:
        delivery.list_my_approved_deliveries(
            user=SimpleNamespace(user_id="customer-1", organization_id="customer-org"),
            db=FakeDB(),
        )
    assert exc.value.status_code == 403


def test_my_deliverables_hides_revoked_or_changed_paid_order(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.core.nova.work_revenue import operations_customer_delivery as delivery
    monkeypatch.setattr(delivery, "_guard", lambda db: None)
    grant = _synthetic_grant()
    grant["expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=30)

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [grant]

    class FakeDB:
        def get(self, model, user_id):
            return _synthetic_customer()

        def execute(self, statement):
            return FakeResult()

    monkeypatch.setattr(
        delivery, "_exact_paid_lead",
        lambda *args, **kwargs: SimpleNamespace(
            id="lead-1", work_email="different@example.invalid"
        ),
    )
    monkeypatch.setattr(
        delivery.csv_jobs, "_owned",
        lambda *args, **kwargs: pytest.fail(
            "Mismatched paid customer was allowed to inspect private job"
        ),
    )
    response = delivery.list_my_approved_deliveries(
        user=SimpleNamespace(user_id="customer-1", organization_id="customer-org"),
        db=FakeDB(),
    )
    assert response.status_code == 200
    assert b'"deliveries":[]' in response.body
    assert response.headers["cache-control"] == "private, no-store"
