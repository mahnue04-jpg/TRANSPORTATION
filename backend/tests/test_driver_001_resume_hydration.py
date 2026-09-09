"""Driver 001 existing-application resume/hydration.

Uses synthetic applications only. Does not touch production Driver 001 data.
Does not approve, activate, or create a Health ISF driver.
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import now
from app.main import app
from app.modules.approval_engine.models import ensure_approval_engine_schema
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.onboarding import service as onboarding_service

STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "platform-ops"
APPLY_HTML = STATIC_DIR / "driver-apply.html"
APPLY_JS = STATIC_DIR / "driver-apply.js"
APPLY_CSS = STATIC_DIR / "driver-onboarding.css"

REQUIRED_DOC_CATEGORIES = (
    "drivers_license_front",
    "drivers_license_back",
    "vehicle_registration",
    "proof_of_auto_insurance",
    "w9_status",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_approval_engine_schema()
    return TestClient(app)


def _driver_001_payload(org_id: str, *, email: str | None = None) -> dict:
    today = date.today()
    return {
        "organization_id": org_id,
        "legal_first_name": "Saye",
        "legal_last_name": "Monibah",
        "date_of_birth": "1977-12-24",
        "email": email or f"drv001.resume.{uuid4().hex[:8]}@example.com",
        "mobile_phone": "612-555-0683",
        "home_address": "2823 N Aldrich Ave",
        "city": "Minneapolis",
        "state": "MN",
        "zip_code": "55411",
        "emergency_contact_name": "Sherita Monibah",
        "emergency_contact_phone": "612-555-7033",
        "drivers_license_number": "MN7107TEST",
        "license_issuing_state": "MN",
        "license_expiration_date": (today + timedelta(days=400)).isoformat(),
        "vehicle_year": 2021,
        "vehicle_make": "Dodge",
        "vehicle_model": "Ram 1500",
        "vehicle_license_plate": "ZKZ 673",
        "vehicle_vin": "1C6SRFKT3MN723043",
        "declaration_mvr_authorization": True,
        "declaration_valid_license": True,
        "authorize_qualification_checks": True,
        "electronic_signature": "Saye N Monibah",
        "signed_date": today.isoformat(),
    }


def _create_driver_001_draft(client: TestClient, *, org_id: str | None = None) -> tuple[str, str, dict]:
    org_id = org_id or f"org-drv001-resume-{uuid4().hex[:8]}"
    payload = _driver_001_payload(org_id)
    created = client.post("/api/platform-ops/driver-onboarding/applications", json=payload)
    assert created.status_code == 200, created.text
    assert created.json().get("resumed_existing") is False
    app_id = created.json()["application"]["id"]
    token = created.json()["applicant_access_token"]
    headers = {"X-Applicant-Token": token}
    for category, name in (
        ("drivers_license_front", "front-test-only.jpg"),
        ("drivers_license_back", "back-test-only.jpg"),
        ("vehicle_registration", "reg-test-only.jpg"),
        ("proof_of_auto_insurance", "ins-test-only.pdf"),
    ):
        uploaded = client.post(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/documents?category={category}",
            headers=headers,
            files={"file": (name, io.BytesIO(b"TEST-ONLY-" + category.encode()), "image/jpeg")},
        )
        assert uploaded.status_code == 200, uploaded.text
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        row.internal_driver_number = onboarding_service.DRIVER_001_NUMBER
        db.add(
            PlatformDriverOnboardingDocument(
                id=str(uuid4()),
                application_id=app_id,
                organization_id=org_id,
                category="w9_status",
                storage_backend="status_only",
                review_status="accepted",
                status_only_value="provided",
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()
    return app_id, token, payload


def _count_driver_001(org_id: str) -> list[str]:
    with SessionLocal() as db:
        rows = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(
                PlatformDriverOnboardingApplication.organization_id == org_id,
                PlatformDriverOnboardingApplication.internal_driver_number == onboarding_service.DRIVER_001_NUMBER,
            )
            .all()
        )
        return [row.id for row in rows]


def test_driver_001_identity_resumes_existing_application(client: TestClient):
    app_id, _token, payload = _create_driver_001_draft(client)
    org_id = payload["organization_id"]

    by_email = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": org_id, "email": payload["email"]},
    )
    assert by_email.status_code == 200, by_email.text
    body = by_email.json()
    assert body["resumed_existing"] is True
    assert body["application"]["id"] == app_id
    assert body["application"]["internal_driver_number"] == "DRV-001"
    assert body["applicant_access_token"]

    by_name = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={
            "organization_id": org_id,
            "legal_first_name": "Saye",
            "legal_last_name": "Monibah",
        },
    )
    assert by_name.status_code == 200, by_name.text
    assert by_name.json()["resumed_existing"] is True
    assert by_name.json()["application"]["id"] == app_id
    assert _count_driver_001(org_id) == [app_id]


def test_driver_001_org_less_identity_resumes_pinned_application(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    app_id, _token, payload = _create_driver_001_draft(client)
    monkeypatch.setattr(onboarding_service, "EXISTING_DRIVER_001_APPLICATION_ID", app_id)
    resumed = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"email": payload["email"]},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["resumed_existing"] is True
    assert resumed.json()["application"]["id"] == app_id
    assert _count_driver_001(payload["organization_id"]) == [app_id]


def test_driver_001_resume_loads_fields_documents_and_work_setup_step(client: TestClient):
    app_id, _token, payload = _create_driver_001_draft(client)
    resumed = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": payload["organization_id"], "email": payload["email"]},
    )
    assert resumed.status_code == 200, resumed.text
    token = resumed.json()["applicant_access_token"]
    loaded = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
    )
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["id"] == app_id
    assert body["legal_first_name"] == "Saye"
    assert body["legal_last_name"] == "Monibah"
    assert body["email"] == payload["email"]
    assert body["vehicle_year"] == 2021
    assert body["vehicle_make"] == "Dodge"
    assert body["vehicle_model"] == "Ram 1500"
    assert body["vehicle_license_plate"] == "ZKZ 673"
    assert body["internal_driver_number"] == "DRV-001"
    assert body["status"] == "draft"
    assert body["activated_driver_id"] is None
    assert body["approved_at"] is None
    assert body["resume_step"] == 5
    assert body["resume_section_key"] == "work_setup"
    complete = {item["key"]: item["complete"] for item in body["section_completion"]}
    assert complete["about_you"] is True
    assert complete["driving"] is True
    assert complete["vehicle"] is True
    assert complete["authorization"] is True
    assert complete["work_setup"] is False
    docs = {doc["category"]: doc for doc in body["documents"]}
    assert set(docs) >= set(REQUIRED_DOC_CATEGORIES)
    assert docs["drivers_license_front"]["review_status"] == "pending"
    assert docs["drivers_license_back"]["review_status"] == "pending"
    assert docs["vehicle_registration"]["review_status"] == "pending"
    assert docs["proof_of_auto_insurance"]["review_status"] == "pending"
    assert docs["w9_status"]["review_status"] == "accepted"
    assert (body.get("work_setup") or {}).get("all_complete") is False


def test_driver_001_save_draft_reloads_same_application(client: TestClient):
    app_id, _token, payload = _create_driver_001_draft(client)
    resumed = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": payload["organization_id"], "email": payload["email"]},
    )
    token = resumed.json()["applicant_access_token"]
    saved = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
        json={"organization_id": payload["organization_id"], "preferred_language": "English"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["id"] == app_id
    assert saved.json()["vehicle_make"] == "Dodge"
    reloaded = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
    )
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["id"] == app_id
    assert reloaded.json()["preferred_language"] == "English"
    assert reloaded.json()["internal_driver_number"] == "DRV-001"
    assert _count_driver_001(payload["organization_id"]) == [app_id]


def test_driver_001_captcha_empty_save_does_not_clear_saved_data(client: TestClient):
    app_id, _token, payload = _create_driver_001_draft(client)
    resumed = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": payload["organization_id"], "email": payload["email"]},
    )
    token = resumed.json()["applicant_access_token"]
    emptied = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
        json={
            "organization_id": payload["organization_id"],
            "legal_first_name": "",
            "legal_last_name": "",
            "email": "",
            "vehicle_make": "",
            "vehicle_model": "",
            "electronic_signature": "",
            "declaration_mvr_authorization": False,
        },
    )
    assert emptied.status_code == 200, emptied.text
    body = emptied.json()
    assert body["id"] == app_id
    assert body["legal_first_name"] == "Saye"
    assert body["email"] == payload["email"]
    assert body["vehicle_make"] == "Dodge"
    assert body["vehicle_model"] == "Ram 1500"
    assert body["electronic_signature"] == payload["electronic_signature"]
    assert body["declaration_mvr_authorization"] is True
    assert body["internal_driver_number"] == "DRV-001"
    assert body["status"] == "draft"
    assert body["activated_driver_id"] is None
    assert len(body["documents"]) == 5


def test_driver_001_number_and_activation_stay_unchanged_after_resume(client: TestClient):
    app_id, _token, payload = _create_driver_001_draft(client)
    with SessionLocal() as db:
        before = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        snapshot = {
            "internal_driver_number": before.internal_driver_number,
            "status": before.status,
            "activated_driver_id": before.activated_driver_id,
            "approved_at": before.approved_at,
            "agreement_status": before.agreement_status,
            "w9_workflow_status": before.w9_workflow_status,
            "stripe_onboarding_status": before.stripe_onboarding_status,
            "vehicle_make": before.vehicle_make,
            "vehicle_vin": before.vehicle_vin,
        }
        doc_refs = [
            (row.id, row.storage_ref, row.review_status)
            for row in db.query(PlatformDriverOnboardingDocument).filter_by(application_id=app_id).all()
        ]
    client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": payload["organization_id"], "email": payload["email"]},
    )
    with SessionLocal() as db:
        after = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        assert after.internal_driver_number == snapshot["internal_driver_number"] == "DRV-001"
        assert after.status == snapshot["status"] == "draft"
        assert after.activated_driver_id == snapshot["activated_driver_id"] is None
        assert after.approved_at == snapshot["approved_at"] is None
        assert after.agreement_status == snapshot["agreement_status"] is None
        assert after.w9_workflow_status == snapshot["w9_workflow_status"]
        assert after.stripe_onboarding_status == snapshot["stripe_onboarding_status"]
        assert after.vehicle_make == snapshot["vehicle_make"] == "Dodge"
        assert after.vehicle_vin == snapshot["vehicle_vin"]
        after_docs = [
            (row.id, row.storage_ref, row.review_status)
            for row in db.query(PlatformDriverOnboardingDocument).filter_by(application_id=app_id).all()
        ]
        assert after_docs == doc_refs


def test_unrelated_create_does_not_replace_driver_001(client: TestClient):
    app_id, _token, payload = _create_driver_001_draft(client)
    other = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={
            "organization_id": payload["organization_id"],
            "legal_first_name": "New",
            "legal_last_name": "Applicant",
            "email": f"other.{uuid4().hex[:8]}@example.com",
        },
    )
    assert other.status_code == 200, other.text
    assert other.json()["resumed_existing"] is False
    assert other.json()["application"]["id"] != app_id
    assert _count_driver_001(payload["organization_id"]) == [app_id]


def test_driver_001_resume_js_contract():
    html = APPLY_HTML.read_text(encoding="utf-8")
    js = APPLY_JS.read_text(encoding="utf-8")
    assert "driver-apply.js?v=20260909.1" in html
    assert 'id="existing-documents"' in html
    assert "recoverAfterChallengeReset" in js
    assert "adoptCreatedOrResumedApplication" in js
    assert "hasResumeIdentity" in js
    assert "resumed_existing" in js
    assert "payloadFromForm()" in js
    assert "A new application was not created" in js
    assert "pending review" in js
    assert "w9_status" in js


def _browser_driver_001_resume() -> None:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    html = APPLY_HTML.read_text(encoding="utf-8")
    js = APPLY_JS.read_text(encoding="utf-8")
    css = APPLY_CSS.read_text(encoding="utf-8")
    payload = {
        "id": "ed17c75c-04ec-407a-aba6-a48988d5051c",
        "organization_id": "org-resume-001",
        "status": "draft",
        "internal_driver_number": "DRV-001",
        "legal_first_name": "Saye",
        "legal_last_name": "Monibah",
        "email": "saye.resume@example.com",
        "mobile_phone": "612-555-0683",
        "home_address": "2823 N Aldrich Ave",
        "city": "Minneapolis",
        "state": "MN",
        "zip_code": "55411",
        "date_of_birth": "1977-12-24",
        "emergency_contact_name": "Sherita Monibah",
        "emergency_contact_phone": "612-555-7033",
        "drivers_license_number_masked": "*********7107",
        "license_issuing_state": "MN",
        "license_expiration_date": "2029-12-24",
        "vehicle_year": 2021,
        "vehicle_make": "Dodge",
        "vehicle_model": "Ram 1500",
        "vehicle_license_plate": "ZKZ 673",
        "declaration_mvr_authorization": True,
        "declaration_valid_license": True,
        "declaration_background_authorization": True,
        "electronic_signature": "Saye N Monibah",
        "signed_date": "2026-08-17",
        "resume_step": 5,
        "resume_section_key": "work_setup",
        "resume_section_label": "Work setup",
        "section_completion": [
            {"step": 1, "key": "about_you", "label": "About you", "complete": True},
            {"step": 2, "key": "driving", "label": "Driving", "complete": True},
            {"step": 3, "key": "vehicle", "label": "Vehicle", "complete": True},
            {"step": 4, "key": "authorization", "label": "Authorization", "complete": True},
            {"step": 5, "key": "work_setup", "label": "Work setup", "complete": False},
        ],
        "work_setup": {
            "all_complete": False,
            "agreement": {"complete": False, "status": "Not signed"},
            "tax": {"complete": True, "status": "Complete"},
            "payout": {"complete": False, "status": "Not started"},
        },
        "documents": [
            {"id": "doc-front", "category": "drivers_license_front", "review_status": "pending", "original_filename": "front.jpg"},
            {"id": "doc-back", "category": "drivers_license_back", "review_status": "pending", "original_filename": "back.jpg"},
            {"id": "doc-reg", "category": "vehicle_registration", "review_status": "pending", "original_filename": "reg.jpg"},
            {"id": "doc-ins", "category": "proof_of_auto_insurance", "review_status": "pending", "original_filename": "ins.pdf"},
            {"id": "doc-w9", "category": "w9_status", "review_status": "pending", "status_only_value": "provided"},
        ],
    }
    posts = []

    def handle_route(route):
        url = route.request.url
        method = route.request.method
        if url.endswith(".js") or "driver-apply.js" in url:
            return route.fulfill(body=js, content_type="application/javascript")
        if url.endswith(".css") or "driver-onboarding.css" in url:
            return route.fulfill(body=css, content_type="text/css")
        if "/api/platform-ops/driver-onboarding/applications" in url:
            if method == "POST" and url.rstrip("/").endswith("/applications"):
                posts.append(route.request.post_data or "")
                return route.fulfill(
                    json={
                        "application": payload,
                        "applicant_access_token": "resumed-token",
                        "resumed_existing": True,
                    }
                )
            if method == "PUT":
                return route.fulfill(json=payload)
            return route.fulfill(json=payload)
        if "/platform-ops/driver-apply" in url:
            return route.fulfill(body=html, content_type="text/html")
        return route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.route("**/*", handle_route)
        page.goto("https://amicor.example/platform-ops/driver-apply")
        page.wait_for_selector('input[name="email"]', state="attached")
        page.fill('input[name="email"]', "saye.resume@example.com")
        page.locator("#save-draft").click()
        page.wait_for_function("() => document.querySelector('[name=legal_first_name]').value === 'Saye'")
        page.wait_for_function(
            "() => !document.querySelector('[data-step-panel=\"5\"]').classList.contains('hidden')"
        )
        assert page.locator('[data-step-panel="5"]').is_visible()
        assert page.input_value('input[name="legal_first_name"]') == "Saye"
        assert page.input_value('input[name="vehicle_make"]') == "Dodge"
        assert page.locator("#existing-documents li").count() == 5
        assert "pending review" in (page.locator("#existing-documents").inner_text() or "").lower()
        page.evaluate("document.getElementById('application-form').reset()")
        page.wait_for_function("() => document.querySelector('[name=legal_first_name]').value === 'Saye'")
        assert page.input_value('input[name="legal_first_name"]') == "Saye"
        assert page.input_value('input[name="email"]') == "saye.resume@example.com"
        page.reload()
        page.wait_for_function("() => document.querySelector('[name=legal_first_name]').value === 'Saye'")
        assert page.locator('[data-step-panel="5"]').is_visible()
        assert len(posts) == 1
        browser.close()


def test_driver_001_apply_page_resumes_existing_and_survives_captcha_reset():
    try:
        _browser_driver_001_resume()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or (
            "playwright" in str(exc).lower() and "install" in str(exc).lower()
        ):
            pytest.skip("Playwright browser not installed")
        raise
