"""Phase 2B P1 owner/admin onboarding workflow tests.

Phase 2A activation, dispatch, STS/MHCP, and storage controls must remain intact.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4 as make_uuid
from app.main import app
from app.modules.approval_engine.eligibility import (
    dispatch_gate_enabled,
    driver_blocked_from_live_dispatch,
    evaluate_driver_ride_eligibility,
    sts_mhcp_dispatch_enabled,
    vehicle_is_assignable,
)
from app.modules.approval_engine.esign_provider import ESignProviderNotConfigured, start_live_esign
from app.modules.approval_engine.external_service import record_external_verification
from app.modules.approval_engine.external_verification import ExternalVerificationRecord
from app.modules.approval_engine.models import (
    ApprovalCase,
    ApprovalRequirement,
    ApprovalVehicleRecord,
    ensure_approval_engine_schema,
)
from app.modules.approval_engine.phase2b import p1_approval_blockers
from app.modules.approval_engine.sensitive_providers import reject_raw_sensitive_payload
from app.modules.approval_engine.workflow import owner_decide
from app.modules.health_isf.models import HealthISFDriver
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.onboarding.activation import assert_approval_engine_allows_activation


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


def _create_submitted_app(client: TestClient, org_id: str) -> tuple[str, str]:
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json=_complete_payload(org_id),
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
    submitted = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers={"X-Applicant-Token": token},
        json={"confirmation": True},
    )
    assert submitted.status_code == 200, submitted.text
    return app_id, token


def _create_case(client: TestClient, admin_token: str, app_id: str) -> dict:
    created = client.post(
        "/api/approval-engine/cases",
        headers=_auth(admin_token),
        json={
            "platform_ops_application_id": app_id,
            "requested_service_tiers": ["BASE_PRIVATE_AMBULATORY"],
            "run_ai_review": True,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def _force_ready_for_approval(case_id: str) -> None:
    with SessionLocal() as db:
        case = db.query(ApprovalCase).filter(ApprovalCase.id == case_id).first()
        assert case is not None
        for req in list(case.requirements or []):
            if req.is_blocking and req.timing in {"required_now", "required_before_activation"}:
                req.status = "COMPLETE"
                req.traffic_light = "green"
                req.external_status = "VERIFIED"
        for module in list(case.training_modules or []):
            module.status = "completed"
            module.completed_at = now()
        case.workflow_status = "READY_FOR_APPROVAL"
        case.mvr_status = "COMPLETE"
        case.updated_at = now()
        db.commit()


def test_rejected_documents_block_approval(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(admin_token),
    )
    insurance = next(doc for doc in detail.json()["documents"] if doc["category"] == "proof_of_auto_insurance")
    rejected = client.patch(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{insurance['id']}/review",
        headers=_auth(admin_token),
        json={"review_status": "rejected", "review_reason": "illegible test placeholder"},
    )
    assert rejected.status_code == 200, rejected.text
    _force_ready_for_approval(case["id"])
    with SessionLocal() as db:
        loaded = db.query(ApprovalCase).filter(ApprovalCase.id == case["id"]).first()
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).first()
        blockers = p1_approval_blockers(db, loaded, application)
        assert any("rejected" in item for item in blockers)
        with pytest.raises(ValueError, match="rejected"):
            owner_decide(db, case=loaded, decision="APPROVE", actor_user_id="owner-test", application=application)


def test_expired_insurance_blocks_eligibility(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    recorded = client.post(
        f"/api/approval-engine/cases/{case['id']}/insurance-review",
        headers=_auth(admin_token),
        json={
            "carrier": "Test Mutual",
            "policy_reference": "POL-99998888",
            "effective_date": (date.today() - timedelta(days=400)).isoformat(),
            "expiration_date": (date.today() - timedelta(days=1)).isoformat(),
            "vehicle_association": "TEST001",
            "review_status": "accepted",
            "notes": "Expired test policy",
            "evidence_ref": "doc-test-insurance",
        },
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["insurance"]["expired"] is True
    assert "****" in recorded.json()["insurance"]["policy_ref_masked"]
    assert recorded.json()["insurance"]["commercial_policy_not_required_for_private"] is True
    with SessionLocal() as db:
        loaded = db.query(ApprovalCase).filter(ApprovalCase.id == case["id"]).first()
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).first()
        assert any("expired" in item.lower() for item in p1_approval_blockers(db, loaded, application))
        loaded.workflow_status = "ACTIVE"
        loaded.health_isf_driver_id = make_uuid()
        db.commit()
        eligibility = evaluate_driver_ride_eligibility(
            db,
            organization_id=org_id,
            driver_id=loaded.health_isf_driver_id,
            ride=SimpleNamespace(service_type="private"),
        )
        assert eligibility["eligible"] is False
        standalone = ApprovalCase(
            id=make_uuid(),
            organization_id=org_id,
            entity_type="driver",
            workflow_status="ACTIVE",
            insurance_expiration=date.today() - timedelta(days=1),
            created_at=now(),
            updated_at=now(),
        )
        standalone_driver = HealthISFDriver(
            id=make_uuid(),
            organization_id=org_id,
            name="Expired Insurance",
            phone=_unique_phone(),
            vehicle_type="sedan",
            vehicle_plate=f"EXP{uuid4().hex[:5].upper()}",
            is_active=True,
        )
        db.add(standalone_driver)
        standalone.health_isf_driver_id = standalone_driver.id
        db.add(standalone)
        db.commit()
        expired_eligibility = evaluate_driver_ride_eligibility(
            db,
            organization_id=org_id,
            driver_id=standalone_driver.id,
            ride=SimpleNamespace(service_type="private"),
        )
        assert expired_eligibility["eligible"] is False
        assert "insurance expired" in expired_eligibility["reason"].lower()


def test_incomplete_mvr_blocks_approval(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    with SessionLocal() as db:
        loaded = db.query(ApprovalCase).filter(ApprovalCase.id == case["id"]).first()
        for req in list(loaded.requirements or []):
            if req.requirement_key != "mvr" and req.is_blocking:
                req.status = "COMPLETE"
                req.traffic_light = "green"
        mvr = next(req for req in loaded.requirements if req.requirement_key == "mvr")
        mvr.status = "PENDING_EXTERNAL"
        loaded.workflow_status = "READY_FOR_APPROVAL"
        db.commit()
        db.refresh(loaded)
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).first()
        assert any("MVR" in item for item in p1_approval_blockers(db, loaded, application))
        with pytest.raises(ValueError, match="MVR|blocking"):
            owner_decide(db, case=loaded, decision="APPROVE", actor_user_id="owner-test", application=application)


def test_ai_and_system_cannot_clear_mvr_background_fingerprint():
    with pytest.raises(ValueError, match="AI must not manufacture"):
        ExternalVerificationRecord(
            requirement_key="mvr",
            status="CLEARED",
            evidence_source="invented",
            provider_key="manual-test",
            reviewer_source="AI",
        ).normalized()
    with pytest.raises(ValueError, match="Automatic internal logic"):
        ExternalVerificationRecord(
            requirement_key="mvr",
            status="VERIFIED",
            evidence_source="auto",
            provider_key="system",
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
                requirement_key="mvr",
                label="MVR",
                service_tier="BASE_PRIVATE_AMBULATORY",
                timing="required_before_activation",
                traffic_light="yellow",
                is_blocking=True,
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
                requirement_key="mvr",
                status="CLEARED",
                actor_user_id="ai",
                actor_type="AI",
                evidence_source="should-fail",
                provider_key="manual",
            )
        with pytest.raises(ValueError, match="Automatic internal logic"):
            record_external_verification(
                db,
                case=case,
                requirement_key="mvr",
                status="VERIFIED",
                actor_user_id="system",
                actor_type="SYSTEM",
                evidence_source="should-fail",
                provider_key="manual",
            )


def test_agreement_version_and_evidence_retrievable(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(admin_token),
    )
    agreement_doc = next(
        doc for doc in detail.json()["documents"] if doc["category"] == "independent_contractor_agreement"
    )
    recorded = client.post(
        f"/api/approval-engine/cases/{case['id']}/agreement",
        headers=_auth(admin_token),
        json={
            "version": "AMICOR-IC-TEST-1.0",
            "status": "signed",
            "evidence_document_id": agreement_doc["id"],
            "notes": "Typed acceptance preserved",
        },
    )
    assert recorded.status_code == 200, recorded.text
    package = recorded.json()["agreement"]
    assert package["agreement_version"] == "AMICOR-IC-TEST-1.0"
    assert package["evidence_document_id"] == agreement_doc["id"]
    assert package["inspect_path"].endswith(f"/documents/{agreement_doc['id']}/download")
    assert package["public_url_exposed"] is False
    assert package["esign_provider"]["live"] is False
    fetched = client.get(
        f"/api/approval-engine/cases/{case['id']}/agreement",
        headers=_auth(admin_token),
    )
    assert fetched.status_code == 200
    assert fetched.json()["agreement_version"] == "AMICOR-IC-TEST-1.0"
    download = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{agreement_doc['id']}/download",
        headers=_auth(admin_token),
    )
    assert download.status_code == 200
    assert download.content
    assert "http" not in (package["inspect_path"] or "")[:4] or package["inspect_path"].startswith("/")
    with pytest.raises(ESignProviderNotConfigured):
        start_live_esign()


def test_raw_ssn_tin_rejected_on_w9_workflow(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    rejected = client.post(
        f"/api/approval-engine/cases/{case['id']}/w9-workflow",
        headers=_auth(admin_token),
        json={"status": "pending", "metadata": {"ssn": "000-00-0000", "tin": "12-3456789"}},
    )
    assert rejected.status_code == 400, rejected.text
    assert "SSN" in rejected.text or "TIN" in rejected.text or "must not accept" in rejected.text
    with pytest.raises(ValueError, match="must not accept"):
        reject_raw_sensitive_payload({"ssn": "000-00-0000"})
    ok = client.post(
        f"/api/approval-engine/cases/{case['id']}/w9-workflow",
        headers=_auth(admin_token),
        json={"status": "requested", "notes": "Request sent to future tax provider"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["w9"]["stores_ssn_tin"] is False
    with SessionLocal() as db:
        columns = {col["name"] for col in db.bind.dialect.get_columns} if False else set()
        from sqlalchemy import inspect

        inspector = inspect(db.bind)
        app_cols = {col["name"] for col in inspector.get_columns("platform_driver_onboarding_applications")}
        assert "ssn" not in app_cols
        assert "tin" not in app_cols
        assert "social_security_number" not in app_cols


def test_incomplete_required_training_blocks_eligibility(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    with SessionLocal() as db:
        loaded = db.query(ApprovalCase).filter(ApprovalCase.id == case["id"]).first()
        assert loaded.training_modules
        assert any(module.status != "completed" for module in loaded.training_modules)
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).first()
        assert any("training" in item.lower() for item in p1_approval_blockers(db, loaded, application))
        loaded.workflow_status = "ACTIVE"
        loaded.health_isf_driver_id = make_uuid()
        db.commit()
        eligibility = evaluate_driver_ride_eligibility(
            db,
            organization_id=org_id,
            driver_id=loaded.health_isf_driver_id,
            ride=SimpleNamespace(service_type="private"),
        )
        assert eligibility["eligible"] is False


def test_incomplete_vehicle_review_blocks_and_test_plate_does_not_dispatch(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    pending = client.post(
        f"/api/approval-engine/cases/{case['id']}/vehicle",
        headers=_auth(admin_token),
        json={
            "make": "Honda",
            "model": "Accord",
            "year": 2019,
            "license_plate": "TEST001",
            "registration_expiration": (date.today() + timedelta(days=200)).isoformat(),
            "inspection_status": "pending",
            "eligibility_status": "PENDING",
        },
    )
    assert pending.status_code == 200, pending.text
    vehicle = pending.json()["vehicle"]
    assert vehicle["license_plate"] == "TEST001"
    assert vehicle["dispatch_activated"] is False
    assert vehicle["assignable_for_live_dispatch"] is False
    with SessionLocal() as db:
        loaded = db.query(ApprovalCase).filter(ApprovalCase.id == case["id"]).first()
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).first()
        assert any("vehicle" in item.lower() for item in p1_approval_blockers(db, loaded, application))
        row = db.query(ApprovalVehicleRecord).filter(ApprovalVehicleRecord.case_id == case["id"]).first()
        ok, reason = vehicle_is_assignable(row, required_tier="BASE_PRIVATE_AMBULATORY")
        assert ok is False
        assert "not activated" in reason.lower() or "pending" in reason.lower() or "eligibility" in reason.lower()
        driver = HealthISFDriver(
            id=make_uuid(),
            organization_id=org_id,
            name="Test Plate Link",
            phone=_unique_phone(),
            vehicle_type="sedan",
            vehicle_plate="TEST001",
            is_active=False,
        )
        db.add(driver)
        loaded.health_isf_driver_id = driver.id
        row.health_isf_vehicle_id = None
        db.commit()
        hold = driver_blocked_from_live_dispatch(
            db, organization_id=org_id, driver_id=driver.id, ride=SimpleNamespace(service_type="private")
        )
        assert hold["blocked"] is True
    blocked_placeholder = client.post(
        f"/api/approval-engine/cases/{case['id']}/vehicle",
        headers=_auth(admin_token),
        json={"license_plate": "ONBD-TEST", "make": "Honda", "eligibility_status": "REVIEWED"},
    )
    assert blocked_placeholder.status_code == 400
    reviewed = client.post(
        f"/api/approval-engine/cases/{case['id']}/vehicle",
        headers=_auth(admin_token),
        json={
            "make": "Honda",
            "model": "Accord",
            "year": 2019,
            "license_plate": "TEST001",
            "eligibility_status": "ELIGIBLE_NOT_ACTIVE",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["vehicle"]["dispatch_activated"] is False
    assert reviewed.json()["vehicle"]["assignable_for_live_dispatch"] is False


def test_sts_mhcp_and_phase2a_activation_protections_remain(client: TestClient) -> None:
    assert dispatch_gate_enabled() is False
    assert sts_mhcp_dispatch_enabled() is False
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
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
    blocked = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert blocked.status_code in {400, 409}, blocked.text
    assert "COMPLIANCE_ACTIVATION_BLOCKED" in blocked.text
    with SessionLocal() as db:
        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).first()
        with pytest.raises(ValueError, match="COMPLIANCE_ACTIVATION_BLOCKED"):
            assert_approval_engine_allows_activation(db, application=application)
        driver = HealthISFDriver(
            id=make_uuid(),
            organization_id=org_id,
            name="Legacy",
            phone=_unique_phone(),
            vehicle_type="sedan",
            vehicle_plate=f"LEG{uuid4().hex[:5].upper()}",
            is_active=True,
        )
        db.add(driver)
        db.commit()
        hold = driver_blocked_from_live_dispatch(
            db, organization_id=org_id, driver_id=driver.id, ride=SimpleNamespace(service_type="STS medical")
        )
        assert hold["blocked"] is True
        assert "STS/MHCP" in hold["reason"]


def test_unauthorized_roles_cannot_access_sensitive_information(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    dispatcher_token = _login(client, "dispatcher@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(dispatcher_token),
    )
    assert detail.status_code == 200
    assert detail.json()["drivers_license_number_masked"] != "D123456789"
    insurance = next(doc for doc in detail.json()["documents"] if doc["category"] == "proof_of_auto_insurance")
    inspect = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{insurance['id']}/download",
        headers=_auth(dispatcher_token),
    )
    assert inspect.status_code == 403
    review = client.patch(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{insurance['id']}/review",
        headers=_auth(dispatcher_token),
        json={"review_status": "accepted", "review_reason": "should fail"},
    )
    assert review.status_code == 403
    mvr = client.post(
        f"/api/approval-engine/cases/{case['id']}/external/mvr/record",
        headers=_auth(dispatcher_token),
        json={
            "status": "CLEARED",
            "provider_key": "manual-test",
            "evidence_source": "should-not-be-allowed",
            "actor_type": "USER",
        },
    )
    assert mvr.status_code == 403
    w9 = client.post(
        f"/api/approval-engine/cases/{case['id']}/w9-workflow",
        headers=_auth(dispatcher_token),
        json={"status": "completed"},
    )
    assert w9.status_code == 403


def test_manual_mvr_verified_requires_evidence(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    missing = client.post(
        f"/api/approval-engine/cases/{case['id']}/external/mvr/record",
        headers=_auth(admin_token),
        json={"status": "CLEARED", "actor_type": "USER"},
    )
    assert missing.status_code == 400, missing.text
    recorded = client.post(
        f"/api/approval-engine/cases/{case['id']}/external/mvr/record",
        headers=_auth(admin_token),
        json={
            "status": "PENDING_EXTERNAL",
            "provider_key": "manual-external-review",
            "notes": "Queued for manual MVR",
            "actor_type": "USER",
        },
    )
    assert recorded.status_code == 200, recorded.text
    cleared = client.post(
        f"/api/approval-engine/cases/{case['id']}/external/mvr/record",
        headers=_auth(admin_token),
        json={
            "status": "CLEARED",
            "provider_key": "manual-external-review",
            "provider_reference_id": "MVR-TEST-001",
            "evidence_source": "external paper MVR case file",
            "verification_date": date.today().isoformat(),
            "expiration_date": (date.today() + timedelta(days=365)).isoformat(),
            "notes": "Manual review of test placeholder result",
            "actor_type": "USER",
        },
    )
    assert cleared.status_code == 200, cleared.text
    mvr = next(req for req in cleared.json()["requirements"] if req["key"] == "mvr")
    assert mvr["status"] in {"CLEARED", "VERIFIED"}


def test_readiness_view_distinguishes_private_and_sts(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    view = client.get(
        f"/api/approval-engine/cases/{case['id']}/readiness-view",
        headers=_auth(admin_token),
    )
    assert view.status_code == 200, view.text
    payload = view.json()
    assert payload["private_and_sts_remain_separate"] is True
    assert payload["sts_mhcp_dispatch_enabled"] is False
    keys = {item["key"]: item for item in payload["items"]}
    assert keys["sts_mhcp_eligibility"]["state"] in {"NOT_REQUIRED", "BLOCKED"}
    assert keys["dispatch_eligibility"]["state"] == "BLOCKED"
    for item in payload["items"]:
        assert item["state"] in {
            "READY",
            "PENDING",
            "BLOCKED",
            "EXPIRED",
            "NOT_REQUIRED",
            "NOT_AVAILABLE_YET",
        }


def test_training_record_does_not_invent_completion(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, _ = _create_submitted_app(client, org_id)
    case = _create_case(client, admin_token, app_id)
    module_key = case["training_modules"][0]["module_key"]
    updated = client.patch(
        f"/api/approval-engine/cases/{case['id']}/training/{module_key}",
        headers=_auth(admin_token),
        json={
            "status": "in_progress",
            "module_version": "BASE-TEST-1",
            "evidence_ref": None,
        },
    )
    assert updated.status_code == 200, updated.text
    row = next(item for item in updated.json()["training_modules"] if item["module_key"] == module_key)
    assert row["status"] == "in_progress"
    assert row["completed_at"] is None
