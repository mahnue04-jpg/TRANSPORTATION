"""Work Setup: in-app ICA, electronic W-9, and Stripe Connect payout.

Uses synthetic applications only. Does not create or mutate production Driver 001.
"""
from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.approval_engine.models import ensure_approval_engine_schema
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.onboarding.stripe_connect import (
    FakeStripeConnectClient,
    set_stripe_connect_client_override,
)
from tests.work_setup_testutil import complete_secure_work_setup


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_stripe_override():
    set_stripe_connect_client_override(None)
    yield
    set_stripe_connect_client_override(None)


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "admin@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _create_draft(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={
            "organization_id": _org_id(),
            "legal_first_name": "Casey",
            "legal_last_name": "Driver",
            "email": f"worksetup-{uuid4().hex[:8]}@example.com",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    return body["application"]["id"], body["applicant_access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"X-Applicant-Token": token}


def test_apply_page_uses_status_cards_instead_of_file_upload():
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "static" / "platform-ops"
    html = (static / "driver-apply.html").read_text(encoding="utf-8")
    js = (static / "driver-apply.js").read_text(encoding="utf-8")
    assert "work-setup-card" in html
    assert "Set Up Payout Account" in html
    assert "file_contractor" not in html
    assert "Please review and sign the Independent Contractor Agreement." in js
    assert "Please complete your secure tax information." in js
    assert "Payout setup is not complete." in js
    assert "driver-apply.js?v=20260902.1" in html


def test_ica_unsigned_then_signed_reload_shows_on_file(client: TestClient):
    app_id, token = _create_draft(client)
    headers = _headers(token)
    before = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup",
        headers=headers,
    )
    assert before.status_code == 200, before.text
    assert before.json()["agreement"]["complete"] is False
    assert before.json()["agreement"]["status"] == "Not signed"

    packet = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/agreement",
        headers=headers,
    )
    assert packet.status_code == 200, packet.text
    assert "Independent Contractor Agreement" in packet.json()["title"]
    assert packet.json()["text"]

    unsigned = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/agreement/sign",
        headers=headers,
        json={"typed_signature": "Casey Driver", "accepted": False},
    )
    assert unsigned.status_code == 400, unsigned.text

    signed = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/agreement/sign",
        headers=headers,
        json={"typed_signature": "Casey Driver", "accepted": True},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["agreement"]["complete"] is True
    assert signed.json()["agreement"]["status"] == "Signed / On file"

    reload_status = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup",
        headers=headers,
    )
    assert reload_status.json()["agreement"]["complete"] is True
    assert reload_status.json()["agreement"]["status"] == "Signed / On file"

    again = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/agreement/sign",
        headers=headers,
        json={"typed_signature": "Casey Driver", "accepted": True},
    )
    assert again.status_code == 200, again.text
    with SessionLocal() as db:
        docs = (
            db.query(PlatformDriverOnboardingDocument)
            .filter(
                PlatformDriverOnboardingDocument.application_id == app_id,
                PlatformDriverOnboardingDocument.category == "independent_contractor_agreement",
            )
            .all()
        )
        assert len(docs) == 1
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        assert row.status == "draft"
        assert row.agreement_version
        assert row.agreement_accepted_at is not None


def test_w9_incomplete_then_secure_completion_persists(client: TestClient):
    app_id, token = _create_draft(client)
    headers = _headers(token)
    before = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup",
        headers=headers,
    )
    assert before.json()["tax"]["complete"] is False
    assert before.json()["tax"]["status"] == "Incomplete"
    assert before.json()["tax"]["stores_ssn_tin"] is False

    rejected = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/w9",
        headers=headers,
        json={
            "tax_classification": "individual",
            "legal_name": "Casey Driver",
            "ssn": "123-45-6789",
            "certify_accurate": True,
            "certify_us_person": True,
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "ssn" in rejected.text.lower() or "tin" in rejected.text.lower() or "sensitive" in rejected.text.lower()

    completed = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/w9",
        headers=headers,
        json={
            "tax_classification": "individual",
            "legal_name": "Casey Driver",
            "certify_accurate": True,
            "certify_us_person": True,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["tax"]["complete"] is True
    assert completed.json()["tax"]["status"] == "Complete"
    assert completed.json()["tax"]["stores_ssn_tin"] is False

    reload_status = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup",
        headers=headers,
    )
    assert reload_status.json()["tax"]["complete"] is True
    assert reload_status.json()["tax"]["stores_ssn_tin"] is False
    assert "123-45-6789" not in reload_status.text

    again = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/w9",
        headers=headers,
        json={
            "tax_classification": "partnership",
            "legal_name": "Changed Name",
            "certify_accurate": True,
            "certify_us_person": True,
        },
    )
    assert again.status_code == 200, again.text
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        assert row.w9_workflow_status == "completed"
        assert row.w9_tax_classification == "individual"
        docs = (
            db.query(PlatformDriverOnboardingDocument)
            .filter(
                PlatformDriverOnboardingDocument.application_id == app_id,
                PlatformDriverOnboardingDocument.category == "w9_status",
            )
            .all()
        )
        assert len(docs) == 1


def test_stripe_onboarding_start_return_persists_account_and_status(client: TestClient):
    app_id, token = _create_draft(client)
    headers = _headers(token)
    fake = FakeStripeConnectClient()
    set_stripe_connect_client_override(fake)
    start = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/payout/start",
        headers=headers,
        json={
            "return_url": "https://amicor.test/driver-apply?work_setup=stripe_return",
            "refresh_url": "https://amicor.test/driver-apply?work_setup=stripe_refresh",
        },
    )
    assert start.status_code == 200, start.text
    payout = start.json()["payout"]
    assert payout["complete"] is False
    assert payout["status_key"] == "pending_verification"
    assert payout["onboarding_url"]
    assert fake.created_count == 1
    first_account = fake.last_account_id

    start_again = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/payout/start",
        headers=headers,
        json={
            "return_url": "https://amicor.test/driver-apply?work_setup=stripe_return",
            "refresh_url": "https://amicor.test/driver-apply?work_setup=stripe_refresh",
        },
    )
    assert start_again.status_code == 200, start_again.text
    assert fake.created_count == 1
    assert fake.last_account_id == first_account

    fake.mark_complete()
    refreshed = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/payout/refresh",
        headers=headers,
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["payout"]["complete"] is True
    assert refreshed.json()["payout"]["status"] == "Complete"
    assert "acct_" not in str(refreshed.json()["payout"])
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        assert row.stripe_account_id == first_account
        assert row.stripe_onboarding_status == "complete"
        assert row.stripe_payouts_enabled is True


def test_reload_retains_all_three_statuses_without_duplicates(client: TestClient):
    app_id, token = _create_draft(client)
    complete_secure_work_setup(client, app_id, token, legal_name="Casey Driver")
    first = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_headers(token),
    )
    assert first.status_code == 200, first.text
    work = first.json()["work_setup"]
    assert work["agreement"]["complete"] is True
    assert work["tax"]["complete"] is True
    assert work["payout"]["complete"] is True
    assert first.json()["resume_section_key"] != "work_setup" or first.json()["section_completion"][-1]["complete"] is True
    assert first.json()["status"] == "draft"

    complete_secure_work_setup(client, app_id, token, legal_name="Casey Driver")
    second = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup",
        headers=_headers(token),
    )
    assert second.json()["all_complete"] is True
    with SessionLocal() as db:
        ica = (
            db.query(PlatformDriverOnboardingDocument)
            .filter(
                PlatformDriverOnboardingDocument.application_id == app_id,
                PlatformDriverOnboardingDocument.category == "independent_contractor_agreement",
            )
            .all()
        )
        w9 = (
            db.query(PlatformDriverOnboardingDocument)
            .filter(
                PlatformDriverOnboardingDocument.application_id == app_id,
                PlatformDriverOnboardingDocument.category == "w9_status",
            )
            .all()
        )
        assert len(ica) == 1
        assert len(w9) == 1
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        assert row.status == "draft"


def test_no_banking_or_ssn_data_exposed_and_submit_is_not_automatic(client: TestClient):
    app_id, token = _create_draft(client)
    complete_secure_work_setup(client, app_id, token, legal_name="Casey Driver")
    detail = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers=_headers(token),
    )
    payload = detail.json()
    work = payload.get("work_setup") or {}
    assert work.get("tax", {}).get("stores_ssn_tin") is False
    assert "123-45-6789" not in detail.text
    assert "acct_" not in str(work.get("payout") or {})
    assert payload["status"] == "draft"
    assert detail.json()["submitted_at"] is None


def test_driver_001_shaped_record_stays_untouched(client: TestClient):
    org_id = _org_id()
    with SessionLocal() as db:
        existing = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(
                PlatformDriverOnboardingApplication.organization_id == org_id,
                PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001",
            )
            .first()
        )
        snapshot = None
        if existing is not None:
            snapshot = {
                "id": existing.id,
                "status": existing.status,
                "agreement_status": existing.agreement_status,
                "w9_workflow_status": existing.w9_workflow_status,
                "stripe_account_id": getattr(existing, "stripe_account_id", None),
                "updated_at": existing.updated_at,
            }

    app_id, token = _create_draft(client)
    complete_secure_work_setup(client, app_id, token, legal_name="Casey Driver")
    blocked = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={
            "organization_id": org_id,
            "legal_first_name": "Driver",
            "legal_last_name": "001",
            "email": "driver001.safe@example.com",
            "internal_driver_number": "DRV-001",
        },
    )
    assert blocked.status_code in {200, 400, 409}, blocked.text
    if blocked.status_code == 200:
        created_id = blocked.json()["application"]["id"]
        created_number = blocked.json()["application"].get("internal_driver_number")
        assert created_id != (snapshot or {}).get("id")
        assert created_number != "DRV-001"

    with SessionLocal() as db:
        if snapshot is None:
            still = (
                db.query(PlatformDriverOnboardingApplication)
                .filter(
                    PlatformDriverOnboardingApplication.organization_id == org_id,
                    PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001",
                )
                .all()
            )
            assert still == []
            return
        current = db.query(PlatformDriverOnboardingApplication).filter_by(id=snapshot["id"]).one()
        assert current.status == snapshot["status"]
        assert current.agreement_status == snapshot["agreement_status"]
        assert current.w9_workflow_status == snapshot["w9_workflow_status"]
        assert getattr(current, "stripe_account_id", None) == snapshot["stripe_account_id"]
        assert current.updated_at == snapshot["updated_at"]


def test_submit_names_missing_work_setup_requirements(client: TestClient):
    org_id = _org_id()
    today = date.today()
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={
            "organization_id": org_id,
            "legal_first_name": "Casey",
            "legal_last_name": "Driver",
            "date_of_birth": "1988-06-01",
            "email": f"worksetup-submit-{uuid4().hex[:8]}@example.com",
            "mobile_phone": "612-555-2211",
            "home_address": "200 Lake St",
            "city": "Minneapolis",
            "state": "MN",
            "zip_code": "55408",
            "emergency_contact_name": "Alex Contact",
            "emergency_contact_phone": "612-555-0199",
            "drivers_license_number": "MN-WORK-441",
            "license_issuing_state": "MN",
            "license_expiration_date": (today + timedelta(days=400)).isoformat(),
            "declaration_valid_license": True,
            "declaration_mvr_authorization": True,
            "declaration_truthful_information": True,
            "electronic_signature": "Casey Driver",
            "signed_date": today.isoformat(),
        },
    )
    assert created.status_code == 200, created.text
    app_id = created.json()["application"]["id"]
    token = created.json()["applicant_access_token"]
    submitted = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/submit",
        headers=_headers(token),
        json={"confirmation": True},
    )
    assert submitted.status_code == 422, submitted.text
    messages = " ".join(err["message"] for err in submitted.json()["detail"]["errors"])
    assert "Please review and sign the Independent Contractor Agreement." in messages
    assert "Please complete your secure tax information." in messages
    assert "Payout setup is not complete." in messages
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        assert row.status == "draft"
