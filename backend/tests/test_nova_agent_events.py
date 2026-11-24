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


def test_synthetic_handoff_chain_contract():
    """Rehearse the envelope sequence only, not runtime authorization or dispatch."""
    route_specs = [
        (Agent.GROWTH, Agent.WORK_REVENUE, EventType.LEAD_QUALIFIED,
         "lead", "syn-lead-1", "syn-consent-1", None),
        (Agent.WORK_REVENUE, Agent.OWNER, EventType.OPPORTUNITY_REVIEW,
         "opportunity", "syn-opp-1", None, None),
        (Agent.OWNER, Agent.OPERATIONS, EventType.TASK_APPROVED,
         "task", "syn-task-1", None, "syn-approval-1"),
        (Agent.OPERATIONS, Agent.OWNER, EventType.TASK_COMPLETED,
         "task", "syn-task-1", None, None),
    ]
    journey = []
    for i, (source, target, kind, subject_kind, subject_id, consent, approval) in enumerate(route_specs):
        envelope = event(
            event_id=f"syn-event-{i}", correlation_id="syn-journey-1",
            organization_id="syn-org-1", source_agent=source, target_agent=target,
            event_type=kind, subject_kind=subject_kind, subject_id=subject_id,
            idempotency_key=f"syn-journey-1:{i}", payload_reference=f"syn-payload-{i}",
            consent_reference=consent, approval_reference=approval,
        )
        journey.append(AgentEvent.from_mapping(envelope.to_mapping()))
    assert all(item.synthetic for item in journey)
    assert {item.organization_id for item in journey} == {"syn-org-1"}
    assert {item.correlation_id for item in journey} == {"syn-journey-1"}
    assert len({item.idempotency_key for item in journey}) == len(journey)
    assert all(first.target_agent == second.source_agent
               for first, second in zip(journey, journey[1:]))
    assert journey[-2].subject_id == journey[-1].subject_id
    assert journey[-1].target_agent == Agent.OWNER


def test_synthetic_ledger_exact_replay_is_not_recorded_twice():
    ledger = _module.SyntheticEventLedger("org-001", "journey-001")
    original = event()
    assert ledger.record(original) is True
    assert ledger.record(AgentEvent.from_mapping(original.to_mapping())) is False


@pytest.mark.parametrize("changes", [
    {"event_id": "evt-002"},
    {"idempotency_key": "different-key"},
    {"payload_reference": "different-payload"},
])
def test_synthetic_ledger_rejects_conflicting_replay(changes):
    ledger = _module.SyntheticEventLedger("org-001", "journey-001")
    assert ledger.record(event()) is True
    with pytest.raises(ValueError, match="conflicting event replay"):
        ledger.record(event(**changes))
    assert ledger.record(event()) is False


@pytest.mark.parametrize("changes", [
    {"organization_id": "other-org"},
    {"correlation_id": "other-journey"},
    {"synthetic": False},
])
def test_synthetic_ledger_rejects_out_of_scope_events(changes):
    ledger = _module.SyntheticEventLedger("org-001", "journey-001")
    with pytest.raises(ValueError):
        ledger.record(event(**changes))
    assert ledger.record(event()) is True


def synthetic_handoff_fixture():
    controller = _module.SyntheticHandoff(
        "org-001", "journey-001", lead_id="lead-001",
        consent_reference="consent-001", opportunity_id="opp-001",
        task_id="task-001", approval_reference="approval-001",
    )
    specs = [
        (Agent.GROWTH, Agent.WORK_REVENUE, EventType.LEAD_QUALIFIED,
         "lead", "lead-001", "consent-001", None),
        (Agent.WORK_REVENUE, Agent.OWNER, EventType.OPPORTUNITY_REVIEW,
         "opportunity", "opp-001", None, None),
        (Agent.OWNER, Agent.OPERATIONS, EventType.TASK_APPROVED,
         "task", "task-001", None, "approval-001"),
        (Agent.OPERATIONS, Agent.OWNER, EventType.TASK_COMPLETED,
         "task", "task-001", None, None),
    ]
    items = [
        event(event_id=f"handoff-{i}", idempotency_key=f"handoff-key-{i}",
              source_agent=source, target_agent=target, event_type=kind,
              subject_kind=subject_kind, subject_id=subject_id,
              consent_reference=consent, approval_reference=approval)
        for i, (source, target, kind, subject_kind, subject_id, consent, approval)
        in enumerate(specs)
    ]
    return controller, items


def test_synthetic_handoff_completes_once_and_replays_are_noops():
    controller, items = synthetic_handoff_fixture()
    assert not controller.completed
    for i, item in enumerate(items, 1):
        assert controller.advance(item) is True
        assert controller.advance(item) is False
        assert controller.accepted_count == i
        assert controller.completed == (i == len(items))
    for item in items:
        assert controller.advance(item) is False
    assert controller.accepted_count == 4


@pytest.mark.parametrize("step,changes", [
    (0, {"consent_reference": "wrong-consent"}),
    (0, {"subject_id": "wrong-lead"}),
    (0, {"organization_id": "wrong-org"}),
    (0, {"synthetic": False}),
    (1, {"subject_id": "wrong-opportunity"}),
    (2, {"approval_reference": "wrong-approval"}),
    (2, {"subject_id": "wrong-task"}),
    (3, {"subject_id": "wrong-task"}),
    (3, {"correlation_id": "wrong-journey"}),
    (3, {"occurred_at": datetime(2026, 11, 16, tzinfo=timezone.utc)}),
    (3, {"idempotency_key": "handoff-key-2"}),
])
def test_synthetic_handoff_rejects_bad_evidence_without_advancing(step, changes):
    from dataclasses import replace
    controller, items = synthetic_handoff_fixture()
    for item in items[:step]:
        assert controller.advance(item)
    with pytest.raises(ValueError):
        controller.advance(replace(items[step], **changes))
    assert controller.accepted_count == step
    assert not controller.completed
    for item in items[step:]:
        assert controller.advance(item)
    assert controller.completed


@pytest.mark.parametrize("step,premature", [(0, 1), (0, 2), (0, 3), (1, 3), (2, 3)])
def test_synthetic_handoff_rejects_skipped_steps(step, premature):
    controller, items = synthetic_handoff_fixture()
    for item in items[:step]:
        assert controller.advance(item)
    with pytest.raises(ValueError, match="expected step"):
        controller.advance(items[premature])
    assert controller.accepted_count == step
    assert not controller.completed
