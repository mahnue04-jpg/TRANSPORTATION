"""End-to-end synthetic website KV -> authenticated Growth owner HTTP route.

No live Cloudflare token, network, production database, or outbound messaging.
"""
from __future__ import annotations

from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext
from app.core.nova.growth_agent import website_inquiries
from app.core.nova.growth_agent.tenant import require_growth_owner
from app.core.nova.growth_agent.website_kv_source import WebsiteKVSource


def _owner():
    return UserContext(user_id="test-owner", email="owner@example.invalid",
                       role="admin", organization_id="synthetic-org")


def test_website_inquiry_from_fake_cloudflare_kv_to_owner_http(monkeypatch):
    from app.core.nova.growth_agent.router import router

    key = "lead:AMQ-TEST-1234"
    record = {
        "receivedAt": "2026-11-15T08:00:00Z",
        "referenceId": "AMQ-TEST-1234",
        "name": "Synthetic Business Owner",
        "company": "Fixture Company",
        "email": "synthetic@example.invalid",
        "product": "Nova Operations Agent",
        "message": "Please prepare a synthetic CSV report.",
        "consent": True,
        "is_synthetic": True,
        "secret_webhook_token": "must-not-expose",
    }
    calls = []

    def fake_cloudflare_api(path):
        calls.append(path)
        if path.startswith("keys?"):
            return {"success": True, "result": [{"name": key}, {"name": key}],
                    "result_info": {}}
        if path.startswith("values/") and unquote(path[7:]) == key:
            return record
        raise AssertionError("unexpected Cloudflare path")

    source = WebsiteKVSource(
        tenant_id="synthetic-org", account_id="account1234",
        namespace_id="namespace1234", token="synthetic-only",
        request_json=fake_cloudflare_api,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_growth_owner] = _owner
    app.dependency_overrides[website_inquiries.get_website_inquiry_source] = lambda: source
    monkeypatch.setattr(website_inquiries, "resolve_org",
                        lambda user, requested=None: "synthetic-org")
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    monkeypatch.setenv("NOVA_GROWTH_AGENT_DEMO_MODE", "true")
    monkeypatch.setenv("NOVA_GROWTH_SYNTHETIC_INQUIRY_HANDOFF", "true")
    with TestClient(app) as client:
        response = client.get("/api/nova/growth-agent/website-inquiries")
        repeated = client.get("/api/nova/growth-agent/website-inquiries")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "available"
    assert body["complete"] is True
    assert len(body["inquiries"]) == 1
    lead = body["inquiries"][0]
    assert lead["source_key"] == key
    assert lead["reference_id"] == "AMQ-TEST-1234"
    assert lead["name"] == "Synthetic Business Owner"
    assert lead["product"] == "Nova Operations Agent"
    assert lead["is_synthetic"] is True
    assert lead["consent"] is True
    assert "must-not-expose" not in response.text
    assert repeated.json()["inquiries"] == body["inquiries"]
    assert len([x for x in calls if x.startswith("values/")]) == 2

    handoff = "/api/nova/growth-agent/website-inquiries/handoff"
    with TestClient(app) as client:
        payload = {"source_key": lead["source_key"]}
        first = client.post(handoff, json=payload)
        assert first.status_code == 200, first.text
        conversation = first.json()
        assert conversation["handler"] == "human"
        assert conversation["status"] == "handed_off"
        assert conversation["is_synthetic_demo"] is True
        assert lead["source_key"] in conversation["messages"][0]["content"]
        assert len(conversation["messages"]) == 2
        assert client.post(handoff, json=payload).json() == conversation
        record["consent"] = False
        assert client.post(handoff, json=payload).status_code == 409
        record.update(consent=True, is_synthetic=False)
        assert client.post(handoff, json=payload).status_code == 409
        monkeypatch.delenv("NOVA_GROWTH_SYNTHETIC_INQUIRY_HANDOFF")
        assert client.post(handoff, json=payload).status_code == 404



def test_inquiry_api_without_adapter_is_unavailable_not_zero(monkeypatch):
    from app.core.nova.growth_agent.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_growth_owner] = _owner
    app.dependency_overrides[website_inquiries.get_website_inquiry_source] = lambda: None
    monkeypatch.setattr(website_inquiries, "resolve_org",
                        lambda user, requested=None: "synthetic-org")
    with TestClient(app) as client:
        response = client.get("/api/nova/growth-agent/website-inquiries")
    assert response.status_code == 200
    assert response.json() == {
        "state": "unavailable",
        "source_system": "cloudflare_amicor_leads",
        "inquiries": [],
        "complete": False,
    }
