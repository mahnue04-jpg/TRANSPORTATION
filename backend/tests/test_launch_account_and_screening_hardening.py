"""Launch hardening: seed allowlist, separate sync key, screening status mapping."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    SEED_PASSWORD,
    active_seed_emails,
    deployment_sync_key,
    seed_default_users,
    seed_password_is_weak_default,
)
from app.auth import ensure_auth_schema, seed_default_users as _seed
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.approval_engine.screening_status import (
    normalize_screening_status,
    screening_summary_for_application,
)
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication, ensure_platform_ops_schema
from app.modules.platform_ops.onboarding.insurance_requirements import insurance_requirements_config


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    ensure_platform_ops_schema()
    seed_default_users()
    return TestClient(app)


def test_deployment_sync_key_does_not_fall_back_to_seed_password(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AMICOR_DEPLOYMENT_SYNC_KEY", raising=False)
    assert deployment_sync_key() == ""
    # Seed password must not authorize sync.
    blocked = client.post(
        "/api/auth/deployment/sync-seed-users",
        headers={"X-Amicor-Deployment-Key": SEED_PASSWORD},
    )
    assert blocked.status_code in {403, 503}
    assert "SEED_PASSWORD" not in blocked.text or "must not" in blocked.text.lower() or blocked.status_code == 503


def test_unused_seed_accounts_are_deactivated_when_restriction_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AMICOR_RESTRICT_SEED_ACCOUNTS", "1")
    seed_default_users()
    allow = active_seed_emails()
    with SessionLocal() as db:
        rows = (
            db.query(PlatformUser)
            .filter(PlatformUser.email.like("%@amicor.local"))
            .all()
        )
        for row in rows:
            email = str(row.email or "").lower()
            if email in allow:
                assert row.is_active is True
            else:
                assert row.is_active is False
    monkeypatch.setenv("AMICOR_RESTRICT_SEED_ACCOUNTS", "0")
    seed_default_users()


def test_seed_status_reports_hardening_flags_without_secrets(client: TestClient) -> None:
    status = client.get("/api/auth/deployment/seed-status")
    assert status.status_code == 200
    body = status.json()
    assert "Amicor123!" not in status.text
    assert "seed_password_is_weak_default" in body
    assert body["deployment_sync_key_separate"] is bool(deployment_sync_key())
    assert "admin@amicor.local" in body["active_seed_allowlist"]
    assert any(not item.get("allowed_for_ops") for item in body["pilot_accounts"])


def test_screening_status_vocabulary_and_no_fabricated_clearance() -> None:
    assert normalize_screening_status(None, has_consent=False) == "consent_required"
    assert normalize_screening_status("PENDING_EXTERNAL", has_consent=True) == "pending"
    assert normalize_screening_status("CLEARED", has_consent=True) == "cleared"
    assert normalize_screening_status("FAILED", has_consent=True) == "failed"
    assert normalize_screening_status("EXPIRED", has_consent=True) == "expired"
    app = PlatformDriverOnboardingApplication(
        id=str(uuid4()),
        organization_id=str(uuid4()),
        status="under_review",
        declaration_mvr_authorization=True,
        declaration_background_authorization=True,
    )
    summary = screening_summary_for_application(application=app, case=None)
    assert summary["external_vendor_configured"] is False
    assert summary["mvr"]["status"] in {"pending", "not_started", "consent_required"}
    assert summary["blocks_activation"] is True


def test_insurance_minimums_not_invented() -> None:
    cfg = insurance_requirements_config()
    assert cfg["business_confirmation_required"] is True
    assert cfg["minimums_configured"] is False
    assert cfg["minimum_liability_usd"] is None
