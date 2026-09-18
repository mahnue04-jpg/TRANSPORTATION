"""Block 1 owner-fact intake: validation, isolation, readiness, and no external action."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.owner_facts import (
    OwnerFactError,
    fact_catalog,
    fact_readiness,
    validate_fact_value,
)
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import engine
from app.main import app
from tests.test_nova_work_revenue import WORK_HTML, WORK_JS


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)['access_token']}"}


def _put(client: TestClient, headers: dict[str, str], key: str, **payload):
    return client.put(f"/api/nova/work/owner-facts/{key}", headers=headers, json=payload)


def test_owner_fact_ui_is_internal_only() -> None:
    assert 'data-tab="owner-facts"' in WORK_HTML
    assert "Do not enter EIN" in WORK_HTML
    assert "Saving a fact does not approve" in WORK_HTML
    assert "/api/nova/work/owner-facts" in WORK_JS
    assert "live apply" not in WORK_JS.lower()
    assert "Submit Application" not in WORK_JS


def test_create_update_verify_expire_and_not_applicable(client: TestClient) -> None:
    headers = _headers(client)
    created = _put(
        client,
        headers,
        "legal_business_name",
        value_status="PROVIDED",
        value_display="AMICOR Owner Entered Legal Name",
        notes="typed by owner",
    )
    assert created.status_code == 200, created.text
    row = next(item for item in created.json()["facts"] if item["fact_id"] == "legal_business_name")
    assert row["value_status"] == "PROVIDED"
    assert row["source"] == "OWNER"
    assert row["value_display"] == "AMICOR Owner Entered Legal Name"
    updated = _put(
        client,
        headers,
        "legal_business_name",
        value_status="PROVIDED",
        value_display="AMICOR Updated Legal Name",
    )
    assert updated.status_code == 200
    verified = _put(
        client,
        headers,
        "legal_business_name",
        value_status="VERIFIED",
        value_display="AMICOR Updated Legal Name",
    )
    assert verified.status_code == 200
    verified_row = next(item for item in verified.json()["facts"] if item["fact_id"] == "legal_business_name")
    assert verified_row["value_status"] == "VERIFIED"
    assert verified_row["verified_at"]
    silent = _put(
        client,
        headers,
        "legal_business_name",
        value_status="PROVIDED",
        value_display="Should Not Overwrite",
    )
    assert silent.status_code == 409
    overwrite = _put(
        client,
        headers,
        "legal_business_name",
        value_status="PROVIDED",
        value_display="AMICOR Overwritten After Confirm",
        confirm_overwrite=True,
    )
    assert overwrite.status_code == 200
    expired = _put(
        client,
        headers,
        "insurance",
        value_status="EXPIRED",
        value_display="OWNER_SAYS_READY",
        expiration_date=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    assert expired.status_code == 200
    expired_row = next(item for item in expired.json()["facts"] if item["fact_id"] == "insurance")
    assert expired_row["value_status"] == "EXPIRED"
    missing = _put(client, headers, "legal_business_name", value_status="MISSING", confirm_overwrite=True)
    assert missing.status_code == 200
    missing_row = next(item for item in missing.json()["facts"] if item["fact_id"] == "legal_business_name")
    assert missing_row["value_status"] == "MISSING"
    na = _put(client, headers, "dba", value_status="NOT_APPLICABLE", value_display="NOT_APPLICABLE")
    assert na.status_code == 200
    na_row = next(item for item in na.json()["facts"] if item["fact_id"] == "dba")
    assert na_row["value_status"] == "NOT_APPLICABLE"
    forbidden_na = _put(client, headers, "legal_business_name", value_status="NOT_APPLICABLE")
    assert forbidden_na.status_code == 400


def test_email_phone_decisions_and_readiness_percentage(client: TestClient) -> None:
    headers = _headers(client, "staff@amicor.local")
    catalog = client.get("/api/nova/work/owner-facts", headers=headers)
    assert catalog.status_code == 200
    ready = catalog.json()["readiness"]
    assert ready["externally_ready"] is False
    assert ready["percentage_complete"] == 0
    assert ready["missing_facts"] == ready["total_required_facts"]
    assert _put(client, headers, "business_email", value_status="PROVIDED", value_display="not-an-email").status_code == 400
    assert _put(client, headers, "business_phone", value_status="PROVIDED", value_display="abc").status_code == 400
    email = _put(client, headers, "business_email", value_status="PROVIDED", value_display="owner@example.invalid")
    phone = _put(client, headers, "business_phone", value_status="PROVIDED", value_display="+1 555 123 4567")
    ai = _put(
        client,
        headers,
        "ai_use_disclosure_decision",
        value_status="PROVIDED",
        value_display="AI_ASSISTANCE_USED_OWNER_WILL_DECIDE_PER_PLATFORM",
    )
    sub = _put(
        client,
        headers,
        "subcontractor_disclosure_decision",
        value_status="PROVIDED",
        value_display="SUBCONTRACTOR_ASSISTANCE_NOT_ALLOWED",
    )
    w9 = _put(client, headers, "w9_readiness", value_status="PROVIDED", value_display="w9_ready")
    assert email.status_code == 200, email.text
    assert phone.status_code == 200, phone.text
    assert ai.status_code == 200, ai.text
    assert sub.status_code == 200, sub.text
    assert w9.status_code == 200, w9.text
    after = w9.json()["readiness"]
    assert after["provided_facts"] == 5
    assert after["percentage_complete"] > 0
    assert after["externally_ready"] is False
    assert after["live_discovery_enabled"] is False
    assert after["external_submission_enabled"] is False
    assert after["financial_actions_enabled"] is False


def test_secret_and_injection_rejection() -> None:
    with pytest.raises(OwnerFactError):
        validate_fact_value("legal_business_name", value_status="PROVIDED", value_display="12-3456789")
    with pytest.raises(OwnerFactError):
        validate_fact_value("legal_business_name", value_status="PROVIDED", value_display="123-45-6789")
    with pytest.raises(OwnerFactError):
        validate_fact_value("address", value_status="PROVIDED", value_display="routing number 021000021")
    with pytest.raises(OwnerFactError):
        validate_fact_value("ownership", value_status="PROVIDED", value_display="account number 000123456789")
    with pytest.raises(OwnerFactError):
        validate_fact_value("pricing", value_status="PROVIDED", value_display="sk_test_51secretvalue")
    with pytest.raises(OwnerFactError):
        validate_fact_value("rates", value_status="PROVIDED", value_display="whsec_abc123456")
    with pytest.raises(OwnerFactError):
        validate_fact_value("workforce", value_status="PROVIDED", value_display="api_key=abcd1234")
    with pytest.raises(OwnerFactError):
        validate_fact_value("equipment", value_status="PROVIDED", value_display="<script>alert(1)</script>")
    with pytest.raises(OwnerFactError):
        validate_fact_value("references", value_status="PROVIDED", value_display="javascript:alert(1)")
    with pytest.raises(OwnerFactError):
        validate_fact_value("banking_payment_readiness", value_status="PROVIDED", value_display="111000025")
    ok = validate_fact_value("legal_business_name", value_status="PROVIDED", value_display="AMICOR Example LLC")
    assert ok == "AMICOR Example LLC"


def test_http_secret_rejection_and_duplicate_key_updates(client: TestClient) -> None:
    headers = _headers(client)
    assert _put(client, headers, "legal_business_name", value_status="PROVIDED", value_display="EIN 98-7654321").status_code == 400
    assert _put(client, headers, "authorized_signer", value_status="PROVIDED", value_display="ssn 123-45-6789").status_code == 400
    assert _put(client, headers, "ownership", value_status="PROVIDED", value_display="routing number 111000025").status_code == 400
    assert _put(client, headers, "pricing", value_status="PROVIDED", value_display="sk_live_secret").status_code == 400
    first = _put(client, headers, "industries_served", value_status="PROVIDED", value_display="Transportation support")
    second = _put(client, headers, "industries_served", value_status="PROVIDED", value_display="Transportation and operations")
    assert first.status_code == 200
    assert second.status_code == 200
    rows = [item for item in second.json()["facts"] if item["fact_id"] == "industries_served"]
    assert len(rows) == 1
    assert rows[0]["value_display"] == "Transportation and operations"


def test_tenant_isolation_and_no_external_side_effects(client: TestClient) -> None:
    owner = _headers(client)
    other = _headers(client, "staff@amicor.local")
    saved = _put(
        client,
        owner,
        "service_areas",
        value_status="PROVIDED",
        value_display="Owner-only service area text",
    )
    assert saved.status_code == 200
    other_catalog = client.get("/api/nova/work/owner-facts", headers=other).json()
    other_row = next(item for item in other_catalog["facts"] if item["fact_id"] == "service_areas")
    assert other_row["value_status"] == "MISSING"
    assert other_row["value_display"] != "Owner-only service area text"
    owner_catalog = client.get("/api/nova/work/owner-facts", headers=owner).json()
    assert owner_catalog["externally_ready"] is False
    assert owner_catalog["guardrails"]["FACT_ENTRY_EQUALS_SUBMIT"] is False
    assert owner_catalog["executes_externally"] is False if "executes_externally" in owner_catalog else True
    dash = client.get("/api/nova/work/dashboard", headers=owner)
    assert dash.status_code == 200
    assert dash.json()["guardrails"]["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert dash.json()["guardrails"]["LIVE_DISCOVERY_ENABLED"] is False
    assert dash.json()["guardrails"]["FINANCIAL_ACTIONS_ENABLED"] is False
    apps = client.get("/api/nova/work/applications", headers=owner)
    assert apps.status_code == 200
    for item in apps.json():
        assert item.get("externally_ready") is False
        assert item.get("approved_equals_submitted") is False
    guards = engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert guards["AUTONOMOUS_CLIENT_CONTACT_ENABLED"] is False


def test_catalog_readiness_does_not_enable_live_paths() -> None:
    catalog = fact_catalog()
    ids = {item["fact_id"] for item in catalog["facts"]}
    assert "business_email" in ids
    assert "authorized_signer" in ids
    ready = fact_readiness(catalog["facts"])
    assert ready["externally_ready"] is False
    assert ready["percentage_complete"] == 0
    assert "sk_live" not in str(catalog).lower()
