"""Fail-closed tests for explicit owner staging booking preparation."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.service import GrowthAgentService


def setup_service(db_name="nova_ga_receptionist_dispos", demo=True, services=None):
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(url=SimpleNamespace(database=db_name))
    profile = SimpleNamespace(
        services_json=services if services is not None else [
            {"code": "consult", "name": "Consultation", "duration_minutes": 30}
        ],
        activated=False,
    )
    svc = GrowthAgentService.__new__(GrowthAgentService)
    svc.db = db
    svc._require_profile = MagicMock(return_value=profile)
    svc._org_query = MagicMock()
    svc._org_query.return_value.filter_by.return_value.one_or_none.return_value = None
    svc._org_query.return_value.count.return_value = 0
    return svc, db, profile


@pytest.mark.parametrize("db_name", ["amicor_health_isf", "nova_ga_490_dispos", "production", "", "nova_receptionist_test"])
def test_rejects_all_non_isolated_databases(db_name, monkeypatch):
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True)
    svc, db, _ = setup_service(db_name=db_name)
    with pytest.raises(GrowthAgentError) as error:
        svc.prepare_staging_booking_service("org-a", service_code="consult", actor_user_id="owner")
    assert error.value.http_status == 403
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_rejects_when_demo_mode_disabled(monkeypatch):
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: False)
    svc, db, _ = setup_service()
    with pytest.raises(GrowthAgentError) as error:
        svc.prepare_staging_booking_service("org-a", service_code="consult", actor_user_id="owner")
    assert error.value.http_status == 403
    db.commit.assert_not_called()


def test_rejects_unknown_service_without_database_write(monkeypatch):
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True)
    svc, db, _ = setup_service()
    with pytest.raises(GrowthAgentError) as error:
        svc.prepare_staging_booking_service("org-a", service_code="other", actor_user_id="owner")
    assert error.value.http_status == 404
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_prepares_only_profile_defined_service_and_weekday_rules(monkeypatch):
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True)
    svc, db, profile = setup_service()
    result = svc.prepare_staging_booking_service("org-a", service_code="consult", actor_user_id="owner")
    assert result["service_code"] == "consult"
    assert result["staging_only"] is True
    assert result["external_delivery_enabled"] is False
    assert result["profile_activated"] is False
    assert profile.activated is False
    assert result["availability_rules_created"] == 5
    assert db.add.call_count == 6
    db.commit.assert_called_once()


def test_existing_service_remains_idempotent(monkeypatch):
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True)
    svc, db, _ = setup_service()
    svc._org_query.return_value.filter_by.return_value.one_or_none.return_value = SimpleNamespace(active=True)
    svc._org_query.return_value.count.return_value = 5
    result = svc.prepare_staging_booking_service("org-a", service_code="consult", actor_user_id="owner")
    assert result["created"] is False
    assert result["availability_rules_created"] == 0
    db.add.assert_not_called()


def test_inactive_service_not_reactivated(monkeypatch):
    monkeypatch.setattr("app.core.nova.growth_agent.flags.demo_mode_enabled", lambda: True)
    svc, db, _ = setup_service()
    svc._org_query.return_value.filter_by.return_value.one_or_none.return_value = SimpleNamespace(active=False)
    with pytest.raises(GrowthAgentError) as error:
        svc.prepare_staging_booking_service("org-a", service_code="consult", actor_user_id="owner")
    assert error.value.http_status == 409
    db.commit.assert_not_called()
