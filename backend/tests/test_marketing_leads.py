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
