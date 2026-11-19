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
