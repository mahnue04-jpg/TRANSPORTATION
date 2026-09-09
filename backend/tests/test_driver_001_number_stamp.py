"""Idempotent DRV-001 number stamp on one existing application.

Does not create a second Driver 001 file, approve, activate, or touch documents.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app
from app.modules.approval_engine.models import ApprovalCase, ensure_approval_engine_schema
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.onboarding.service import (
    DRIVER_001_NUMBER,
    EXISTING_DRIVER_001_APPLICATION_ID,
    stamp_existing_driver_001_number,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    return TestClient(app)


def _login(client: TestClient, email: str = "admin@amicor.local") -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _snapshot_application(row: PlatformDriverOnboardingApplication) -> dict:
    return {
        attr.key: deepcopy(getattr(row, attr.key))
        for attr in sa_inspect(row).mapper.column_attrs
        if attr.key != "internal_driver_number"
    }


def _snapshot_documents(rows: list[PlatformDriverOnboardingDocument]) -> list[dict]:
    return [
        {
            "id": row.id,
            "category": row.category,
            "review_status": row.review_status,
            "storage_backend": row.storage_backend,
            "storage_ref": row.storage_ref,
            "original_filename": row.original_filename,
            "content_type": row.content_type,
            "byte_size": row.byte_size,
            "status_only_value": row.status_only_value,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in sorted(rows, key=lambda item: item.id)
    ]


def _seed_pair(
    *,
    with_case: bool = True,
    badge: str = DRIVER_001_NUMBER,
    target_id: str | None = None,
    org_id: str | None = None,
):
    org_id = org_id or f"org-stamp-{uuid4()}"
    target_id = target_id or uuid4()
    other_id = uuid4()
    with SessionLocal() as db:
        target = PlatformDriverOnboardingApplication(
            id=target_id,
            organization_id=org_id,
            status="draft",
            legal_first_name="Saye",
            legal_last_name="Monibah",
            email="stamp.target@example.com",
            mobile_phone="6125550683",
            vehicle_year=2021,
            vehicle_make="Dodge",
            vehicle_model="Ram 1500",
            created_at=now(),
            updated_at=now(),
        )
        other = PlatformDriverOnboardingApplication(
            id=other_id,
            organization_id=org_id,
            status="draft",
            legal_first_name="Other",
            legal_last_name="Applicant",
            email="stamp.other@example.com",
            created_at=now(),
            updated_at=now(),
        )
        document_id = uuid4()
        document = PlatformDriverOnboardingDocument(
            id=document_id,
            application_id=target.id,
            organization_id=org_id,
            category="drivers_license_front",
            storage_backend="s3_private",
            storage_ref="s3://private/stamp-license-front",
            original_filename="front.jpg",
            content_type="image/jpeg",
            byte_size=4930505,
            review_status="pending",
            created_at=now(),
            updated_at=now(),
        )
        db.add_all([target, other, document])
        case_id = None
        if with_case:
            case = ApprovalCase(
                id=uuid4(),
                organization_id=org_id,
                display_badge=badge,
                legal_name="Saye Monibah",
                platform_ops_application_id=target.id,
                workflow_status="ACTION_REQUIRED",
                activation_status="NOT_ACTIVE",
                owner_approval_status="PENDING",
            )
            db.add(case)
            case_id = case.id
        db.commit()
    return {
        "org_id": org_id,
        "target_id": target_id,
        "other_id": other_id,
        "case_id": case_id,
        "document_id": document_id,
    }


def test_stamp_assigns_only_the_linked_application():
    seeded = _seed_pair()
    with SessionLocal() as db:
        target = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["target_id"]).one()
        other = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["other_id"]).one()
        docs = db.query(PlatformDriverOnboardingDocument).filter_by(application_id=target.id).all()
        case = db.query(ApprovalCase).filter_by(id=seeded["case_id"]).one()
        before_target = _snapshot_application(target)
        before_other = _snapshot_application(other)
        before_docs = _snapshot_documents(docs)
        before_case = {
            "workflow_status": case.workflow_status,
            "activation_status": case.activation_status,
            "owner_approval_status": case.owner_approval_status,
            "health_isf_driver_id": case.health_isf_driver_id,
            "platform_ops_application_id": case.platform_ops_application_id,
        }
        assert target.internal_driver_number is None

        result = stamp_existing_driver_001_number(db, application_id=target.id)

        db.expire_all()
        target = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["target_id"]).one()
        other = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["other_id"]).one()
        docs = db.query(PlatformDriverOnboardingDocument).filter_by(application_id=target.id).all()
        case = db.query(ApprovalCase).filter_by(id=seeded["case_id"]).one()
        numbered = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(
                PlatformDriverOnboardingApplication.organization_id == seeded["org_id"],
                PlatformDriverOnboardingApplication.internal_driver_number == DRIVER_001_NUMBER,
            )
            .all()
        )

    assert result["rows_affected"] == 1
    assert result["already_stamped"] is False
    assert result["application_id"] == seeded["target_id"]
    assert result["internal_driver_number"] == DRIVER_001_NUMBER
    assert len(numbered) == 1
    assert numbered[0].id == seeded["target_id"]
    assert other.internal_driver_number is None
    assert _snapshot_application(target) == before_target
    assert _snapshot_application(other) == before_other
    assert _snapshot_documents(docs) == before_docs
    assert {
        "workflow_status": case.workflow_status,
        "activation_status": case.activation_status,
        "owner_approval_status": case.owner_approval_status,
        "health_isf_driver_id": case.health_isf_driver_id,
        "platform_ops_application_id": case.platform_ops_application_id,
    } == before_case


def test_stamp_repeat_is_idempotent():
    seeded = _seed_pair()
    with SessionLocal() as db:
        first = stamp_existing_driver_001_number(db, application_id=seeded["target_id"])
    with SessionLocal() as db:
        second = stamp_existing_driver_001_number(db, application_id=seeded["target_id"])
        numbered = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(
                PlatformDriverOnboardingApplication.organization_id == seeded["org_id"],
                PlatformDriverOnboardingApplication.internal_driver_number == DRIVER_001_NUMBER,
            )
            .all()
        )
    assert first["rows_affected"] == 1
    assert second["already_stamped"] is True
    assert second["rows_affected"] == 0
    assert second["internal_driver_number"] == DRIVER_001_NUMBER
    assert len(numbered) == 1
    assert numbered[0].id == seeded["target_id"]


def test_stamp_fails_when_another_application_already_has_drv_001():
    seeded = _seed_pair()
    with SessionLocal() as db:
        other = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["other_id"]).one()
        other.internal_driver_number = DRIVER_001_NUMBER
        db.commit()

    with SessionLocal() as db:
        target = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["target_id"]).one()
        docs = db.query(PlatformDriverOnboardingDocument).filter_by(application_id=target.id).all()
        before_target = _snapshot_application(target)
        before_docs = _snapshot_documents(docs)
        with pytest.raises(ValueError, match="another application already stores DRV-001"):
            stamp_existing_driver_001_number(db, application_id=target.id)
        db.expire_all()
        target = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["target_id"]).one()
        other = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["other_id"]).one()
        docs = db.query(PlatformDriverOnboardingDocument).filter_by(application_id=target.id).all()

    assert target.internal_driver_number is None
    assert other.internal_driver_number == DRIVER_001_NUMBER
    assert _snapshot_application(target) == before_target
    assert _snapshot_documents(docs) == before_docs


def test_stamp_fails_when_case_does_not_point_at_application():
    seeded = _seed_pair()
    with SessionLocal() as db:
        case = db.query(ApprovalCase).filter_by(id=seeded["case_id"]).one()
        case.platform_ops_application_id = seeded["other_id"]
        db.commit()

    with SessionLocal() as db:
        with pytest.raises(ValueError, match="does not point at this application"):
            stamp_existing_driver_001_number(db, application_id=seeded["target_id"])
        target = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["target_id"]).one()
        assert target.internal_driver_number is None


def test_stamp_fails_when_badge_is_not_drv_001():
    seeded = _seed_pair(badge="DRV-999")
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="no approval case with display badge DRV-001"):
            stamp_existing_driver_001_number(db, application_id=seeded["target_id"])
        target = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded["target_id"]).one()
        assert target.internal_driver_number is None


def test_api_is_locked_to_the_existing_production_application(client: TestClient):
    seeded = _seed_pair()
    headers = {"Authorization": f"Bearer {_login(client)}"}
    wrong = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{seeded['target_id']}/stamp-driver-001-number",
        headers=headers,
    )
    assert wrong.status_code == 400, wrong.text
    assert "locked" in wrong.text.lower()

    forbidden = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{EXISTING_DRIVER_001_APPLICATION_ID}/stamp-driver-001-number",
        headers={"Authorization": f"Bearer {_login(client, 'dispatcher@amicor.local')}"},
    )
    assert forbidden.status_code == 403

    seeded_prod = _seed_pair(target_id=EXISTING_DRIVER_001_APPLICATION_ID)
    ok = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{EXISTING_DRIVER_001_APPLICATION_ID}/stamp-driver-001-number",
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["application_id"] == EXISTING_DRIVER_001_APPLICATION_ID
    assert body["internal_driver_number"] == DRIVER_001_NUMBER
    assert body["rows_affected"] == 1

    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{EXISTING_DRIVER_001_APPLICATION_ID}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["internal_driver_number"] == DRIVER_001_NUMBER
    with SessionLocal() as db:
        other = db.query(PlatformDriverOnboardingApplication).filter_by(id=seeded_prod["other_id"]).one()
        assert other.internal_driver_number is None
