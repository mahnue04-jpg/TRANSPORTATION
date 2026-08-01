from __future__ import annotations

import io
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import HealthISFDriver
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
    suffix = uuid4().int % 10_000_000
    return f"917{suffix:07d}"


def _complete_payload(org_id: str, *, email: str | None = None, phone: str | None = None) -> dict:
    today = date.today()
    return {
        "organization_id": org_id,
        "legal_first_name": "Taylor",
        "legal_middle_name": "Q",
        "legal_last_name": "Applicant",
        "date_of_birth": "1990-04-12",
        "email": email or f"driver-{uuid4().hex[:8]}@example.com",
        "mobile_phone": phone or _unique_phone(),
        "home_address": "100 Main St",
        "city": "New York",
        "state": "NY",
        "zip_code": "10001",
        "emergency_contact_name": "Casey Contact",
        "emergency_contact_phone": "212-555-0199",
        "preferred_language": "English",
        "drivers_license_number": "D123456789",
        "license_issuing_state": "NY",
        "license_expiration_date": (today + timedelta(days=400)).isoformat(),
        "years_driving_experience": 8,
        "employment_type": "independent_contractor",
        "availability_days": ["monday", "wednesday", "friday"],
        "availability_start_time": "08:00",
        "availability_end_time": "18:00",
        "willing_weekends": True,
        "willing_wheelchair": True,
        "service_area_counties": "New York, Kings",
        "declaration_valid_license": True,
        "declaration_mvr_authorization": True,
        "declaration_background_authorization": True,
        "declaration_drug_alcohol_policy": True,
        "declaration_truthful_information": True,
        "electronic_signature": "Taylor Q Applicant",
        "signed_date": today.isoformat(),
    }


def _create_draft(client: TestClient, org_id: str, payload: dict | None = None) -> tuple[str, str]:
    body = payload or {"organization_id": org_id}
    response = client.post("/api/platform-ops/driver-onboarding/applications", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    return data["application"]["id"], data["applicant_access_token"]


def _applicant_headers(token: str) -> dict[str, str]:
    return {"X-Applicant-Token": token}


def test_driver_can_save_draft(client: TestClient) -> None:
    org_id = _org_id()
    app_id, applicant_token = _create_draft(client, org_id)
    payload = _complete_payload(org_id)
    payload["legal_first_name"] = "Draft"
    response = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_applicant_headers(applicant_token),
        json=payload,
    )
    assert response.status_code == 200, response.text
    assert response.json()["legal_first_name"] == "Draft"
    assert response.json()["status"] == "draft"


def test_driver_can_submit_complete_application(client: TestClient) -> None:
    org_id = _org_id()
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id))
    response = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["submitted_at"] is not None


def test_incomplete_application_rejected_with_validation(client: TestClient) -> None:
    org_id = _org_id()
    app_id, applicant_token = _create_draft(client, org_id)
    response = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["errors"]
    assert any(err["field"] == "legal_first_name" for err in detail["errors"])


def test_applicant_cannot_approve_themselves(client: TestClient) -> None:
    org_id = _org_id()
    admin_email = "admin@amicor.local"
    payload = _complete_payload(org_id, email=admin_email)
    app_id, applicant_token = _create_draft(client, org_id, payload)
    client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_applicant_headers(applicant_token),
        json=payload,
    )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    admin_token = _login(client, admin_email)
    for status in ("under_review", "background_review"):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
            headers=_auth(admin_token),
            json={"to_status": status, "confirm": True, "reason": "review"},
        )
    response = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert response.status_code == 403, response.text


def test_unauthorized_user_cannot_view_other_applicant(client: TestClient) -> None:
    org_id = _org_id()
    app_id, token_a = _create_draft(client, org_id, _complete_payload(org_id))
    _, token_b = _create_draft(client, org_id, _complete_payload(org_id))
    response = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_applicant_headers(token_b),
    )
    assert response.status_code == 403


def test_public_cannot_list_applications(client: TestClient) -> None:
    response = client.get("/api/platform-ops/driver-onboarding/applications")
    assert response.status_code in {401, 403}


def test_document_status_can_be_reviewed(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id))
    upload = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category=drivers_license_front",
        headers=_applicant_headers(applicant_token),
        files={"file": ("license-front.jpg", io.BytesIO(b"fake-image"), "image/jpeg")},
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["id"]
    review = client.patch(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{document_id}/review",
        headers=_auth(admin_token),
        json={"review_status": "accepted", "review_reason": "legible"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["review_status"] == "accepted"


def test_invalid_status_transition_rejected(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    response = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "activated", "confirm": True},
    )
    assert response.status_code == 409, response.text


def test_approval_does_not_automatically_activate(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "under_review", "confirm": True},
    )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "background_review", "confirm": True},
    )
    approve = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert approve.status_code == 200, approve.text
    body = approve.json()
    assert body["status"] == "approved"
    assert body["activated_driver_id"] is None


def test_activation_creates_one_linked_driver_and_is_idempotent(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    phone = _unique_phone()
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id, phone=phone))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    for status in ("under_review", "background_review"):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
            headers=_auth(admin_token),
            json={"to_status": status, "confirm": True},
        )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    first = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert first.status_code == 200, first.text
    driver_id = first.json()["driver_id"]
    second = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert second.status_code == 200, second.text
    assert second.json()["driver_id"] == driver_id
    assert second.json()["idempotent"] is True

    with SessionLocal() as db:
        drivers = db.query(HealthISFDriver).filter(HealthISFDriver.phone == phone).all()
        assert len(drivers) == 1


def test_newly_activated_driver_starts_offline(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    phone = _unique_phone()
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id, phone=phone))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    for status in ("under_review", "background_review"):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
            headers=_auth(admin_token),
            json={"to_status": status, "confirm": True},
        )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    activated = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    assert activated.status_code == 200, activated.text
    driver_id = activated.json()["driver_id"]
    with SessionLocal() as db:
        driver = hs.get_driver_by_id(db, driver_id)
        assert driver is not None
        status_value = getattr(driver.status, "value", str(driver.status))
        assert str(status_value).lower().endswith("offline") or str(status_value).lower() == "unavailable"


def test_existing_production_drivers_unaffected(client: TestClient) -> None:
    org_id = _org_id()
    with SessionLocal() as db:
        before = {
            str(row.id): {
                "phone": row.phone,
                "name": row.name,
                "status": row.status,
                "vehicle_plate": row.vehicle_plate,
            }
            for row in db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all()
        }

    admin_token = _login(client, "admin@amicor.local")
    phone = _unique_phone()
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id, phone=phone))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    for status in ("under_review", "background_review"):
        client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
            headers=_auth(admin_token),
            json={"to_status": status, "confirm": True},
        )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/approve",
        headers=_auth(admin_token),
        json={"confirm": True},
    )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/activate",
        headers=_auth(admin_token),
        json={"confirm": True},
    )

    with SessionLocal() as db:
        after = {
            str(row.id): {
                "phone": row.phone,
                "name": row.name,
                "status": row.status,
                "vehicle_plate": row.vehicle_plate,
            }
            for row in db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all()
        }
    for driver_id, snapshot in before.items():
        assert after[driver_id] == snapshot


def test_status_change_creates_audit_record(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/status",
        headers=_auth(admin_token),
        json={"to_status": "under_review", "confirm": True},
    )
    with SessionLocal() as db:
        audits = (
            db.query(PlatformDriverOnboardingAuditEvent)
            .filter(PlatformDriverOnboardingAuditEvent.application_id == app_id)
            .all()
        )
        assert any(event.event_type == "application_submitted" for event in audits)
        assert any(event.to_status == "under_review" for event in audits)


def test_license_masked_in_admin_list(client: TestClient) -> None:
    org_id = _org_id()
    admin_token = _login(client, "admin@amicor.local")
    app_id, applicant_token = _create_draft(client, org_id, _complete_payload(org_id))
    client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_applicant_headers(applicant_token),
        json={"confirmation": True},
    )
    listed = client.get("/api/platform-ops/driver-onboarding/applications", headers=_auth(admin_token))
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item["id"] == app_id)
    assert row["mobile_phone"].startswith("***")

    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_auth(admin_token),
    )
    assert detail.status_code == 200
    assert detail.json()["drivers_license_number_masked"].endswith("6789")
