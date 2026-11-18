"""Read-only Growth campaign preview: pure contract + authenticated route regressions.

Uses synthetic fixtures and monkeypatched service; no live delivery, providers,
external network, real Studio asset or customer CRM writes.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.nova.growth_agent import router as growth_router
from app.core.nova.growth_agent.campaign_preview import (
    CampaignPreviewDenied, build_campaign_preview,
)
from app.core.nova.growth_agent.tenant import require_growth_owner


def profile(**updates):
    out = {
        "configured": True, "organization_id": "org-A",
        "is_synthetic_demo": True, "activated": False, "agent_disabled": True,
        "contact_email": "private@example.invalid",
    }
    out.update(updates)
    return out


def kwargs(**updates):
    out = dict(
        organization_id="org-A", owner_user_id="owner-1",
        owner_role="admin", session_organization_id="org-A",
        campaign_id="campaign-1", asset_id="asset-1",
        studio_project_id="studio-1", profile=profile(), enabled=True,
    )
    out.update(updates)
    return out


def request_body(**updates):
    out = dict(
        organization_id="org-A", campaign_id="campaign-1",
        asset_id="asset-1", studio_project_id="studio-1",
    )
    out.update(updates)
    return out


def test_pure_preview_is_read_only_and_discloses_no_contacts():
    output = build_campaign_preview(**kwargs())
    assert output["status"] == "preview_only"
    assert output["studio_approval_verified"] is False
    assert output["studio_ownership_verified"] is False
    for field in ("campaign_ingested", "lead_created", "published",
                  "outbound_messages_sent", "billing_triggered"):
        assert output[field] is False
    assert "private@example.invalid" not in str(output)


@pytest.mark.parametrize("updates", [
    dict(organization_id="org-B"), dict(owner_role="staff"),
    dict(owner_role="super_admin_support"), dict(owner_user_id="bad id"),
    dict(asset_id=""), dict(studio_project_id="../secret"),
    dict(profile=profile(configured=False)),
    dict(profile=profile(organization_id="org-B")),
    dict(profile=profile(is_synthetic_demo=False)),
    dict(profile=profile(activated=True)),
    dict(profile=profile(agent_disabled=False)),
    dict(enabled=False),
])
def test_pure_preview_rejects_unsafe_context(updates):
    with pytest.raises(CampaignPreviewDenied):
        build_campaign_preview(**kwargs(**updates))


def test_default_off_and_live_flag(monkeypatch):
    monkeypatch.delenv("NOVA_GROWTH_CAMPAIGN_PREVIEW_ENABLED", raising=False)
    with pytest.raises(CampaignPreviewDenied):
        build_campaign_preview(**kwargs(enabled=None))
    monkeypatch.setenv("NOVA_GROWTH_CAMPAIGN_LIVE_ENABLED", "true")
    with pytest.raises(CampaignPreviewDenied):
        build_campaign_preview(**kwargs(enabled=True))


def test_real_http_route_default_off(monkeypatch):
    monkeypatch.delenv("NOVA_GROWTH_CAMPAIGN_PREVIEW_ENABLED", raising=False)
    app.dependency_overrides[require_growth_owner] = lambda: SimpleNamespace(
        user_id="owner-1", organization_id="org-A", role="admin",
    )
    try:
        client = TestClient(app)
        response = client.post(
            "/api/nova/growth-agent/campaign-assets/preview",
            json=request_body(),
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_http_auth_and_tenant_gates_with_no_crm_writes(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_CAMPAIGN_PREVIEW_ENABLED", "true")
    monkeypatch.delenv("NOVA_GROWTH_CAMPAIGN_LIVE_ENABLED", raising=False)

    class ReadOnlyGrowth:
        def __init__(self):
            self.reads = []
        def get_profile(self, organization_id):
            self.reads.append(organization_id)
            return profile()

    svc = ReadOnlyGrowth()
    app.dependency_overrides[require_growth_owner] = lambda: SimpleNamespace(
        user_id="owner-1", organization_id="org-A", role="admin",
    )
    app.dependency_overrides[growth_router._svc] = lambda: svc
    try:
        client = TestClient(app)
        good = client.post(
            "/api/nova/growth-agent/campaign-assets/preview",
            json=request_body(),
        )
        denied_tenant = client.post(
            "/api/nova/growth-agent/campaign-assets/preview",
            json=request_body(organization_id="org-B"),
        )
        denied_extras = client.post(
            "/api/nova/growth-agent/campaign-assets/preview",
            json={**request_body(), "customer_email": "private@example.invalid"},
        )
        assert good.status_code == 200, good.text
        assert good.headers["cache-control"] == "private, no-store"
        assert good.json()["lead_created"] is False
        assert good.json()["studio_approval_verified"] is False
        assert denied_tenant.status_code == 403
        assert denied_extras.status_code == 422
        assert svc.reads == ["org-A"]
    finally:
        app.dependency_overrides.clear()


def test_http_nonadmin_denied_before_profile_lookup(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_CAMPAIGN_PREVIEW_ENABLED", "true")

    class NeverReadProfile:
        def get_profile(self, organization_id):
            raise AssertionError("profile should not be read for non-admin")

    app.dependency_overrides[require_growth_owner] = lambda: SimpleNamespace(
        user_id="staff-1", organization_id="org-A", role="staff",
    )
    app.dependency_overrides[growth_router._svc] = lambda: NeverReadProfile()
    try:
        client = TestClient(app)
        denied = client.post(
            "/api/nova/growth-agent/campaign-assets/preview",
            json=request_body(),
        )
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.clear()
