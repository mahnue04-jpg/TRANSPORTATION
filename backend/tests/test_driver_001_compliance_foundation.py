"""Driver 001 onboarding + compliance foundation — no fabricated clears."""
from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app
from app.modules.approval_engine.driver_001 import DRIVER_001_BADGE
from app.modules.approval_engine.models import ApprovalCase, ensure_approval_engine_schema
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, ensure_health_isf_schema
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication, ensure_platform_ops_schema


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    ensure_health_isf_schema()
    return TestClient(app)


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "admin@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _login(client: TestClient, email: str = "admin@amicor.local") -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _prepare(client: TestClient) -> dict:
    org_id = _org_id()
    token = _login(client)
    with SessionLocal() as db:
        stale = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.organization_id == org_id, ApprovalCase.display_badge == DRIVER_001_BADGE)
            .all()
        )
        for row in stale:
            if str(row.workflow_status or "").upper() == "ACTIVE":
                row.workflow_status = "PENDING"
                row.activation_status = "NOT_ACTIVE"
                row.updated_at = now()
        db.commit()
    response = client.post(
        "/api/approval-engine/driver-001/prepare",
        headers={"Authorization": f"Bearer {token}"},
        json={"legal_first_name": "Driver", "legal_last_name": "001", "reuse_existing": True},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    payload["_admin_token"] = token
    payload["_org_id"] = org_id
    return payload


def test_progress_page_and_prepare_do_not_fabricate(client: TestClient):
    page = client.get("/platform-ops/driver-onboarding")
    assert page.status_code == 200
    assert b"onboarding progress" in page.content.lower()

    prepared = _prepare(client)
    assert prepared["fabricated_verifications"] is False
    assert prepared["activated"] is False
    token = prepared["_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}
    summary = client.get("/api/approval-engine/driver-001/compliance-summary", headers=headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["exists"] is True
    assert body["overall_status"] != "APPROVED"
    assert body["online_eligible"] is False
    background = next(item for item in body["items"] if item["key"] == "background_check")
    assert background["status"] != "CLEAR"
    fingerprint = next(item for item in body["items"] if item["key"] == "fingerprint")
    assert fingerprint["status"] == "NOT_REQUIRED"


def test_driver_001_can_save_application_and_upload(client: TestClient):
    prepared = _prepare(client)
    app_info = prepared["platform_ops_application"]
    application_id = app_info["id"]
    applicant_token = app_info.get("applicant_access_token")
    assert application_id
    if not applicant_token:
        reissue = client.post(
            f"/api/platform-ops/driver-onboarding/applications/{application_id}/applicant-token/reissue",
            headers={"Authorization": f"Bearer {prepared['_admin_token']}"},
        )
        assert reissue.status_code == 200, reissue.text
        applicant_token = reissue.json()["applicant_access_token"]
    headers = {"X-Applicant-Token": applicant_token}
    today = date.today()
    update = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{application_id}",
        headers=headers,
        json={
            "organization_id": prepared["_org_id"],
            "legal_first_name": "Driver",
            "legal_middle_name": "Test",
            "legal_last_name": "001",
            "date_of_birth": "1988-06-01",
            "email": "driver001.safe@example.com",
            "mobile_phone": "612-555-1001",
            "home_address": "100 Test Ave",
            "city": "Minneapolis",
            "state": "MN",
            "zip_code": "55401",
            "emergency_contact_name": "Pat Contact",
            "emergency_contact_phone": "612-555-0199",
            "drivers_license_number": "TEST-MN-001",
            "license_issuing_state": "MN",
            "license_expiration_date": (today + timedelta(days=400)).isoformat(),
            "vehicle_year": 2019,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "vehicle_color": "Silver",
            "vehicle_license_plate": "TEST001",
            "vehicle_plate_state": "MN",
            "insurance_carrier": "Test Mutual",
            "insurance_policy_number": "POL-001",
            "authorize_qualification_checks": True,
        },
    )
    assert update.status_code == 200, update.text
    upload = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{application_id}/documents"
        f"?category=drivers_license_front",
        headers={"X-Applicant-Token": applicant_token},
        files={"file": ("license-front.txt", io.BytesIO(b"TEST ONLY LICENSE FRONT"), "text/plain")},
    )
    assert upload.status_code in {200, 201}, upload.text
    progress = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{application_id}/progress",
        headers=headers,
    )
    assert progress.status_code == 200, progress.text
    body = progress.json()
    assert body["application_id"] == application_id
    assert body["progress_percent"] >= 0
    application_item = next(item for item in body["items"] if item["key"] == "application")
    assert application_item["light"] in {"GREEN", "YELLOW"}


def test_incomplete_driver_001_blocked_from_online_legacy_driver_not_blocked(client: TestClient):
    prepared = _prepare(client)
    org_id = prepared["_org_id"]
    application_id = prepared["platform_ops_application"]["id"]
    token = prepared["_admin_token"]
    driver_id = uuid4()
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=driver_id,
            organization_id=org_id,
            name="Driver 001",
            phone="612-555-1001",
            vehicle_type="sedan",
            vehicle_plate=f"ONBD-{driver_id[:4].upper()}",
            status=DriverStatus.OFFLINE,
            is_active=True,
            is_online=False,
            availability_state="offline",
        )
        db.add(driver)
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=application_id).first()
        application.activated_driver_id = driver_id
        case = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.display_badge == DRIVER_001_BADGE, ApprovalCase.organization_id == org_id)
            .first()
        )
        case.health_isf_driver_id = driver_id
        db.commit()

    blocked = client.post(
        "/api/health-isf/drivers/availability",
        headers={"Authorization": f"Bearer {token}"},
        json={"driver_id": driver_id, "availability_state": "available"},
    )
    assert blocked.status_code == 409, blocked.text
    assert "blocked from going online" in blocked.text.lower()

    with SessionLocal() as db:
        james = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name == "James Smith")
            .first()
        )
        if james is None:
            from app.modules.health_isf.service import sync_operational_driver_fleet

            sync_operational_driver_fleet(db)
            james = (
                db.query(HealthISFDriver)
                .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.phone == "917-555-1001")
                .first()
            )
        assert james is not None
        james_id = str(james.id)
        james.is_active = True
        db.commit()

    allowed = client.post(
        "/api/health-isf/drivers/availability",
        headers={"Authorization": f"Bearer {token}"},
        json={"driver_id": james_id, "availability_state": "available"},
    )
    assert allowed.status_code == 200, allowed.text


def test_admin_can_legitimately_complete_and_then_driver_may_go_online(client: TestClient):
    prepared = _prepare(client)
    org_id = prepared["_org_id"]
    application_id = prepared["platform_ops_application"]["id"]
    token = prepared["_admin_token"]
    headers = {"Authorization": f"Bearer {token}"}
    driver_id = uuid4()
    today = date.today() + timedelta(days=200)
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=driver_id,
            organization_id=org_id,
            name="Driver 001",
            phone="612-555-1099",
            vehicle_type="sedan",
            vehicle_plate=f"TST-{driver_id[:4].upper()}",
            status=DriverStatus.OFFLINE,
            is_active=True,
            is_online=False,
            availability_state="offline",
        )
        db.add(driver)
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=application_id).first()
        application.activated_driver_id = driver_id
        application.status = "approved"
        application.approved_at = now()
        application.legal_first_name = "Driver"
        application.legal_last_name = "001"
        application.date_of_birth = date(1988, 6, 1)
        application.email = "driver001.safe@example.com"
        application.mobile_phone = "612-555-1099"
        application.home_address = "100 Test Ave"
        application.emergency_contact_name = "Pat"
        application.emergency_contact_phone = "612-555-0100"
        application.drivers_license_number = "TEST-MN-001"
        application.license_issuing_state = "MN"
        application.license_expiration_date = today
        application.vehicle_year = 2019
        application.vehicle_make = "Honda"
        application.vehicle_model = "Accord"
        application.vehicle_license_plate = "TEST001"
        application.insurance_carrier = "Test Mutual"
        application.insurance_review_status = "accepted"
        application.agreement_status = "signed"
        application.declaration_background_authorization = True
        application.background_consent_at = now()
        case = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.display_badge == DRIVER_001_BADGE, ApprovalCase.organization_id == org_id)
            .first()
        )
        case.health_isf_driver_id = driver_id
        case.license_verification_status = "VERIFIED"
        case.background_study_status = "CLEAR"
        case.fingerprint_status = "NOT_REQUIRED"
        case.owner_approval_status = "APPROVED"
        case.owner_approval_timestamp = now()
        case.contractor_agreement_status = "SIGNED"
        case.vehicle_registration_status = "APPROVED"
        for vehicle in list(case.vehicles or []):
            vehicle.eligibility_status = "ELIGIBLE"
            vehicle.vehicle_status = "APPROVED"
            vehicle.updated_at = now()
        for module in list(case.training_modules or []):
            if bool(getattr(module, "is_required", False)):
                module.status = "completed"
                module.completed_at = now()
                module.updated_at = now()
        from app.modules.platform_ops.models import PlatformDriverOnboardingDocument

        for category in (
            "drivers_license_front",
            "drivers_license_back",
            "vehicle_registration",
            "proof_of_auto_insurance",
            "independent_contractor_agreement",
        ):
            db.add(
                PlatformDriverOnboardingDocument(
                    id=uuid4(),
                    application_id=application_id,
                    organization_id=org_id,
                    category=category,
                    storage_backend="local_dev",
                    storage_ref=f"test/{category}.txt",
                    original_filename=f"{category}.txt",
                    review_status="accepted",
                    reviewed_by="admin-test",
                    reviewed_at=now(),
                )
            )
        db.commit()

    try:
        summary = client.get("/api/approval-engine/driver-001/compliance-summary", headers=headers)
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert body["online_eligible"] is True, body
        assert body["overall_status"] == "APPROVED"
        allowed = client.post(
            "/api/health-isf/drivers/availability",
            headers=headers,
            json={"driver_id": driver_id, "availability_state": "available"},
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["is_online"] is True
    finally:
        with SessionLocal() as db:
            application = db.query(PlatformDriverOnboardingApplication).filter_by(id=application_id).first()
            if application is not None:
                application.status = "draft"
                application.approved_at = None
                application.activated_driver_id = None
                application.insurance_review_status = "pending"
                application.agreement_status = "pending"
                application.updated_at = now()
            case = (
                db.query(ApprovalCase)
                .filter(ApprovalCase.display_badge == DRIVER_001_BADGE, ApprovalCase.organization_id == org_id)
                .first()
            )
            if case is not None:
                case.license_verification_status = "NOT_STARTED"
                case.background_study_status = "NOT_STARTED"
                case.owner_approval_status = "PENDING"
                case.owner_approval_timestamp = None
                case.contractor_agreement_status = "NOT_STARTED"
                case.vehicle_registration_status = "NOT_STARTED"
                case.health_isf_driver_id = None
                case.updated_at = now()
                for vehicle in list(case.vehicles or []):
                    vehicle.eligibility_status = "PENDING"
                    vehicle.vehicle_status = "PENDING"
            db.commit()
