"""Isolated marketing lead API tests (no ride-engine coupling)."""
from __future__ import annotations

import os

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _provider_payload(**overrides):
    data = {
        "lead_type": "provider_interest",
        "organization_name": "Phase3 Test Clinic",
        "contact_name": "Phase Three",
        "work_email": "phase3.provider@example.com",
        "phone": "612-555-0144",
        "organization_type": "clinic",
        "estimated_monthly_rides": "1-25",
        "service_area": "Hennepin County, Minnesota",
        "transportation_needs": "[TEST LEAD] Provider consultation — safe to delete.",
        "preferred_contact_method": "email",
        "consent": True,
        "source_path": "/for-providers",
        "lead_source": "website_test",
        "website": "",
    }
    data.update(overrides)
    return data


def test_provider_lead_saves_without_email_config():
    # Ensure notification env is not required for success.
    for key in (
        "MARKETING_SMTP_HOST",
        "MARKETING_SMTP_USER",
        "MARKETING_SMTP_PASSWORD",
        "MARKETING_SMTP_FROM",
        "MARKETING_LEAD_NOTIFY_TO",
    ):
        os.environ.pop(key, None)

    response = client.post("/api/marketing/leads", json=_provider_payload())
    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is True
    data = body.get("data") or {}
    assert data.get("accepted") is True
    assert data.get("lead_id")
    assert data.get("status") == "new"
    assert data.get("email_notification", {}).get("sent") is False
    assert data.get("email_notification", {}).get("reason") in {"not_configured", "duplicate"}


def test_contact_lead_requires_consent_and_message():
    bad = client.post(
        "/api/marketing/leads",
        json={
            "lead_type": "contact",
            "contact_name": "No Consent",
            "work_email": "noconsent.phase3@example.com",
            "message": "[TEST LEAD] missing consent",
            "consent": False,
            "website": "",
        },
    )
    assert bad.status_code == 422

    good = client.post(
        "/api/marketing/leads",
        json={
            "lead_type": "contact",
            "contact_name": "Phase3 Contact",
            "work_email": "phase3.contact@example.com",
            "subject": "transport",
            "message": "[TEST LEAD] General transportation inquiry — safe to delete.",
            "consent": True,
            "source_path": "/contact",
            "lead_source": "website_test",
            "website": "",
        },
    )
    assert good.status_code == 200
    assert good.json().get("ok") is True


def test_honeypot_filtered():
    response = client.post(
        "/api/marketing/leads",
        json={
            "lead_type": "contact",
            "contact_name": "Bot",
            "work_email": "bot.phase3@example.com",
            "message": "spam",
            "consent": True,
            "website": "http://spam.example",
        },
    )
    assert response.status_code == 200
    data = response.json().get("data") or {}
    assert data.get("spam_filtered") is True
    assert data.get("lead_id") is None


def test_marketing_pages_still_serve():
    for path in ("/", "/for-providers", "/for-drivers", "/contact"):
        response = client.get(path)
        assert response.status_code == 200
        assert "AMICOR" in response.text


def test_anonymous_operations_requires_work_description():
    response = client.post("/api/marketing/leads", json={
        "lead_type": "anonymous_operations",
        "contact_name": "Pilot Client",
        "work_email": "pilot-anon@example.com",
        "consent": True,
        "message": ""
    })
    assert response.status_code == 422


def test_anonymous_operations_intake_is_accepted():
    response = client.post("/api/marketing/leads", json={
        "lead_type": "anonymous_operations",
        "organization_name": "Pilot Company",
        "contact_name": "Pilot Client",
        "work_email": "pilot-anon-ok@example.com",
        "consent": True,
        "preferred_contact_method": "email",
        "subject": "Spreadsheet cleanup",
        "message": "Clean and organize a spreadsheet and prepare a summary."
    })
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["accepted"] is True
    assert body["data"]["lead_type"] == "anonymous_operations"


def test_anonymous_operations_internal_inbox_and_status():
    from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users

    ensure_auth_schema()
    seed_default_users()
    submitted = client.post("/api/marketing/leads", json={
        "lead_type": "anonymous_operations",
        "organization_name": "Inbox Test Company",
        "contact_name": "Inbox Test Client",
        "work_email": "anon-inbox@example.com",
        "consent": True,
        "preferred_contact_method": "email",
        "service_plan": "scope_check",
        "subject": "Operations support",
        "message": "Organize business records and prepare an operating summary."
    })
    assert submitted.status_code == 200, submitted.text
    lead_id = submitted.json()["data"]["lead_id"]

    assert client.get("/api/marketing/admin/leads").status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    inbox = client.get(
        "/api/marketing/admin/leads",
        params={"lead_type": "anonymous_operations", "status": "new"},
        headers=headers,
    )
    assert inbox.status_code == 200, inbox.text
    assert any(row["lead_id"] == lead_id for row in inbox.json()["leads"])

    detail = client.get(f"/api/marketing/admin/leads/{lead_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["service_plan"] == "scope_check"
    assert "operating summary" in detail.json()["message"]

    qualified = client.patch(
        f"/api/marketing/admin/leads/{lead_id}/status",
        headers=headers,
        json={"status": "qualified"},
    )
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["status"] == "qualified"

    bad = client.patch(
        f"/api/marketing/admin/leads/{lead_id}/status",
        headers=headers,
        json={"status": "paid"},
    )
    assert bad.status_code == 422
