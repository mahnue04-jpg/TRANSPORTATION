"""Simple Driver #001 application + AI compliance handoff tests."""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4 as make_uuid
from app.main import app
from app.modules.approval_engine.eligibility import dispatch_gate_enabled
from app.modules.approval_engine.models import ApprovalCase, ensure_approval_engine_schema
from app.modules.approval_engine.requirements import build_requirement_plan
from app.modules.approval_engine.workflow import activate_if_eligible, owner_decide
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
    assert response.status_code == 200
    return response.json()["access_token"]


def _simple_payload(org_id: str) -> dict:
    today = date.today()
    return {
        "organization_id": org_id,
        "legal_first_name": "Driver",
        "legal_last_name": "One",
        "date_of_birth": "1988-06-01",
        "email": f"simple-{uuid4().hex[:8]}@example.com",
        "mobile_phone": f"612{uuid4().int % 10_000_000:07d}",
        "home_address": "200 Lake St",
        "city": "Minneapolis",
        "state": "MN",
        "zip_code": "55408",
        "emergency_contact_name": "Pat Contact",
        "emergency_contact_phone": "612-555-0199",
        "drivers_license_number": "MN998877",
        "license_issuing_state": "MN",
        "license_expiration_date": (today + timedelta(days=300)).isoformat(),
        "vehicle_year": 2019,
        "vehicle_make": "Honda",
        "vehicle_model": "Accord",
        "vehicle_license_plate": "AMICOR1",
        "authorize_qualification_checks": True,
        "declaration_valid_license": True,
        "declaration_mvr_authorization": True,
        "electronic_signature": "Driver One",
        "signed_date": today.isoformat(),
        "w9_secure_workflow_started": True,
        "payout_setup_started": True,
    }


def test_applicant_facing_html_is_simple():
    html = Path("static/platform-ops/driver-apply.html").read_text(encoding="utf-8")
    js = Path("static/platform-ops/driver-apply.js").read_text(encoding="utf-8")
    admin_html = Path("static/platform-ops/driver-onboarding-admin.html").read_text(encoding="utf-8")
    admin_js = Path("static/platform-ops/driver-onboarding-admin.js").read_text(encoding="utf-8")
    assert "About you" in html
    assert "Become an Amicor Driver" in html
    assert "Application submitted" in html
    assert "start-new-application" in html
    assert "clearApplicationSession" in js
    assert "Only draft applications can be edited" in js or "only draft applications can be edited" in js.lower()
    assert "admin-sign-in" in admin_html
    assert "Session expired" in admin_js or "Click Sign in" in admin_js
    assert "latestDocumentsByCategory" in admin_js
    assert "refreshWorkspace" in admin_js
    assert "FETCH_TIMEOUT_MS" in admin_js
    assert "Sign in required" in admin_js
    assert "status === 403" not in admin_js
    assert "AMICOR_EXT_VERIFY" not in html
    assert "PENDING_EXTERNAL" not in html
    assert "adapter" not in html.lower()
    assert "background study" not in html.lower()
    assert "fingerprint" not in html.lower()


def test_repeat_upload_same_file_is_idempotent(client: TestClient):
    org_id = _org_id()
    create = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": org_id},
    )
    assert create.status_code == 200, create.text
    app_id = create.json()["application"]["id"]
    token = create.json()["applicant_access_token"]
    headers = {"X-Applicant-Token": token}
    payload = b"TEST-ONLY-IDEMPOTENT-BYTES"

    first = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers=headers,
        files={"file": ("front-test-only.jpg", io.BytesIO(payload), "image/jpeg")},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["id"]

    second = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers=headers,
        files={"file": ("front-test-only.jpg", io.BytesIO(payload), "image/jpeg")},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first_id

    with SessionLocal() as db:
        from app.modules.platform_ops.models import (
            PlatformDriverOnboardingAuditEvent,
            PlatformDriverOnboardingDocument,
        )

        docs = (
            db.query(PlatformDriverOnboardingDocument)
            .filter(
                PlatformDriverOnboardingDocument.application_id == app_id,
                PlatformDriverOnboardingDocument.category == "drivers_license_front",
            )
            .all()
        )
        assert len(docs) == 1
        uploads = (
            db.query(PlatformDriverOnboardingAuditEvent)
            .filter(
                PlatformDriverOnboardingAuditEvent.application_id == app_id,
                PlatformDriverOnboardingAuditEvent.event_type == "document_uploaded",
            )
            .all()
        )
        assert len(uploads) == 1


def test_simple_driver_001_submission_creates_ai_tasks_without_fabricating(client: TestClient):
    assert dispatch_gate_enabled() is False
    org_id = _org_id()
    create = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": org_id},
    )
    assert create.status_code == 200, create.text
    app_id = create.json()["application"]["id"]
    token = create.json()["applicant_access_token"]
    headers = {"X-Applicant-Token": token}

    payload = _simple_payload(org_id)
    updated = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=headers,
        json=payload,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["vehicle_make"] == "Honda"

    # Submit without required uploads must fail.
    blocked = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=headers,
        json={"confirmation": True, "simple_confirmation_message": True},
    )
    assert blocked.status_code in {400, 422}, blocked.text
    assert "drivers_license_front" in blocked.text

    # TEST-ONLY placeholder bytes — not real identity/insurance documents.
    for category, filename in (
        ("drivers_license_front", "front-test-only.jpg"),
        ("drivers_license_back", "back-test-only.jpg"),
        ("vehicle_registration", "reg-test-only.jpg"),
        ("proof_of_auto_insurance", "ins-test-only.jpg"),
        ("independent_contractor_agreement", "ica-test-only.pdf"),
    ):
        upload = client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category={category}",
            headers=headers,
            files={"file": (filename, io.BytesIO(b"TEST-ONLY-PLACEHOLDER"), "image/jpeg")},
        )
        assert upload.status_code == 200, upload.text
        assert upload.json()["review_status"] == "pending"

    submitted = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=headers,
        json={"confirmation": True, "simple_confirmation_message": True},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "submitted"
    assert "reviewing your information" in (body.get("applicant_message") or "").lower()
    assert len(body.get("documents") or []) >= 5

    applicant_status = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/applicant-status",
        headers=headers,
    )
    assert applicant_status.status_code == 200
    assert applicant_status.json()["internal_status_hidden"] is True
    assert "PENDING_EXTERNAL" not in str(applicant_status.json())

    with SessionLocal() as db:
        case = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.platform_ops_application_id == app_id)
            .first()
        )
        assert case is not None
        assert case.workflow_status in {"ACTION_REQUIRED", "EXTERNAL_VERIFICATION", "AI_REVIEW"}
        assert case.workflow_status != "ACTIVE"
        mvr = next(r for r in case.requirements if r.requirement_key == "mvr")
        assert mvr.status == "PENDING_EXTERNAL"
        assert mvr.status != "VERIFIED"
        # Pending uploads must count as evidence present (not MISSING).
        license_req = next(r for r in case.requirements if r.requirement_key == "drivers_license")
        assert license_req.status == "PENDING_EXTERNAL"
        assert license_req.evidence_ref
        registration = next(r for r in case.requirements if r.requirement_key == "vehicle_registration")
        assert registration.status == "PENDING_EXTERNAL"
        insurance = next(r for r in case.requirements if r.requirement_key == "vehicle_insurance")
        assert insurance.status == "PENDING_EXTERNAL"
        contractor = next(r for r in case.requirements if r.requirement_key == "contractor_agreement")
        assert contractor.status == "PENDING_EXTERNAL"
        # No fabricated external clears.
        for key in ("mvr", "vehicle_insurance", "drivers_license"):
            row = next(r for r in case.requirements if r.requirement_key == key)
            assert row.status not in {"VERIFIED", "COMPLETE"}
        bg = next(r for r in case.requirements if r.requirement_key == "background_study")
        assert bg.status == "CONDITIONAL_NOT_APPLICABLE"
        assert bg.is_blocking is False
        fp = next(r for r in case.requirements if r.requirement_key == "fingerprint")
        assert fp.status == "CONDITIONAL_NOT_APPLICABLE"
        assert any(t.task_type for t in (case.external_tasks or []))
        assert case.readiness_percentage > 18.2

        with pytest.raises(ValueError):
            owner_decide(db, case=case, decision="APPROVE", actor_user_id="owner-test")
        with pytest.raises(ValueError):
            activate_if_eligible(db, case=case, actor_user_id="owner-test")


def test_conditional_requirements_activate_for_sts_tier():
    plan = {p["requirement_key"]: p for p in build_requirement_plan(["STS_ELIGIBLE"])}
    assert plan["background_study"]["timing"] == "required_before_activation"
    assert plan["fingerprint"]["timing"] in {"required_before_activation", "conditional"}
    assert plan["fingerprint"]["fingerprint_status"] == "REQUIRED"
    base_plan = {p["requirement_key"]: p for p in build_requirement_plan(["BASE_PRIVATE_AMBULATORY"])}
    assert base_plan["background_study"]["timing"] == "conditional"
    assert base_plan["fingerprint"]["timing"] == "conditional"
    assert base_plan["medical_qualification"]["timing"] == "conditional"


def test_owner_approval_gate_and_audit(client: TestClient):
    org_id = _org_id()
    admin = _login(client)
    with SessionLocal() as db:
        case = ApprovalCase(
            id=make_uuid(),
            organization_id=org_id,
            entity_type="driver",
            display_badge="DRV-OWNER-GATE",
            legal_name="Gate Test",
            workflow_status="READY_FOR_APPROVAL",
            activation_status="NOT_ACTIVE",
            created_at=now(),
            updated_at=now(),
        )
        db.add(case)
        db.commit()
        case_id = case.id

    # APPROVE when ready records audit.
    response = client.post(
        f"/api/approval-engine/cases/{case_id}/owner-decision",
        headers={"Authorization": f"Bearer {admin}"},
        json={"decision": "APPROVE", "reason": "Owner package approval"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["owner_approval_status"] == "APPROVED"

    audit = client.get(
        f"/api/approval-engine/cases/{case_id}/audit",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert audit.status_code == 200
    actions = [row.get("action") for row in audit.json()]
    assert "owner_approve" in actions
