"""Applicant access reissue — existing application only, no duplicate case."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.approval_engine.driver_001 import DRIVER_001_BADGE
from app.modules.approval_engine.eligibility import dispatch_gate_enabled
from app.modules.approval_engine.models import ApprovalCase, ensure_approval_engine_schema
from app.modules.approval_engine.workflow import create_or_sync_case_from_platform_ops
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingAuditEvent,
    ensure_platform_ops_schema,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    return TestClient(app)


def _login(client: TestClient, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "admin@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _create_draft(client: TestClient, org_id: str) -> tuple[str, str]:
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": org_id, "legal_first_name": "Reissue", "legal_last_name": "Probe"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    return body["application"]["id"], body["applicant_access_token"]


def test_unauthorized_and_staff_cannot_reissue(client: TestClient) -> None:
    org_id = _org_id()
    app_id, _ = _create_draft(client, org_id)
    denied = client.post(f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-token/reissue")
    assert denied.status_code == 401
    staff = _login(client, "staff@amicor.local")
    staff_denied = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-token/reissue",
        headers=_auth(staff),
    )
    assert staff_denied.status_code == 403


def test_admin_reissue_rotates_token_without_duplicate_or_activation(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    org_id = _org_id()
    app_id, old_token = _create_draft(client, org_id)
    admin = _login(client, "admin@amicor.local")
    headers = _auth(admin)

    with SessionLocal() as db:
        application = db.get(PlatformDriverOnboardingApplication, app_id)
        assert application is not None
        case = create_or_sync_case_from_platform_ops(
            db,
            application=application,
            display_badge="REISSUE-TEST",
            requested_tiers=["BASE_PRIVATE_AMBULATORY"],
            run_review=False,
        )
        case_id = case.id
        db.commit()
        before_apps = db.query(PlatformDriverOnboardingApplication).count()
        before_cases = db.query(ApprovalCase).count()

    old_ok = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-status",
        headers={"X-Applicant-Token": old_token},
    )
    assert old_ok.status_code == 200, old_ok.text

    caplog.set_level(logging.INFO)
    reissued = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-token/reissue",
        headers=headers,
    )
    assert reissued.status_code == 200, reissued.text
    payload = reissued.json()
    new_token = payload["applicant_access_token"]
    assert new_token
    assert new_token != old_token
    assert payload["application_id"] == app_id
    assert payload["organization_id"] == org_id
    assert payload["previous_token_revoked"] is True
    assert payload["status"] != "activated"
    assert f"application_id={app_id}" in payload["apply_path"]
    assert f"organization_id={org_id}" in payload["apply_path"]
    assert "token=" in payload["apply_path"]

    persisted = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=headers,
    )
    assert persisted.status_code == 200
    detail = persisted.json()
    assert "applicant_access_token" not in detail
    assert detail["id"] == app_id
    assert detail["organization_id"] == org_id
    assert detail["status"] == "draft"
    assert not detail.get("activated_driver_id")

    old_blocked = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-status",
        headers={"X-Applicant-Token": old_token},
    )
    assert old_blocked.status_code == 403
    new_ok = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-status",
        headers={"X-Applicant-Token": new_token},
    )
    assert new_ok.status_code == 200, new_ok.text

    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert new_token not in log_text
    assert old_token not in log_text

    with SessionLocal() as db:
        application = db.get(PlatformDriverOnboardingApplication, app_id)
        assert application is not None
        assert application.id == app_id
        assert application.organization_id == org_id
        assert application.status == "draft"
        assert not application.activated_driver_id
        assert application.applicant_access_token_hash
        assert new_token not in (application.applicant_access_token_hash or "")
        events = (
            db.query(PlatformDriverOnboardingAuditEvent)
            .filter(
                PlatformDriverOnboardingAuditEvent.application_id == app_id,
                PlatformDriverOnboardingAuditEvent.event_type == "applicant_access_reissued",
            )
            .all()
        )
        assert len(events) == 1
        audit = events[0]
        assert new_token not in (audit.reason or "")
        assert new_token not in (audit.metadata_json or "")
        assert old_token not in (audit.reason or "")
        assert old_token not in (audit.metadata_json or "")
        assert "applicant_access_reissued" == audit.event_type
        case = db.get(ApprovalCase, case_id)
        assert case is not None
        assert case.platform_ops_application_id == app_id
        assert case.workflow_status != "ACTIVE"
        assert db.query(PlatformDriverOnboardingApplication).count() == before_apps
        assert db.query(ApprovalCase).count() == before_cases

    assert dispatch_gate_enabled() is False


def test_reissue_on_driver_001_does_not_prepare_or_activate(client: TestClient) -> None:
    org_id = _org_id()
    admin = _login(client, "admin@amicor.local")
    headers = _auth(admin)
    prepared = client.post(
        "/api/approval-engine/driver-001/prepare",
        headers=headers,
        json={"reuse_existing": True, "legal_first_name": "Driver", "legal_last_name": "001"},
    )
    assert prepared.status_code == 200, prepared.text
    first = prepared.json()
    app_id = first["platform_ops_application"]["id"]
    case_id = first["case"]["case_id"]
    assert first["activated"] is False
    assert first["dispatch_gate_enabled"] is False

    with SessionLocal() as db:
        before_apps = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.organization_id == org_id)
            .count()
        )
        before_cases = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.display_badge == DRIVER_001_BADGE)
            .count()
        )

    reissued = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-token/reissue",
        headers=headers,
    )
    assert reissued.status_code == 200, reissued.text
    assert reissued.json()["application_id"] == app_id
    assert reissued.json()["organization_id"] == org_id

    status = client.get("/api/approval-engine/driver-001", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["exists"] is True
    assert body["platform_ops_application"]["id"] == app_id
    assert body["case"]["case_id"] == case_id
    assert body["case"]["workflow_status"] != "ACTIVE"
    assert body["dispatch_gate_enabled"] is False
    assert body.get("activated") is not True

    with SessionLocal() as db:
        after_apps = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.organization_id == org_id)
            .count()
        )
        after_cases = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.display_badge == DRIVER_001_BADGE)
            .count()
        )
        assert after_apps == before_apps
        assert after_cases == before_cases
        case = db.get(ApprovalCase, case_id)
        assert case is not None
        assert case.activation_status != "ACTIVE"
        assert case.health_isf_driver_id is None
