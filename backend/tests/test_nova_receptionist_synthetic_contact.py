"""Staging-only synthetic contact preparation: do not touch preexisting CRM leads."""

from __future__ import annotations

import pytest

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.models import GaContact
from app.core.nova.growth_agent.service import GrowthAgentService


def test_booking_fixture_requires_disposable_db(db, monkeypatch):
    monkeypatch.setattr(
        "app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True
    )
    svc = GrowthAgentService(db)
    with pytest.raises(GrowthAgentError) as exc:
        svc.prepare_staging_booking_contact("org-test", actor_user_id="owner-test")
    assert exc.value.code == "STAGING_ONLY"
    assert db.query(GaContact).count() == 0


def test_booking_fixture_rejects_when_demo_mode_off(db, monkeypatch):
    monkeypatch.setattr(
        "app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: False
    )
    svc = GrowthAgentService(db)
    with pytest.raises(GrowthAgentError) as exc:
        svc.prepare_staging_booking_contact("org-test", actor_user_id="owner-test")
    assert exc.value.code == "STAGING_ONLY"
    assert db.query(GaContact).count() == 0


def test_fixture_is_synthetic_and_never_relabels_legacy_lead(db, monkeypatch):
    """Simulate the approved isolated DB without connecting to Render."""
    from unittest.mock import Mock

    monkeypatch.setattr(
        "app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True
    )
    svc = GrowthAgentService(db)
    legacy = GaContact(
        id="legacy-alex", organization_id="org-test", display_name="Alex Demo",
        lead_state="booked", notes="Synthetic demo -- qualified",
        is_synthetic_demo=False,
    )
    db.add(legacy)
    db.commit()

    # Replace only URL metadata on the real in-memory test engine.
    # Do not fake Session.get_bind; ORM queries must still run against SQLite.
    real_engine = db.get_bind()
    fake_url = Mock()
    fake_url.database = "nova_ga_receptionist_dispos"
    monkeypatch.setattr(real_engine, "url", fake_url)
    monkeypatch.setattr(svc, "_require_profile", lambda org: object())
    monkeypatch.setattr(svc, "audit", lambda *args, **kwargs: None)
    created = svc.prepare_staging_booking_contact("org-test", actor_user_id="owner-test")
    assert created["created"] is True
    assert created["is_synthetic_demo"] is True
    assert created["live_delivery"] is False
    assert created["contact_id"] != legacy.id
    contact = db.query(GaContact).filter_by(id=created["contact_id"]).one()
    assert contact.is_synthetic_demo is True
    assert contact.do_not_contact is True
    assert contact.display_name == "Nova Booking Test (Synthetic)"
    assert db.query(GaContact).filter_by(id=legacy.id).one().is_synthetic_demo is False
    assert db.query(GaContact).filter_by(id=legacy.id).one().lead_state == "booked"

    reused = svc.prepare_staging_booking_contact("org-test", actor_user_id="owner-test")
    assert reused["created"] is False
    assert reused["contact_id"] == created["contact_id"]
    assert db.query(GaContact).count() == 2
