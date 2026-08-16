"""AI Approval Engine — workflow, fingerprint rules, owner gate, Driver #001 path."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4 as make_uuid
from app.main import app
from app.modules.approval_engine.assistant import handle_assistant_query
from app.modules.approval_engine.compliance import monitor_case
from app.modules.approval_engine.eligibility import evaluate_driver_ride_eligibility
from app.modules.approval_engine.models import (
    ApprovalCase,
    ApprovalRequirement,
    ensure_approval_engine_schema,
)
from app.modules.approval_engine.requirements import (
    build_requirement_plan,
    fingerprint_required_for_tiers,
)
from app.modules.approval_engine.statuses import assert_transition_allowed
from app.modules.approval_engine.workflow import (
    activate_if_eligible,
    blocking_requirements,
    create_or_sync_case_from_platform_ops,
    mark_requirement,
    owner_decide,
)
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    ensure_platform_ops_schema,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    return TestClient(app)


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "admin@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def test_fingerprint_not_universal_for_base_tier():
    assert fingerprint_required_for_tiers(["BASE_PRIVATE_AMBULATORY"]) is False
    assert fingerprint_required_for_tiers(["STS_ELIGIBLE"]) is True
    plan = build_requirement_plan(["BASE_PRIVATE_AMBULATORY"])
    fp = next(item for item in plan if item["requirement_key"] == "fingerprint")
    assert fp["timing"] == "conditional"
    assert fp["fingerprint_status"] == "NOT_REQUIRED"


def test_cannot_jump_pending_to_active():
    with pytest.raises(ValueError):
        assert_transition_allowed("PENDING", "ACTIVE")


def test_driver_001_full_workflow_without_fabricated_external_results(client: TestClient):
    """Driver #001 (DRV-001) path using a real local application — no fake approvals invented by AI."""
    ensure_approval_engine_schema()
    org_id = _org_id()
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    today = date.today()

    with SessionLocal() as db:
        application = PlatformDriverOnboardingApplication(
            id=make_uuid(),
            organization_id=org_id,
            status="submitted",
            legal_first_name="Driver",
            legal_last_name="One",
            date_of_birth=date(1985, 1, 15),
            email=f"driver001-{uuid4().hex[:6]}@example.com",
            mobile_phone=f"612{uuid4().int % 10_000_000:07d}",
            home_address="100 Main St",
            city="Minneapolis",
            state="MN",
            zip_code="55401",
            drivers_license_number="MN1234567",
            license_issuing_state="MN",
            license_expiration_date=today + timedelta(days=365),
            declaration_valid_license=True,
            declaration_mvr_authorization=True,
            declaration_background_authorization=True,
            declaration_drug_alcohol_policy=True,
            declaration_truthful_information=True,
            electronic_signature="Driver One",
            signed_date=today,
            submitted_at=now(),
            created_at=now(),
            updated_at=now(),
        )
        db.add(application)
        # Accepted docs — still does not fabricate MVR/insurance external verification.
        for category, expires in (
            ("drivers_license_front", today + timedelta(days=365)),
            ("drivers_license_back", None),
            ("vehicle_registration", today + timedelta(days=200)),
            ("vehicle_inspection_record", today + timedelta(days=180)),
            ("independent_contractor_agreement", None),
            ("motor_vehicle_record_consent", None),
            ("background_check_consent", None),
        ):
            db.add(
                PlatformDriverOnboardingDocument(
                    id=make_uuid(),
                    application_id=application.id,
                    organization_id=org_id,
                    category=category,
                    storage_backend="local_dev",
                    review_status="accepted",
                    expires_at=expires,
                    created_at=now(),
                    updated_at=now(),
                )
            )
        db.add(
            PlatformDriverOnboardingDocument(
                id=make_uuid(),
                application_id=application.id,
                organization_id=org_id,
                category="w9_status",
                storage_backend="local_dev",
                review_status="accepted",
                status_only_value="provided",
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()
        app_id = application.id

        case = create_or_sync_case_from_platform_ops(
            db,
            application=application,
            display_badge="DRV-E2E-001",
            requested_tiers=["BASE_PRIVATE_AMBULATORY"],
            run_review=True,
        )
        assert case.display_badge == "DRV-E2E-001"
        assert case.workflow_status in {"ACTION_REQUIRED", "EXTERNAL_VERIFICATION", "AI_REVIEW"}
        assert case.fingerprint_status == "NOT_REQUIRED"
        assert case.readiness_percentage < 100
        assert "cannot be activated" in (case.ai_summary or "").lower() or case.workflow_status != "ACTIVE"

        # Insurance upload missing → should be blocking; MVR consent present → external task, not fabricated complete.
        mvr = next(r for r in case.requirements if r.requirement_key == "mvr")
        assert mvr.status == "PENDING_EXTERNAL"
        assert mvr.traffic_light == "yellow"
        assert any(t.task_type == "mvr_request" for t in case.external_tasks)

        # Owner approval must not be available yet.
        with pytest.raises(ValueError):
            owner_decide(db, case=case, decision="APPROVE", actor_user_id="admin-test")

        # Complete remaining activation blockers with explicit human/external evidence (not AI invention).
        for key in (
            "drivers_license",
            "mvr",
            "vehicle_registration",
            "vehicle_insurance",
            "vehicle_inspection",
            "contractor_agreement",
            "w9",
            "payout_setup",
            "identity_complete",
            "age_verified",
            "base_training",
        ):
            mark_requirement(
                db,
                case=case,
                requirement_key=key,
                status="COMPLETE",
                actor_user_id="admin-test",
                evidence_ref=f"evidence-{key}",
                traffic_light="green",
                external_result=True,
            )
        for module in list(case.training_modules or []):
            module.status = "completed"
            module.completed_at = now()
            module.updated_at = now()
        db.commit()

        # Re-run AI review after human/external completions.
        from app.modules.approval_engine.ai_review import run_ai_review

        application = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).first()
        case = db.query(ApprovalCase).filter_by(id=case.id).first()
        case = run_ai_review(db, case, application=application)
        assert case.workflow_status == "READY_FOR_APPROVAL"
        assert not blocking_requirements(case)

        case = owner_decide(
            db,
            case=case,
            decision="APPROVE",
            actor_user_id="admin-test",
            reason="Owner approved Driver #001 package",
        )
        assert case.owner_approval_status == "APPROVED"
        assert case.workflow_status in {"OWNER_APPROVED", "APPROVED"}
        if case.workflow_status == "OWNER_APPROVED":
            # Force approved path if auto-step already happened otherwise.
            pass
        if case.workflow_status != "APPROVED":
            from app.modules.approval_engine.statuses import assert_transition_allowed as _at

            _at(case.workflow_status, "APPROVED")
            case.workflow_status = "APPROVED"
            db.commit()

        case = activate_if_eligible(
            db,
            case=case,
            actor_user_id="admin-test",
            health_isf_driver_id=make_uuid(),
        )
        assert case.workflow_status == "ACTIVE"
        assert case.activation_status == "ACTIVE"

        # Assistant queries answer from live case data.
        blocking = handle_assistant_query(
            db, organization_id=org_id, query="What is blocking DRV-E2E-001?"
        )
        assert blocking["intent"] == "blocking_items"
        assert blocking["display_badge"] == "DRV-E2E-001"
        assert blocking["blockers"] == []

        waiting = handle_assistant_query(
            db, organization_id=org_id, query="Show drivers waiting for approval."
        )
        assert waiting["intent"] == "drivers_waiting_for_approval"

        # Compliance monitor scheduled/scan path.
        scan = monitor_case(db, case)
        assert scan["case_id"] == case.id
        assert "alerts" in scan

        # API audit searchable.
        audit = client.get(f"/api/approval-engine/cases/{case.id}/audit", headers=headers)
        assert audit.status_code == 200, audit.text
        events = audit.json()
        actions = {row["action"] for row in events}
        assert "ai_application_review" in actions
        assert "owner_approve" in actions
        assert "activate_driver" in actions

        # Base ambulatory driver excluded from STS ride.
        class _Ride:
            service_type = "sts_wheelchair"
            priority_tag = "STS"

        eligibility = evaluate_driver_ride_eligibility(
            db,
            organization_id=org_id,
            driver_id=case.health_isf_driver_id,
            ride=_Ride(),
        )
        assert eligibility["eligible"] is False
        assert "STS" in eligibility["reason"] or "sts" in eligibility["reason"].lower()


def test_legal_block_cannot_be_greened_without_evidence(client: TestClient):
    ensure_approval_engine_schema()
    org_id = _org_id()
    with SessionLocal() as db:
        case = ApprovalCase(
            id=make_uuid(),
            organization_id=org_id,
            entity_type="driver",
            display_badge="DRV-TEST",
            workflow_status="ACTION_REQUIRED",
            requested_service_tiers_json='["BASE_PRIVATE_AMBULATORY"]',
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
                traffic_light="red",
                is_blocking=True,
                is_legal_block=True,
                status="PENDING",
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()
        with pytest.raises(ValueError):
            mark_requirement(
                db,
                case=case,
                requirement_key="mvr",
                status="COMPLETE",
                actor_user_id="admin",
                evidence_ref=None,
                external_result=False,
            )


def test_expired_mandatory_restricts_active_driver():
    ensure_approval_engine_schema()
    org_id = _org_id()
    with SessionLocal() as db:
        case = ApprovalCase(
            id=make_uuid(),
            organization_id=org_id,
            entity_type="driver",
            display_badge="DRV-EXP",
            workflow_status="ACTIVE",
            activation_status="ACTIVE",
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
                requirement_key="vehicle_insurance",
                label="Insurance",
                service_tier="BASE_PRIVATE_AMBULATORY",
                timing="required_before_activation",
                traffic_light="green",
                is_blocking=True,
                is_legal_block=True,
                status="COMPLETE",
                expiration_date=date.today() - timedelta(days=1),
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()
        result = monitor_case(db, case)
        assert result["action"] == "auto_restrict_expired_mandatory"
        db.refresh(case)
        assert case.workflow_status == "RESTRICTED"
