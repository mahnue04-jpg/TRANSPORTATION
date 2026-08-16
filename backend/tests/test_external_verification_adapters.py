"""External verification adapters + expiration re-verification readiness."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4 as make_uuid
from app.main import app
from app.modules.approval_engine.compliance import monitor_case
from app.modules.approval_engine.external_service import (
    record_external_verification,
    submit_external_verification,
)
from app.modules.approval_engine.external_verification import (
    BASE_EXTERNAL_REQUIREMENT_KEYS,
    EXTERNAL_VERIFICATION_STATUSES,
    ExternalVerificationRecord,
    build_adapter_registry,
    get_adapter,
    list_adapter_capabilities,
)
from app.modules.approval_engine.models import (
    ApprovalCase,
    ApprovalRequirement,
    ensure_approval_engine_schema,
)
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


def test_adapter_registry_covers_base_without_vendor_hardcoding():
    caps = list_adapter_capabilities()
    base_keys = {c["requirement_key"] for c in caps if c["base_activation"]}
    assert set(BASE_EXTERNAL_REQUIREMENT_KEYS) == base_keys
    for key in BASE_EXTERNAL_REQUIREMENT_KEYS:
        adapter = get_adapter(key)
        cap = adapter.capability()
        assert cap.vendor_selected is False
        assert cap.mode in {"manual", "configurable_provider", "unconfigured"}
    # Non-BASE stay registered but separate
    assert "fingerprint" in build_adapter_registry()
    assert "background_study" in build_adapter_registry()


def test_ai_cannot_manufacture_verified_external_record():
    with pytest.raises(ValueError, match="AI must not manufacture"):
        ExternalVerificationRecord(
            requirement_key="mvr",
            status="VERIFIED",
            evidence_source="fake",
            reviewer_source="AI",
        ).normalized()


def test_manual_submit_and_record_with_evidence():
    ensure_approval_engine_schema()
    org_id = _org_id()
    with SessionLocal() as db:
        case = ApprovalCase(
            id=make_uuid(),
            organization_id=org_id,
            entity_type="driver",
            display_badge="DRV-EXT",
            workflow_status="EXTERNAL_VERIFICATION",
            activation_status="NOT_ACTIVE",
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
                is_legal_block=True,
                status="PENDING_EXTERNAL",
                external_status="PENDING_EXTERNAL",
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()

        case = submit_external_verification(
            db,
            case=case,
            requirement_key="mvr",
            actor_user_id="ops-1",
            payload={"notes": "Queued for manual MVR pull"},
        )
        mvr = next(r for r in case.requirements if r.requirement_key == "mvr")
        assert mvr.external_status == "PENDING_EXTERNAL"
        assert mvr.provider_key == "manual"

        with pytest.raises(ValueError, match="AI must not"):
            record_external_verification(
                db,
                case=case,
                requirement_key="mvr",
                status="VERIFIED",
                actor_user_id="ai",
                actor_type="AI",
                evidence_source="should-fail",
            )

        case = record_external_verification(
            db,
            case=case,
            requirement_key="mvr",
            status="VERIFIED",
            actor_user_id="ops-1",
            actor_type="EXTERNAL",
            evidence_source="manual_mvr_packet",
            provider_reference_id="MVR-REF-001",
            expiration_date=date.today() + timedelta(days=365),
            notes="Authoritative MVR clear recorded by ops",
        )
        mvr = next(r for r in case.requirements if r.requirement_key == "mvr")
        assert mvr.external_status == "VERIFIED"
        assert mvr.status == "VERIFIED"
        assert mvr.provider_reference_id == "MVR-REF-001"
        assert mvr.evidence_source == "manual_mvr_packet"
        assert mvr.verification_date is not None
        assert case.mvr_status == "COMPLETE"
        assert mvr.external_status in EXTERNAL_VERIFICATION_STATUSES


def test_expired_mandatory_restricts_and_opens_reverification():
    ensure_approval_engine_schema()
    org_id = _org_id()
    with SessionLocal() as db:
        case = ApprovalCase(
            id=make_uuid(),
            organization_id=org_id,
            entity_type="driver",
            display_badge="DRV-EXP2",
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
                status="VERIFIED",
                external_status="VERIFIED",
                expiration_date=date.today() - timedelta(days=1),
                evidence_source="prior_packet",
                provider_reference_id="INS-OLD",
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()
        result = monitor_case(db, case)
        assert result["action"] == "auto_restrict_expired_mandatory"
        assert "vehicle_insurance" in result["reverification_opened"]
        db.refresh(case)
        assert case.workflow_status == "RESTRICTED"
        assert case.activation_status == "RESTRICTED"
        insurance = next(r for r in case.requirements if r.requirement_key == "vehicle_insurance")
        assert insurance.external_status == "EXPIRED"
        assert insurance.status == "EXPIRED"
        assert any(
            getattr(t, "requirement_key", None) == "vehicle_insurance"
            and t.external_status == "EXPIRED"
            for t in case.external_tasks
        )

        # Re-verify with renewed evidence does not auto-reactivate; restores requirement only.
        case = record_external_verification(
            db,
            case=case,
            requirement_key="vehicle_insurance",
            status="VERIFIED",
            actor_user_id="ops-1",
            actor_type="USER",
            evidence_source="renewed_insurance_packet",
            provider_reference_id="INS-NEW",
            expiration_date=date.today() + timedelta(days=180),
        )
        insurance = next(r for r in case.requirements if r.requirement_key == "vehicle_insurance")
        assert insurance.external_status == "VERIFIED"
        assert case.workflow_status == "RESTRICTED"  # owner/reapproval path still required


def test_external_adapters_api(client: TestClient):
    token = _login(client)
    response = client.get(
        "/api/approval-engine/external-adapters",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["base_adapters"]) == len(BASE_EXTERNAL_REQUIREMENT_KEYS)
    assert all(row["vendor_selected"] is False for row in body["base_adapters"])
    assert body["remaining_vendor_decisions"]
