"""Isolated receptionist synthetic booking contact guard tests (no real DB access)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.service import GrowthAgentService


class FakeQuery:
    def __init__(self, contact=None):
        self.contact = contact
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        if self.contact and self.contact.is_synthetic_demo and self.contact.display_name == self.filters["display_name"]:
            return self.contact
        return None


class FakeDb:
    def __init__(self, database="nova_ga_receptionist_dispos"):
        self.database = database
        self.added = []
        self.commits = 0

    def get_bind(self):
        return SimpleNamespace(url=SimpleNamespace(database=self.database))

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1


def fake_service(monkeypatch, database="nova_ga_receptionist_dispos", existing=None):
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True)
    svc = object.__new__(GrowthAgentService)
    svc.db = FakeDb(database)
    monkeypatch.setattr(svc, "_require_profile", lambda org: SimpleNamespace(organization_id=org))
    query = FakeQuery(existing)
    monkeypatch.setattr(svc, "_org_query", lambda model, org: query)
    audits = []
    monkeypatch.setattr(svc, "audit", lambda *args, **kwargs: audits.append(kwargs))
    return svc, query, audits


def test_rejects_non_receptionist_db_without_writes(monkeypatch):
    svc, _, audits = fake_service(monkeypatch, database="nova_ga_490_dispos")
    with pytest.raises(GrowthAgentError) as caught:
        svc.prepare_staging_booking_contact("org-test", actor_user_id="owner")
    assert caught.value.code == "STAGING_ONLY"
    assert not svc.db.added and not audits and svc.db.commits == 0


def test_rejects_when_demo_mode_disabled_without_writes(monkeypatch):
    svc, _, audits = fake_service(monkeypatch)
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: False)
    with pytest.raises(GrowthAgentError) as caught:
        svc.prepare_staging_booking_contact("org-test", actor_user_id="owner")
    assert caught.value.code == "STAGING_ONLY"
    assert not svc.db.added and not audits and svc.db.commits == 0


def test_creates_synthetic_contact_without_identity_or_delivery(monkeypatch):
    svc, query, audits = fake_service(monkeypatch)
    result = svc.prepare_staging_booking_contact("org-test", actor_user_id="owner")
    assert query.filters == {"display_name": "Nova Booking Test (Synthetic)", "is_synthetic_demo": True}
    assert result["created"] is True and result["is_synthetic_demo"] is True
    assert result["staging_only"] is True and result["live_delivery"] is False
    assert len(svc.db.added) == 1
    contact = svc.db.added[0]
    assert contact.id == result["contact_id"]
    assert contact.organization_id == "org-test"
    assert contact.is_synthetic_demo is True
    assert contact.lead_state == "new"
    assert not contact.dedupe_fingerprint
    assert len(audits) == 1 and svc.db.commits == 1


def test_reuses_existing_synthetic_contact_without_writes(monkeypatch):
    existing = SimpleNamespace(id="synthetic-fixture-id", display_name="Nova Booking Test (Synthetic)", is_synthetic_demo=True)
    svc, _, audits = fake_service(monkeypatch, existing=existing)
    result = svc.prepare_staging_booking_contact("org-test", actor_user_id="owner")
    assert result["created"] is False
    assert result["contact_id"] == existing.id
    assert not svc.db.added and not audits and svc.db.commits == 0


def test_does_not_reclassify_same_named_non_synthetic_lead(monkeypatch):
    legacy = SimpleNamespace(id="existing-real-id", display_name="Nova Booking Test (Synthetic)", is_synthetic_demo=False)
    svc, _, _ = fake_service(monkeypatch, existing=legacy)
    result = svc.prepare_staging_booking_contact("org-test", actor_user_id="owner")
    assert result["contact_id"] != legacy.id
    assert legacy.is_synthetic_demo is False
    assert legacy.id == "existing-real-id"
