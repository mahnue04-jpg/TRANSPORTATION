"""Unit tests for the isolated Nova cross-agent event envelope.

No database, backend service, network, paid provider or live customer data.
The module is loaded by path so collection does not execute app.core.nova.
"""
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_EVENTS = Path(__file__).resolve().parents[1] / "app/core/nova/agent_events.py"
_spec = importlib.util.spec_from_file_location("nova_agent_events_under_test", _EVENTS)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

Agent = _module.Agent
AgentEvent = _module.AgentEvent
EventType = _module.EventType
SCHEMA_VERSION = _module.SCHEMA_VERSION


def event(**changes):
    values = {
        "schema_version": SCHEMA_VERSION,
        "event_id": "evt-001",
        "correlation_id": "journey-001",
        "organization_id": "org-001",
        "source_agent": Agent.GROWTH,
        "target_agent": Agent.WORK_REVENUE,
        "event_type": EventType.LEAD_QUALIFIED,
        "subject_kind": "lead",
        "subject_id": "lead-001",
        "synthetic": True,
        "occurred_at": datetime(2026, 11, 17, tzinfo=timezone.utc),
        "idempotency_key": "org-001:lead-001:qualified",
        "payload_reference": "private:lead-001",
        "consent_reference": "consent-001",
    }
    values.update(changes)
    return AgentEvent(**values)


def test_valid_synthetic_lead_handoff_round_trips():
    original = event()
    result = AgentEvent.from_mapping(original.to_mapping())
    assert result == original
    assert result.synthetic is True


def test_sensitive_arbitrary_data_cannot_be_added():
    raw = event().to_mapping()
    raw["customer_email"] = "do-not-copy@example.com"
    with pytest.raises(ValueError, match="unexpected event fields"):
        AgentEvent.from_mapping(raw)


@pytest.mark.parametrize("bad", ["", "a" * 129, "email@example.com", "contains spaces"])
def test_identifiers_reject_invalid_values(bad):
    with pytest.raises(ValueError, match="opaque identifier"):
        event(organization_id=bad)


def test_unsupported_version_fails_closed():
    with pytest.raises(ValueError, match="unsupported"):
        event(schema_version="nova.agent-event.v99")


def test_wrong_agent_route_fails_closed():
    with pytest.raises(ValueError, match="not permitted"):
        event(target_agent=Agent.OPERATIONS)


def test_missing_consent_fails_closed():
    with pytest.raises(ValueError, match="consent"):
        event(consent_reference=None)


def test_missing_approval_fails_closed():
    with pytest.raises(ValueError, match="approval"):
        event(source_agent=Agent.OWNER, target_agent=Agent.OPERATIONS,
              event_type=EventType.TASK_APPROVED, consent_reference=None)


def test_owner_approved_synthetic_task_route_valid():
    item = event(source_agent=Agent.OWNER, target_agent=Agent.OPERATIONS,
                 event_type=EventType.TASK_APPROVED, consent_reference=None,
                 approval_reference="owner-approval-1")
    assert item.approval_reference == "owner-approval-1"


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone"):
        event(occurred_at=datetime(2026, 11, 17))


def test_malformed_timestamp_rejected():
    raw = event().to_mapping()
    raw["occurred_at"] = "not-a-date"
    with pytest.raises(ValueError, match="invalid agent event"):
        AgentEvent.from_mapping(raw)


def test_bool_must_be_strict():
    with pytest.raises(ValueError, match="boolean"):
        event(synthetic=1)


def test_unrecognized_event_type_rejected():
    raw = event().to_mapping()
    raw["event_type"] = "auto_send_email"
    with pytest.raises(ValueError, match="invalid agent event"):
        AgentEvent.from_mapping(raw)


def test_event_contract_does_not_dispatch():
    """Construction and serialization are pure; no execution is possible here."""
    item = event()
    assert "approval_reference" in item.to_mapping()
    assert not hasattr(item, "execute")
