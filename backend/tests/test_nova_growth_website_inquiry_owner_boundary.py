"""No-network tests for exact-owner website inquiry tenant boundary."""
import json

import pytest

from app.auth import ROLE_ADMIN, ROLE_DISPATCHER, ROLE_SUPER_ADMIN_SUPPORT, UserContext
from app.core.nova.growth_agent import website_inquiry_owner_boundary as boundary

KEY = "lead:AMQ-AB12CD34"
RECORD = {
    "receivedAt": "2026-11-14T21:00:00Z",
    "name": "Synthetic QA",
    "company": "Fictional Company",
    "email": "qa@example.invalid",
    "message": "INTERNAL TEST ONLY",
    "consent": True,
}


def user(*, role=ROLE_ADMIN, org="amicor-test", identity="owner-test"):
    return UserContext(
        user_id=identity,
        email="synthetic@example.invalid",
        role=role,
        organization_id=org,
    )


class Fixture:
    def __init__(self):
        self.reads = 0

    def list_keys(self, *, prefix, cursor):
        self.reads += 1
        assert prefix == "lead:"
        assert cursor is None
        return {"list_complete": True, "keys": [{"name": KEY}]}

    def get_text(self, key):
        assert key == KEY
        return json.dumps(RECORD)


def test_owner_can_read_only_own_tenant_synthetic_fixture(monkeypatch):
    monkeypatch.setattr(boundary, "growth_agent_enabled", lambda: True)
    fixture = Fixture()
    selected = []
    def factory(organization_id):
        selected.append(organization_id)
        return fixture
    result = boundary.read_owner_website_inquiries(
        user(), "amicor-test", factory, trusted_synthetic_fixture=True
    )
    assert selected == ["amicor-test"]
    assert result["count"] == 1
    assert result["organization_id"] == "amicor-test"
    assert result["read_only"] is True
    assert result["inquiries"][0]["is_synthetic"] is True
    assert fixture.reads == 1


@pytest.mark.parametrize("principal,requested_org", [
    (None, None),
    (user(role=ROLE_DISPATCHER), None),
    (user(role=ROLE_SUPER_ADMIN_SUPPORT), None),
    (user(org="global"), None),
    (user(org=None), None),
    (user(identity=""), None),
    (user(), "another-tenant"),
    (user(), ""),
])
def test_access_denied_before_source_factory(monkeypatch, principal, requested_org):
    monkeypatch.setattr(boundary, "growth_agent_enabled", lambda: True)
    selected = []
    def factory(org):
        selected.append(org)
        raise AssertionError("source must not be opened")
    with pytest.raises(boundary.WebsiteInquiryAccessDenied) as denial:
        boundary.read_owner_website_inquiries(principal, requested_org, factory)
    assert str(denial.value) == "website_inquiry_access_denied"
    assert selected == []


def test_disabled_flag_blocks_source_factory(monkeypatch):
    monkeypatch.setattr(boundary, "growth_agent_enabled", lambda: False)
    with pytest.raises(boundary.WebsiteInquiryAccessDenied):
        boundary.read_owner_website_inquiries(
            user(), None, lambda _: (_ for _ in ()).throw(AssertionError("must not open"))
        )


def test_owner_has_no_implicit_synthetic_classification(monkeypatch):
    monkeypatch.setattr(boundary, "growth_agent_enabled", lambda: True)
    result = boundary.read_owner_website_inquiries(user(), None, lambda _: Fixture())
    assert result["inquiries"][0]["is_synthetic"] is False
