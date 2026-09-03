"""Resume/hydration tests for the existing-application driver apply portal.

Uses synthetic applications only. Does not touch production Driver 001 data.
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
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
    ensure_platform_ops_schema,
)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "platform-ops"
APPLY_HTML = STATIC_DIR / "driver-apply.html"
APPLY_JS = STATIC_DIR / "driver-apply.js"


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


def _draft_payload(org_id: str, *, email: str | None = None) -> dict:
    today = date.today()
    return {
        "organization_id": org_id,
        "legal_first_name": "Pat",
        "legal_middle_name": "Q",
        "legal_last_name": "Resume",
        "date_of_birth": "1988-06-01",
        "email": email or f"resume-{uuid4().hex[:8]}@example.com",
        "mobile_phone": "612-555-2211",
        "home_address": "200 Lake St",
        "city": "Minneapolis",
        "state": "MN",
        "zip_code": "55408",
        "emergency_contact_name": "Alex Contact",
        "emergency_contact_phone": "612-555-0199",
        "drivers_license_number": "MN-RESUME-441",
        "license_issuing_state": "MN",
        "license_expiration_date": (today + timedelta(days=400)).isoformat(),
        "vehicle_year": 2021,
        "vehicle_make": "Dodge",
        "vehicle_model": "Ram 1500",
        "vehicle_license_plate": "TST441",
        "vehicle_vin": "1C6SRFFT0MN000441",
        "declaration_mvr_authorization": True,
        "declaration_valid_license": True,
        "authorize_qualification_checks": True,
        "electronic_signature": "Pat Q Resume",
        "signed_date": today.isoformat(),
    }


def _create_resume_draft(client: TestClient) -> tuple[str, str, dict]:
    org_id = _org_id()
    payload = _draft_payload(org_id)
    created = client.post("/api/platform-ops/driver-onboarding/applications", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    app_id = body["application"]["id"]
    token = body["applicant_access_token"]
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
    return app_id, token, payload


def test_resume_get_returns_populated_fields_and_document_metadata(client: TestClient):
    app_id, token, payload = _create_resume_draft(client)
    loaded = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
    )
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["id"] == app_id
    assert body["status"] == "draft"
    assert body["legal_first_name"] == payload["legal_first_name"]
    assert body["legal_last_name"] == payload["legal_last_name"]
    assert body["email"] == payload["email"]
    assert body["mobile_phone"] == payload["mobile_phone"]
    assert body["date_of_birth"] == payload["date_of_birth"]
    assert body["emergency_contact_name"] == payload["emergency_contact_name"]
    assert body["drivers_license_number_masked"] == payload["drivers_license_number"]
    assert body["license_issuing_state"] == "MN"
    assert body["vehicle_make"] == payload["vehicle_make"]
    assert body["vehicle_model"] == payload["vehicle_model"]
    assert body["electronic_signature"] == payload["electronic_signature"]
    assert body["declaration_mvr_authorization"] is True
    categories = {doc["category"] for doc in body["documents"]}
    assert {
        "drivers_license_front",
        "drivers_license_back",
        "vehicle_registration",
        "proof_of_auto_insurance",
    }.issubset(categories)


def test_empty_save_draft_does_not_erase_existing_values(client: TestClient):
    app_id, token, payload = _create_resume_draft(client)
    org_id = payload["organization_id"]
    emptied = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
        json={
            "organization_id": org_id,
            "legal_first_name": "",
            "legal_last_name": "",
            "email": "",
            "mobile_phone": "",
            "home_address": "",
            "city": "",
            "drivers_license_number": "",
            "vehicle_make": "",
            "electronic_signature": "",
            "declaration_mvr_authorization": False,
            "declaration_valid_license": False,
        },
    )
    assert emptied.status_code == 200, emptied.text
    body = emptied.json()
    assert body["id"] == app_id
    assert body["legal_first_name"] == payload["legal_first_name"]
    assert body["legal_last_name"] == payload["legal_last_name"]
    assert body["email"] == payload["email"]
    assert body["mobile_phone"] == payload["mobile_phone"]
    assert body["drivers_license_number_masked"] == payload["drivers_license_number"]
    assert body["vehicle_make"] == payload["vehicle_make"]
    assert body["electronic_signature"] == payload["electronic_signature"]
    assert body["declaration_mvr_authorization"] is True
    assert body["declaration_valid_license"] is True


def test_save_draft_updates_same_application_id(client: TestClient):
    app_id, token, payload = _create_resume_draft(client)
    saved = client.put(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
        json={"organization_id": payload["organization_id"], "vehicle_color": "Silver"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["id"] == app_id
    assert saved.json()["vehicle_color"] == "Silver"
    assert saved.json()["legal_first_name"] == payload["legal_first_name"]
    with SessionLocal() as db:
        rows = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.email == payload["email"])
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == app_id
        assert rows[0].vehicle_color == "Silver"


def test_reopen_get_preserves_populated_values(client: TestClient):
    app_id, token, payload = _create_resume_draft(client)
    first = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
    ).json()
    second = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
    ).json()
    assert first["id"] == second["id"] == app_id
    assert first["legal_first_name"] == second["legal_first_name"] == payload["legal_first_name"]
    assert first["vehicle_make"] == second["vehicle_make"]
    assert {doc["category"] for doc in first["documents"]} == {doc["category"] for doc in second["documents"]}


def test_resume_html_js_contract_maps_saved_fields_and_documents():
    html = APPLY_HTML.read_text(encoding="utf-8")
    js = APPLY_JS.read_text(encoding="utf-8")
    css = (STATIC_DIR / "driver-onboarding.css").read_text(encoding="utf-8")
    for name in (
        "legal_first_name",
        "legal_last_name",
        "email",
        "mobile_phone",
        "home_address",
        "date_of_birth",
        "emergency_contact_name",
        "drivers_license_number",
        "license_issuing_state",
        "vehicle_make",
        "vehicle_model",
        "electronic_signature",
        "signed_date",
        "authorize_qualification_checks",
    ):
        assert f'name="{name}"' in html
    assert "file_license_front" in html
    assert "file_license_back" in html
    assert "file_registration" in html
    assert "file_insurance" in html
    assert "unwrapApplication" in js
    assert "normalizeDateValue" in js
    assert "withPanelsVisible" in js
    assert "Already on file" in js
    assert "existingApplicationLoaded && (value == null" in js
    assert "existingApplicationLoaded) showStep(target)" in js
    assert "pageshow" in js
    assert "computeApplicantResumeProgress" in js
    assert "applyResumePosition" in js
    assert "-webkit-text-fill-color" in css
    assert "driver-apply.js?v=20260902.1" in html


def _browser_resume(viewport: dict[str, int]) -> None:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    html = APPLY_HTML.read_text(encoding="utf-8")
    js = APPLY_JS.read_text(encoding="utf-8")
    css = (STATIC_DIR / "driver-onboarding.css").read_text(encoding="utf-8")
    payload = {
        "id": "app-resume-001",
        "organization_id": "org-resume-001",
        "status": "draft",
        "legal_first_name": "Pat",
        "legal_last_name": "Resume",
        "email": "pat.resume@example.com",
        "mobile_phone": "612-555-2211",
        "home_address": "200 Lake St",
        "city": "Minneapolis",
        "state": "MN",
        "zip_code": "55408",
        "date_of_birth": "1988-06-01T00:00:00",
        "emergency_contact_name": "Alex Contact",
        "emergency_contact_phone": "612-555-0199",
        "drivers_license_number_masked": "MN-RESUME-441",
        "license_issuing_state": "MN",
        "license_expiration_date": "2027-10-05",
        "vehicle_year": 2021,
        "vehicle_make": "Dodge",
        "vehicle_model": "Ram 1500",
        "vehicle_license_plate": "TST441",
        "declaration_mvr_authorization": True,
        "declaration_valid_license": True,
        "declaration_background_authorization": True,
        "electronic_signature": "Pat Q Resume",
        "signed_date": "2026-08-17",
        "documents": [
            {"id": "doc-front", "category": "drivers_license_front", "review_status": "pending", "original_filename": "front.jpg"},
            {"id": "doc-back", "category": "drivers_license_back", "review_status": "pending", "original_filename": "back.jpg"},
            {"id": "doc-reg", "category": "vehicle_registration", "review_status": "pending", "original_filename": "reg.jpg"},
            {"id": "doc-ins", "category": "proof_of_auto_insurance", "review_status": "pending", "original_filename": "ins.pdf"},
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
                posts.append(url)
                return route.fulfill(status=500, body="should-not-create")
            if method == "PUT":
                return route.fulfill(json=payload)
            return route.fulfill(json=payload)
        if "/platform-ops/driver-apply" in url:
            return route.fulfill(body=html, content_type="text/html")
        return route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=viewport)
        page.route("**/*", handle_route)
        page.goto(
            "https://amicor.example/platform-ops/driver-apply"
            "?organization_id=org-resume-001&application_id=app-resume-001&token=synthetic-token"
        )
        page.wait_for_selector('input[name="legal_first_name"]', state="attached")
        page.wait_for_function(
            "() => document.querySelector('[name=legal_first_name]').value === 'Pat'"
        )
        page.wait_for_function(
            "() => !document.querySelector('[data-step-panel=\"5\"]').classList.contains('hidden')"
        )
        assert page.locator('[data-step-panel="5"]').is_visible()
        assert page.locator('[data-step-panel="1"]').is_hidden()
        assert page.input_value('input[name="legal_first_name"]') == "Pat"
        assert page.input_value('input[name="legal_last_name"]') == "Resume"
        assert page.input_value('input[name="email"]') == "pat.resume@example.com"
        assert page.input_value('input[name="date_of_birth"]') == "1988-06-01"
        page.locator('[data-step="2"]').click()
        assert page.input_value('input[name="drivers_license_number"]') == "MN-RESUME-441"
        assert page.locator(".on-file-hint").count() >= 2
        page.locator('[data-step="3"]').click()
        assert page.input_value('input[name="vehicle_make"]') == "Dodge"
        assert page.input_value('input[name="vehicle_model"]') == "Ram 1500"
        page.locator("#save-draft").click()
        page.wait_for_selector("#banner.ok")
        assert "updated, not replaced" in (page.locator("#banner").inner_text() or "").lower()
        page.reload()
        page.wait_for_function(
            "() => document.querySelector('[name=legal_first_name]').value === 'Pat'"
        )
        page.wait_for_function(
            "() => !document.querySelector('[data-step-panel=\"5\"]').classList.contains('hidden')"
        )
        assert page.locator('[data-step-panel="5"]').is_visible()
        assert page.input_value('input[name="legal_first_name"]') == "Pat"
        assert posts == []
        browser.close()


def test_apply_page_repopulates_on_mobile_viewport():
    try:
        _browser_resume({"width": 390, "height": 844})
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or (
            "playwright" in str(exc).lower() and "install" in str(exc).lower()
        ):
            pytest.skip("Playwright browser not installed")
        raise


def test_resume_get_lands_on_first_incomplete_section(client: TestClient):
    from app.modules.platform_ops.onboarding.service import compute_applicant_resume_progress
    from app.modules.platform_ops.models import PlatformDriverOnboardingDocument

    app_id, token, payload = _create_resume_draft(client)
    loaded = client.get(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}",
        headers={"X-Applicant-Token": token},
    )
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["resume_step"] == 5
    assert body["resume_section_key"] == "work_setup"
    complete = {item["key"]: item["complete"] for item in body["section_completion"]}
    assert complete["about_you"] is True
    assert complete["driving"] is True
    assert complete["vehicle"] is True
    assert complete["authorization"] is True
    assert complete["work_setup"] is False

    empty = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": payload["organization_id"], "legal_first_name": "Only"},
    )
    assert empty.status_code == 200, empty.text
    empty_detail = empty.json()["application"]
    assert empty_detail["resume_step"] == 1
    assert empty_detail["resume_section_key"] == "about_you"

    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_id).one()
        docs = (
            db.query(PlatformDriverOnboardingDocument)
            .filter(PlatformDriverOnboardingDocument.application_id == app_id)
            .all()
        )
        progress = compute_applicant_resume_progress(row, docs)
        assert progress["resume_step"] == 5
        assert progress["resume_section_key"] == "work_setup"


def test_apply_page_repopulates_on_desktop_viewport():
    try:
        _browser_resume({"width": 1280, "height": 720})
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or (
            "playwright" in str(exc).lower() and "install" in str(exc).lower()
        ):
            pytest.skip("Playwright browser not installed")
        raise
