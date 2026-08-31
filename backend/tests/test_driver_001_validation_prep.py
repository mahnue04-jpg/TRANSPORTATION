"""Driver #001 production-validation preparation — no fabricated verifications."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.approval_engine.driver_001 import (
    DRIVER_001_BADGE,
    get_driver_001_status,
    prepare_driver_001_validation,
)
from app.modules.approval_engine.eligibility import dispatch_gate_enabled
from app.helpers import now
from app.modules.approval_engine.models import ApprovalCase, ensure_approval_engine_schema
from app.modules.approval_engine.walkthrough import BASE_AMBULATORY_WALKTHROUGH, base_walkthrough
from app.modules.approval_engine.workflow import owner_decide
from app.modules.platform_ops.models import ensure_platform_ops_schema


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    return TestClient(app)


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "admin@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_base_walkthrough_ordered_and_classifies_actors():
    steps = base_walkthrough()
    assert len(steps) == len(BASE_AMBULATORY_WALKTHROUGH)
    assert [s["order"] for s in steps] == sorted(s["order"] for s in steps)
    assert steps[0]["requirement_key"] == "identity_complete"
    assert steps[-1]["requirement_key"] == "owner_package_approval"
    license_step = next(s for s in steps if s["requirement_key"] == "drivers_license")
    assert license_step["is_legal_block"] is True
    assert license_step["driver_uploads"]
    assert license_step["ai_auto_review"]
    assert license_step["external_verification"]
    assert license_step["owner_admin_approval"]
    # Fingerprint / STS not in BASE ordered activation path.
    keys = {s["requirement_key"] for s in steps}
    assert "fingerprint" not in keys
    assert "background_study" not in keys
    assert "sts_training" not in keys
    assert "mhcp_credentialing" not in keys


def test_prepare_driver_001_creates_real_record_without_fabricating(client: TestClient):
    assert dispatch_gate_enabled() is False
    org_id = _org_id()
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Ensure prior ACTIVE DRV-001 rows from other tests cannot block validation prep.
    with SessionLocal() as db:
        stale = (
            db.query(ApprovalCase)
            .filter(
                ApprovalCase.organization_id == org_id,
                ApprovalCase.display_badge == DRIVER_001_BADGE,
            )
            .all()
        )
        for row in stale:
            if row.workflow_status == "ACTIVE":
                row.display_badge = f"DRV-001-ARCHIVED-{row.id[:8]}"
                row.updated_at = now()
            # Other modules may have temporarily approved DRV-001; prep must start from a draft file.
            if row.owner_approval_status == "APPROVED":
                row.owner_approval_status = "PENDING"
                row.owner_approval_timestamp = None
                row.updated_at = now()
            if row.platform_ops_application_id:
                from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

                application = (
                    db.query(PlatformDriverOnboardingApplication)
                    .filter(PlatformDriverOnboardingApplication.id == row.platform_ops_application_id)
                    .first()
                )
                if application is not None and application.status in {"approved", "activated", "suspended"}:
                    application.status = "draft"
                    application.approved_at = None
                    application.activated_at = None
                    application.updated_at = now()
        db.commit()

    response = client.post(
        "/api/approval-engine/driver-001/prepare",
        headers=headers,
        json={
            "legal_first_name": "Driver",
            "legal_last_name": "001",
            "reuse_existing": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["driver_badge"] == DRIVER_001_BADGE
    assert payload["service_tier"] == "BASE_PRIVATE_AMBULATORY"
    assert payload["fabricated_verifications"] is False
    assert payload["activated"] is False
    assert payload["owner_approved"] is False
    assert payload["dispatch_gate_enabled"] is False
    assert payload["case"]["fingerprint_status"] == "NOT_REQUIRED"
    assert payload["case"]["workflow_status"] not in {"OWNER_APPROVED", "APPROVED", "ACTIVE"}
    assert payload["case"]["readiness_percentage"] < 100
    assert payload["platform_ops_application"]["id"]
    assert payload["platform_ops_application"]["status"] == "draft"
    assert payload["walkthrough"]["ordered_steps"]
    assert any(step.get("is_current_focus") for step in payload["walkthrough"]["ordered_steps"])
    assert payload["integrations_still_required"]
    assert payload["credentials_accounts_amicor_must_obtain"]
    assert payload["manual_setup_required"]
    assert payload["owner_approval_required_for"]
    assert payload["compliance_needing_authoritative_verification"]

    # Reuse path does not invent completions.
    again = client.post(
        "/api/approval-engine/driver-001/prepare",
        headers=headers,
        json={"reuse_existing": True},
    )
    assert again.status_code == 200, again.text
    again_payload = again.json()
    assert again_payload["case"]["case_id"] == payload["case"]["case_id"]
    assert again_payload["fabricated_verifications"] is False
    assert again_payload["activated"] is False

    status = client.get("/api/approval-engine/driver-001", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()["exists"] is True

    with SessionLocal() as db:
        case = db.query(ApprovalCase).filter(
            ApprovalCase.organization_id == org_id,
            ApprovalCase.display_badge == DRIVER_001_BADGE,
        ).first()
        assert case is not None
        # Owner cannot approve while blockers remain.
        with pytest.raises(ValueError):
            owner_decide(db, case=case, decision="APPROVE", actor_user_id="admin")
        live = get_driver_001_status(db, organization_id=org_id)
        assert live["case"]["workflow_status"] != "ACTIVE"


def test_walkthrough_endpoint(client: TestClient):
    token = _login(client)
    response = client.get(
        "/api/approval-engine/walkthrough/base",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["service_tier"] == "BASE_PRIVATE_AMBULATORY"
    assert len(body["ordered_steps"]) >= 10
    assert body["non_base_separate_steps"]
    assert body["dispatch_gate_enabled_default"] is False
