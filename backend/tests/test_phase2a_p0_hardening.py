"""Phase 2A P0 security and compliance hardening tests."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    ADMIN_SESSION_COOKIE,
    ROLE_ADMIN,
    ROLE_STAFF,
    SEED_PASSWORD,
    ensure_auth_schema,
    seed_default_users,
)
from app.modules.platform_ops.permissions import REVIEW_ROLES, can_review
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4 as make_uuid
from app.main import app
from app.modules.approval_engine.eligibility import (
    dispatch_gate_enabled,
    driver_blocked_from_live_dispatch,
    evaluate_driver_ride_eligibility,
    filter_dispatch_candidates,
    sts_mhcp_dispatch_enabled,
)
from app.modules.approval_engine.external_service import record_external_verification
from app.modules.approval_engine.external_verification import ExternalVerificationRecord
from app.modules.approval_engine.models import ApprovalCase, ApprovalRequirement, ensure_approval_engine_schema
from app.modules.approval_engine.sensitive_providers import (
    FORBIDDEN_FIELD_NAMES,
    reject_raw_sensitive_payload,
    start_payout_tokenization,
    start_w9_external_workflow,
)
from app.modules.health_isf.models import HealthISFDriver
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingAuditEvent,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.secure_storage import (
    EncryptedPrivateDocumentStorage,
    SecureStorageNotConfigured,
    assert_production_storage_allowed,
    s3_configuration_status,
)
from app.modules.platform_ops.storage import get_document_storage


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
    return f"917{uuid4().int % 10_000_000:07d}"


def _complete_payload(org_id: str, *, phone: str | None = None) -> dict:
    today = date.today()
    return {
        "organization_id": org_id,
        "legal_first_name": "Taylor",
        "legal_last_name": "Applicant",
        "date_of_birth": "1990-04-12",
        "email": f"driver-{uuid4().hex[:8]}@example.com",
        "mobile_phone": phone or _unique_phone(),
        "home_address": "100 Main St",
        "city": "Minneapolis",
        "state": "MN",
        "zip_code": "55401",
        "emergency_contact_name": "Casey Contact",
        "emergency_contact_phone": "612-555-0199",
        "drivers_license_number": "D123456789",
        "license_issuing_state": "MN",
        "license_expiration_date": (today + timedelta(days=400)).isoformat(),
        "years_driving_experience": 8,
        "employment_type": "independent_contractor",
        "declaration_valid_license": True,
        "declaration_mvr_authorization": True,
        "declaration_background_authorization": True,
        "declaration_drug_alcohol_policy": True,
        "declaration_truthful_information": True,
        "electronic_signature": "Taylor Applicant",
        "signed_date": today.isoformat(),
    }


def _create_submitted_approved(client: TestClient, org_id: str, admin_token: str, phone: str) -> str:
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json=_complete_payload(org_id, phone=phone),
    )
    assert created.status_code == 200, created.text
    app_id = created.json()["application"]["id"]
    token = created.json()["applicant_access_token"]
    placeholder = ("placeholder-not-real-pii", "placeholder.txt", "text/plain")
    for category in (
        "drivers_license_front",
        "drivers_license_back",
        "vehicle_registration",
        "proof_of_auto_insurance",
        "independent_contractor_agreement",
    ):
        upload = client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category={category}",
            headers={"X-Applicant-Token": token},
            files={"file": placeholder},
        )
        assert upload.status_code == 200, upload.text
    from tests.work_setup_testutil import complete_secure_work_setup

    complete_secure_work_setup(client, app_id, token, legal_name="Taylor Applicant")
    submitted = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers={"X-Applicant-Token": token},
        json={"confirmation": True},
    )
    assert submitted.status_code == 200, submitted.text
    for status in ("under_review", "background_review"):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
            headers=_auth(admin_token),
            json={"to_status": status, "confirm": True},
        )
    approve = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert approve.status_code == 200, approve.text
    return app_id


def test_dispatch_gate_and_sts_remain_off():
    assert dispatch_gate_enabled() is False
    assert sts_mhcp_dispatch_enabled() is False


def test_platform_ops_cannot_bypass_compliance_activation(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    phone = _unique_phone()
    app_id = _create_submitted_approved(client, org_id, admin_token, phone)
    blocked = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert blocked.status_code in {400, 409}, blocked.text
    assert "COMPLIANCE_ACTIVATION_BLOCKED" in blocked.text
    with SessionLocal() as db:
        assert db.query(HealthISFDriver).filter(HealthISFDriver.phone == phone).first() is None
        events = (
            db.query(PlatformDriverOnboardingAuditEvent)
            .filter(
                PlatformDriverOnboardingAuditEvent.application_id == app_id,
                PlatformDriverOnboardingAuditEvent.event_type == "application_activation_blocked",
            )
            .all()
        )
        assert events


def test_status_cannot_mark_activated_without_compliance(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    phone = _unique_phone()
    app_id = _create_submitted_approved(client, org_id, admin_token, phone)
    moved = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "activated", "confirm": True},
    )
    assert moved.status_code in {400, 409}, moved.text
    assert "COMPLIANCE_ACTIVATION_BLOCKED" in moved.text


def test_onboarding_driver_not_dispatch_eligible_even_if_record_exists() -> None:
    org_id = _org_id()
    ensure_approval_engine_schema()
    ensure_platform_ops_schema()
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=make_uuid(),
            organization_id=org_id,
            name="Onboarding Hold",
            phone=_unique_phone(),
            vehicle_type="sedan",
            vehicle_plate=f"ONBD-{uuid4().hex[:8].upper()}",
            is_active=True,
        )
        db.add(driver)
        application = PlatformDriverOnboardingApplication(
            id=make_uuid(),
            organization_id=org_id,
            status="activated",
            legal_first_name="Onboard",
            legal_last_name="Hold",
            mobile_phone=driver.phone,
            activated_driver_id=driver.id,
            created_at=now(),
            updated_at=now(),
        )
        db.add(application)
        db.commit()
        ride = SimpleNamespace(service_type="private")
        hold = driver_blocked_from_live_dispatch(
            db, organization_id=org_id, driver_id=driver.id, ride=ride
        )
        assert hold["blocked"] is True
        eligibility = evaluate_driver_ride_eligibility(
            db, organization_id=org_id, driver_id=driver.id, ride=ride
        )
        assert eligibility["eligible"] is False
        kept = filter_dispatch_candidates(
            db,
            organization_id=org_id,
            ride=ride,
            candidates=[{"driver": driver, "driver_id": driver.id}],
        )
        assert kept == []


def test_sts_mhcp_rides_remain_disabled() -> None:
    org_id = _org_id()
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=make_uuid(),
            organization_id=org_id,
            name="Legacy Eligible",
            phone=_unique_phone(),
            vehicle_type="sedan",
            vehicle_plate=f"LEG{uuid4().hex[:5].upper()}",
            is_active=True,
        )
        db.add(driver)
        db.commit()
        sts_ride = SimpleNamespace(service_type="STS medical")
        hold = driver_blocked_from_live_dispatch(
            db, organization_id=org_id, driver_id=driver.id, ride=sts_ride
        )
        assert hold["blocked"] is True
        assert "STS/MHCP" in hold["reason"]
        mhcp_ride = SimpleNamespace(priority_tag="MHCP")
        hold_mhcp = driver_blocked_from_live_dispatch(
            db, organization_id=org_id, driver_id=driver.id, ride=mhcp_ride
        )
        assert hold_mhcp["blocked"] is True


def test_dispatcher_cannot_see_full_license(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    dispatcher_token = _login(client, "dispatcher@amicor.local")
    support_token = _login(client, "driversupport@amicor.local")
    phone = _unique_phone()
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json=_complete_payload(org_id, phone=phone),
    )
    app_id = created.json()["application"]["id"]
    applicant_token = created.json()["applicant_access_token"]
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers={"X-Applicant-Token": applicant_token},
        json={"confirmation": True},
    )
    for token in (dispatcher_token, support_token):
        detail = client.get(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}",
            headers=_auth(token),
        )
        assert detail.status_code == 200, detail.text
        license_value = detail.json()["drivers_license_number_masked"]
        assert license_value != "D123456789"
        assert license_value.endswith("6789")
        assert "*" in license_value
    compliance = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(admin_token),
    )
    assert compliance.status_code == 200
    assert compliance.json()["drivers_license_number_masked"] == "D123456789"
    with SessionLocal() as db:
        reveals = (
            db.query(PlatformDriverOnboardingAuditEvent)
            .filter(
                PlatformDriverOnboardingAuditEvent.application_id == app_id,
                PlatformDriverOnboardingAuditEvent.event_type == "sensitive_identity_revealed",
            )
            .all()
        )
        assert reveals


def test_ai_cannot_mark_external_verification_complete():
    with pytest.raises(ValueError, match="AI must not manufacture"):
        ExternalVerificationRecord(
            requirement_key="mvr",
            status="CLEARED",
            evidence_source="invented",
            reviewer_source="AI",
        ).normalized()
    with pytest.raises(ValueError, match="Automatic internal logic"):
        ExternalVerificationRecord(
            requirement_key="fingerprint",
            status="VERIFIED",
            evidence_source="auto",
            reviewer_source="SYSTEM",
        ).normalized()
    ensure_approval_engine_schema()
    org_id = _org_id()
    with SessionLocal() as db:
        case = ApprovalCase(
            id=make_uuid(),
            organization_id=org_id,
            entity_type="driver",
            workflow_status="EXTERNAL_VERIFICATION",
            created_at=now(),
            updated_at=now(),
        )
        db.add(case)
        db.flush()
        db.add(
            ApprovalRequirement(
                id=make_uuid(),
                case_id=case.id,
                organization_id=org_id,
                requirement_key="background_study",
                label="Background study",
                service_tier="STS_ELIGIBLE",
                timing="required_before_activation",
                traffic_light="yellow",
                is_blocking=True,
                is_legal_block=True,
                status="PENDING_EXTERNAL",
                external_status="PENDING_EXTERNAL",
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()
        with pytest.raises(ValueError, match="AI must not"):
            record_external_verification(
                db,
                case=case,
                requirement_key="background_study",
                status="CLEARED",
                actor_user_id="ai",
                actor_type="AI",
                evidence_source="should-fail",
            )
        with pytest.raises(ValueError, match="Automatic internal logic"):
            record_external_verification(
                db,
                case=case,
                requirement_key="background_study",
                status="VERIFIED",
                actor_user_id="system",
                actor_type="SYSTEM",
                evidence_source="should-fail",
            )


def test_production_document_storage_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "local_dev")
    with pytest.raises(SecureStorageNotConfigured, match="COMPLIANCE_STORAGE_BLOCKED"):
        get_document_storage()
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_BUCKET", raising=False)
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_SECRET_KEY", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(SecureStorageNotConfigured):
        assert_production_storage_allowed("s3_private")
    status = s3_configuration_status()
    assert status["status"] == "BLOCKED"
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "local_dev")
    storage = get_document_storage()
    backend, ref, size = storage.store(
        organization_id="org",
        application_id="app",
        category="proof_of_auto_insurance",
        filename="placeholder.txt",
        content_type="text/plain",
        stream=__import__("io").BytesIO(b"placeholder-not-real-pii"),
    )
    assert backend == "local_dev"
    assert size > 0
    payload, _ = storage.retrieve(storage_ref=ref)
    assert payload == b"placeholder-not-real-pii"


def test_encrypted_private_storage_roundtrip(tmp_path) -> None:
    storage = EncryptedPrivateDocumentStorage(
        base_dir=tmp_path,
        encryption_key="phase2a-test-encryption-key-32chars!!",
    )
    backend, ref, size = storage.store(
        organization_id="org",
        application_id="app",
        category="drivers_license_front",
        filename="placeholder.bin",
        content_type="application/octet-stream",
        stream=__import__("io").BytesIO(b"placeholder-image"),
    )
    assert backend == "encrypted_private"
    assert size == len(b"placeholder-image")
    raw_path = tmp_path / ref
    assert raw_path.read_bytes().startswith(b"AMICORDOC1")
    assert b"placeholder-image" not in raw_path.read_bytes()
    payload, _ = storage.retrieve(storage_ref=ref)
    assert payload == b"placeholder-image"


def test_admin_session_cookie_not_js_readable(client: TestClient) -> None:
    login = client.post(
        "/api/auth/admin-session",
        json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert "access_token" not in body
    assert body["session"] == "cookie"
    assert ADMIN_SESSION_COOKIE in login.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@amicor.local"
    listed = client.get("/api/platform-ops/driver-onboarding/applications")
    assert listed.status_code == 200
    logout = client.post("/api/auth/admin-session/logout")
    assert logout.status_code == 200
    me_after = client.get("/api/auth/me")
    assert me_after.status_code == 401


def test_bearer_login_still_works_for_development(client: TestClient) -> None:
    token = _login(client, "admin@amicor.local")
    me = client.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 200
    cats = client.get("/api/platform-ops/driver-onboarding/document-categories")
    assert cats.status_code == 200


def _review_probe(client: TestClient, **kwargs):
    """can_review-gated route that does not create Driver #001."""
    return client.post(
        "/api/approval-engine/cases",
        json={"platform_ops_application_id": "00000000-0000-0000-0000-000000000099"},
        **kwargs,
    )


def test_review_roles_do_not_include_staff() -> None:
    assert ROLE_ADMIN in REVIEW_ROLES
    assert ROLE_STAFF not in REVIEW_ROLES
    assert can_review(SimpleNamespace(role=ROLE_ADMIN, session_role=ROLE_ADMIN)) is True
    assert can_review(SimpleNamespace(role=ROLE_STAFF, session_role=ROLE_STAFF)) is False


def test_admin_session_cookie_resolves_as_admin_for_review_context(client: TestClient) -> None:
    login = client.post(
        "/api/auth/admin-session",
        json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
    )
    assert login.status_code == 200, login.text
    assert "access_token" not in login.json()
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == ROLE_ADMIN
    assert me.json()["session_role"] == ROLE_ADMIN
    assert ROLE_STAFF in (me.json().get("authorized_roles") or [])
    probe = _review_probe(client)
    assert probe.status_code != 403, probe.text
    assert "Review role required" not in probe.text
    assert probe.status_code == 404


def test_bearer_admin_still_passes_review_context(client: TestClient) -> None:
    token = _login(client, "admin@amicor.local")
    me = client.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["role"] == ROLE_ADMIN
    probe = _review_probe(client, headers=_auth(token))
    assert probe.status_code == 404, probe.text
    assert "Review role required" not in probe.text


def test_staff_cannot_perform_review_only_actions(client: TestClient) -> None:
    token = _login(client, "staff@amicor.local")
    me = client.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["role"] == ROLE_STAFF
    walkthrough = client.get("/api/approval-engine/walkthrough/base", headers=_auth(token))
    assert walkthrough.status_code == 200, walkthrough.text
    probe = _review_probe(client, headers=_auth(token))
    assert probe.status_code == 403, probe.text
    assert "Review role required" in probe.text
    staff_cookie = client.post(
        "/api/auth/admin-session",
        json={"email": "staff@amicor.local", "password": SEED_PASSWORD},
    )
    assert staff_cookie.status_code == 200, staff_cookie.text
    cookie_probe = _review_probe(client)
    assert cookie_probe.status_code == 403, cookie_probe.text
    assert "Review role required" in cookie_probe.text
    client.cookies.clear()


def test_unauthenticated_review_context_is_denied(client: TestClient) -> None:
    client.cookies.clear()
    me = client.get("/api/auth/me")
    assert me.status_code == 401
    probe = _review_probe(client)
    assert probe.status_code == 401
    prepare = client.post("/api/approval-engine/driver-001/prepare", json={"reuse_existing": True})
    assert prepare.status_code == 401


def test_sensitive_providers_reject_ssn_and_bank_fields():
    with pytest.raises(ValueError, match="must not accept"):
        reject_raw_sensitive_payload({"ssn": "000-00-0000"})
    with pytest.raises(ValueError, match="must not accept"):
        reject_raw_sensitive_payload({"routing_number": "000000000", "account_number": "111"})
    assert "ssn" in FORBIDDEN_FIELD_NAMES
    with pytest.raises(Exception, match="status flag"):
        start_w9_external_workflow()
    with pytest.raises(Exception, match="bank"):
        start_payout_tokenization()


def test_controlled_onboarding_draft_still_functions(client: TestClient) -> None:
    org_id = _org_id()
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json=_complete_payload(org_id),
    )
    assert created.status_code == 200, created.text
    app_id = created.json()["application"]["id"]
    token = created.json()["applicant_access_token"]
    saved = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
        json={"legal_first_name": "Updated", "organization_id": org_id},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["legal_first_name"] == "Updated"
