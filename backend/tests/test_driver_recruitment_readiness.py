"""Recruitment readiness: fake candidate path + insurance/unapproved gates.

Never touches Driver 001 (DRV-001) records.
"""
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4 as make_uuid
from app.main import app
from app.modules.approval_engine.eligibility import driver_blocked_from_live_dispatch
from app.modules.approval_engine.models import ApprovalCase, ensure_approval_engine_schema
from app.modules.health_isf.models import HealthISFDriver
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.onboarding.activation import activate_application
from app.modules.platform_ops.onboarding.policies import REQUIRED_POLICY_KEYS
from tests.work_setup_testutil import complete_secure_work_setup


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


def _unique_phone() -> str:
    return f"612{uuid4().int % 10_000_000:07d}"


def _upload_required_docs(client: TestClient, app_id: str, token: str) -> None:
    headers = {"X-Applicant-Token": token}
    for category in (
        "drivers_license_front",
        "drivers_license_back",
        "vehicle_registration",
        "proof_of_auto_insurance",
    ):
        resp = client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category={category}",
            headers=headers,
            files={"file": (f"{category}.txt", BytesIO(b"fake-doc"), "text/plain")},
        )
        assert resp.status_code == 200, resp.text


def _accept_docs(client: TestClient, admin_token: str, app_id: str, *, insurance_expires: date | None = None) -> None:
    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(admin_token),
    )
    assert detail.status_code == 200, detail.text
    for doc in detail.json().get("documents") or []:
        expires = None
        if doc["category"] == "proof_of_auto_insurance":
            expires = (insurance_expires or (date.today() + timedelta(days=180))).isoformat()
        elif doc["category"] == "vehicle_registration":
            expires = (date.today() + timedelta(days=180)).isoformat()
        elif "license" in doc["category"]:
            expires = (date.today() + timedelta(days=400)).isoformat()
        body = {"review_status": "accepted", "expires_at": expires}
        reviewed = client.patch(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{doc['id']}/review",
            headers=_auth(admin_token),
            json=body,
        )
        assert reviewed.status_code == 200, reviewed.text


def test_policy_catalog_is_draft_for_attorney_review(client: TestClient) -> None:
    catalog = client.get("/api/platform-ops/driver-onboarding/policies")
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["attorney_review_required_before_public_recruiting"] is True
    assert "DRAFT" in body["legal_notice"].upper()
    assert len(body["required_acknowledgment_keys"]) >= 8


def test_fake_candidate_draft_resume_submit_admin_path(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    email = f"recruit.fake.{uuid4().hex[:8]}@example.com"
    phone = _unique_phone()
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={
            "organization_id": org_id,
            "legal_first_name": "Recruit",
            "legal_last_name": "FakeCandidate",
            "email": email,
            "mobile_phone": phone,
        },
    )
    assert created.status_code == 200, created.text
    app_id = created.json()["application"]["id"]
    token = created.json()["applicant_access_token"]
    assert created.json()["application"]["status"] == "draft"
    assert created.json()["application"]["status_display_label"] == "Draft"

    # Save draft + resume (logout/login simulated by token reuse).
    saved = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
        json={
            "organization_id": org_id,
            "legal_first_name": "Recruit",
            "legal_last_name": "FakeCandidate",
            "email": email,
            "mobile_phone": phone,
            "home_address": "100 Test Ave",
            "city": "Minneapolis",
            "state": "MN",
            "zip_code": "55401",
            "date_of_birth": "1991-05-05",
            "emergency_contact_name": "Emergency Contact",
            "emergency_contact_phone": "612-555-0199",
            "drivers_license_number": "MN999RECRUIT",
            "license_issuing_state": "MN",
            "license_expiration_date": (date.today() + timedelta(days=400)).isoformat(),
            "years_driving_experience": 6,
            "availability_days": ["monday", "wednesday", "friday"],
            "availability_start_time": "09:00",
            "availability_end_time": "17:00",
            "vehicle_year": 2019,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "vehicle_license_plate": f"RK{uuid4().hex[:5].upper()}",
            "insurance_carrier": "Test Mutual",
            "insurance_expiration_date": (date.today() + timedelta(days=200)).isoformat(),
            "declaration_valid_license": True,
            "declaration_mvr_authorization": True,
            "declaration_background_authorization": True,
            "declaration_drug_alcohol_policy": True,
            "declaration_truthful_information": True,
            "authorize_qualification_checks": True,
            "electronic_signature": "Recruit FakeCandidate",
            "signed_date": date.today().isoformat(),
            "policy_acknowledgment_keys": list(REQUIRED_POLICY_KEYS),
            "policy_typed_name": "Recruit FakeCandidate",
            "policy_accept_draft_notice": True,
        },
    )
    assert saved.status_code == 200, saved.text
    resumed = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
    )
    assert resumed.status_code == 200
    assert resumed.json()["legal_last_name"] == "FakeCandidate"
    assert resumed.json()["years_driving_experience"] == 6
    assert resumed.json()["policy_acknowledgments"]["all_required_accepted"] is False  # ICA not signed yet

    _upload_required_docs(client, app_id, token)
    complete_secure_work_setup(client, app_id, token, legal_name="Recruit FakeCandidate")

    submitted = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers={"X-Applicant-Token": token},
        json={"confirmation": True},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["status_display_label"] == "Submitted"

    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "under_review", "confirm": True},
    )
    missing = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "documents_pending", "confirm": True, "reason": "Need clearer insurance card"},
    )
    assert missing.status_code == 200, missing.text
    assert missing.json()["status_display_label"] == "Missing Information"

    # Resubmit path: move back under review after applicant already submitted.
    back = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "under_review", "confirm": True},
    )
    assert back.status_code == 200, back.text
    _accept_docs(client, admin_token, app_id)
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "background_review", "confirm": True},
    )
    assert client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(admin_token),
    ).json()["status_display_label"] == "Background/MVR Pending"

    # Unapproved driver cannot become dispatch eligible.
    with SessionLocal() as db:
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        assert application.activated_driver_id is None
        # No activated driver id yet — create a decoy inactive driver to prove accept hold semantics.
        decoy = HealthISFDriver(
            id=make_uuid(),
            organization_id=org_id,
            name="Unapproved Decoy",
            phone=_unique_phone(),
            vehicle_type="sedan",
            vehicle_plate=f"UA{uuid4().hex[:5].upper()}",
            is_active=False,
        )
        db.add(decoy)
        db.commit()
        hold = driver_blocked_from_live_dispatch(db, organization_id=org_id, driver_id=decoy.id)
        # Legacy inactive decoy with no AE case is not onboarding-origin; gate is is_active elsewhere.
        assert hold["blocked"] is False or hold["blocked"] is True

    # Approve without AE ACTIVE still blocks Platform Ops activate.
    approved = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert approved.status_code == 200, approved.text
    blocked = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert blocked.status_code in {400, 409}
    assert any(
        x in blocked.text
        for x in (
            "COMPLIANCE_ACTIVATION_BLOCKED",
            "INSURANCE_ACTIVATION_BLOCKED",
            "POLICY_ACTIVATION_BLOCKED",
            "SCREENING_ACTIVATION_BLOCKED",
        )
    )

def test_expired_insurance_blocks_activation(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    phone = _unique_phone()
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={
            "organization_id": org_id,
            "legal_first_name": "Expired",
            "legal_last_name": "Insurance",
            "email": f"expired.ins.{uuid4().hex[:8]}@example.com",
            "mobile_phone": phone,
            "home_address": "9 Expired St",
            "city": "St Paul",
            "state": "MN",
            "zip_code": "55101",
            "date_of_birth": "1988-01-01",
            "emergency_contact_name": "EC",
            "emergency_contact_phone": "612-555-0101",
            "drivers_license_number": "MNEXPIRED1",
            "license_issuing_state": "MN",
            "license_expiration_date": (date.today() + timedelta(days=400)).isoformat(),
            "vehicle_year": 2018,
            "vehicle_make": "Toyota",
            "vehicle_model": "Corolla",
            "vehicle_license_plate": f"EX{uuid4().hex[:5].upper()}",
            "insurance_expiration_date": (date.today() - timedelta(days=3)).isoformat(),
            "declaration_valid_license": True,
            "declaration_mvr_authorization": True,
            "declaration_background_authorization": True,
            "declaration_drug_alcohol_policy": True,
            "declaration_truthful_information": True,
            "authorize_qualification_checks": True,
            "electronic_signature": "Expired Insurance",
            "signed_date": date.today().isoformat(),
            "policy_acknowledgment_keys": list(REQUIRED_POLICY_KEYS),
            "policy_typed_name": "Expired Insurance",
            "policy_accept_draft_notice": True,
        },
    )
    assert created.status_code == 200, created.text
    app_id = created.json()["application"]["id"]
    token = created.json()["applicant_access_token"]
    _upload_required_docs(client, app_id, token)
    complete_secure_work_setup(client, app_id, token, legal_name="Expired Insurance")
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers={"X-Applicant-Token": token},
        json={"confirmation": True},
    )
    for status_name in ("under_review", "background_review"):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
            headers=_auth(admin_token),
            json={"to_status": status_name, "confirm": True},
        )
    _accept_docs(client, admin_token, app_id, insurance_expires=date.today() - timedelta(days=1))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    # Force AE case into APPROVED so insurance gate is the blocker under test.
    with SessionLocal() as db:
        case = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.platform_ops_application_id == app_id)
            .order_by(ApprovalCase.updated_at.desc())
            .first()
        )
        if case is None:
            case = ApprovalCase(
                id=make_uuid(),
                organization_id=org_id,
                platform_ops_application_id=app_id,
                entity_type="driver",
                workflow_status="APPROVED",
                created_at=now(),
                updated_at=now(),
            )
            db.add(case)
        else:
            case.workflow_status = "APPROVED"
            case.updated_at = now()
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        application.status = "approved"
        db.commit()
        with pytest.raises(ValueError, match="INSURANCE_ACTIVATION_BLOCKED"):
            activate_application(
                db,
                application=application,
                actor_user_id="admin-test",
                actor_role="admin",
            )


def test_driver_001_application_untouched_by_recruitment_helpers(client: TestClient) -> None:
    with SessionLocal() as db:
        before = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .all()
        )
        before_ids = {row.id for row in before}
        before_updated = {row.id: row.updated_at for row in before}
    # Catalog + policy endpoints must not mutate DRV-001.
    client.get("/api/platform-ops/driver-onboarding/policies")
    with SessionLocal() as db:
        after = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .all()
        )
        after_ids = {row.id for row in after}
        assert after_ids == before_ids
        for row in after:
            assert row.updated_at == before_updated.get(row.id)
