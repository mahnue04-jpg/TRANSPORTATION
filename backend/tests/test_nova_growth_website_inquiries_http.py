"""Synthetic HTTP acceptance tests for the owner-only website inbox."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth import UserContext
from app.core.nova.growth_agent import website_inquiries as module
from app.core.nova.growth_agent.tenant import require_growth_owner


def _user():
    return UserContext(
        user_id="synthetic-owner", email="owner@example.invalid",
        role="admin", organization_id="synthetic-org",
    )


@pytest.fixture
def client(monkeypatch):
    # Existing real auth dependency remains on the router. Tests override
    # it only in this synthetic in-memory FastAPI application.
    app = FastAPI()
    from app.core.nova.growth_agent.router import router
    app.include_router(router)
    app.dependency_overrides[require_growth_owner] = _user
    monkeypatch.setattr(module, "resolve_org", lambda user, requested=None: "synthetic-org")
    with TestClient(app) as c:
        yield app, c


def test_without_source_returns_unavailable(client):
    app, c = client
    r = c.get("/api/nova/growth-agent/website-inquiries")
    assert r.status_code == 200
    assert r.json() == {
        "state": "unavailable", "source_system": "cloudflare_amicor_leads",
        "inquiries": [], "complete": False,
    }


def test_valid_source_projects_only_allowlisted_fields(client):
    app, c = client
    class Source:
        def read(self, org):
            assert org == "synthetic-org"
            return {"state": "available", "complete": True, "inquiries": [
                {"source_system": "cloudflare_amicor_leads",
                 "source_key": "lead:AMQ-TEST", "received_at": "2026-11-14T12:00:00Z",
                 "name": "Sample", "email": "sample@example.invalid", "consent": True,
                 "is_synthetic": True, "private_token": "MUST_NOT_LEAK"}]}
    app.dependency_overrides[module.get_website_inquiry_source] = Source
    r = c.get("/api/nova/growth-agent/website-inquiries")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "available"
    assert len(data["inquiries"]) == 1
    assert data["inquiries"][0]["is_synthetic"] is True
    assert "private_token" not in r.text


def test_broken_source_fails_closed(client):
    app, c = client
    class Broken:
        def read(self, org):
            raise ValueError("secret-example")
    app.dependency_overrides[module.get_website_inquiry_source] = Broken
    r = c.get("/api/nova/growth-agent/website-inquiries")
    assert r.status_code == 200
    assert r.json()["state"] == "unavailable"
    assert "secret-example" not in r.text


def test_anonymous_denied_by_actual_dependency():
    app = FastAPI()
    from app.core.nova.growth_agent.router import router
    app.include_router(router)
    with TestClient(app) as c:
        r = c.get("/api/nova/growth-agent/website-inquiries")
    assert r.status_code in {401, 403, 404}
