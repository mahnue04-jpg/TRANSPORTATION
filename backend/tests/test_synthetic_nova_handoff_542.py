"""Synthetic-only Nova handoff acceptance tests; no services or credentials."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import synthetic_nova_handoff_542 as h

NOW = datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc)


def setup():
    flow = h.SyntheticHandoff("org-A", NOW)
    flow.register_payload("synthetic:lead-1")
    flow.stage_consent(h.Consent("consent-1", "org-A", "lead-1", NOW + timedelta(hours=1)))
    owner = h.Principal("owner-1", "org-A", "owner")
    flow.stage_approval(h.Approval("approval-1", "org-A", "lead-1",
                                   "execute_mock_task", "owner-1",
                                   NOW + timedelta(hours=1)), owner)
    return flow, owner


def make_event(stage, **changes):
    routes = [
        (h.Agent.GROWTH, h.Agent.WORK_REVENUE, h.EventType.LEAD_QUALIFIED),
        (h.Agent.WORK_REVENUE, h.Agent.OWNER, h.EventType.OPPORTUNITY_REVIEW),
        (h.Agent.OWNER, h.Agent.OPERATIONS, h.EventType.TASK_APPROVED),
        (h.Agent.OPERATIONS, h.Agent.OWNER, h.EventType.TASK_COMPLETED),
    ]
    src, target, event_type = routes[stage]
    values = dict(schema_version=h.SCHEMA_VERSION, event_id=f"evt-{stage}",
                  correlation_id="journey-1", organization_id="org-A",
                  source_agent=src, target_agent=target, event_type=event_type,
                  subject_kind="lead", subject_id="lead-1", synthetic=True,
                  occurred_at=NOW, idempotency_key=f"key-{stage}",
                  payload_reference="synthetic:lead-1",
                  consent_reference="consent-1" if stage == 0 else None,
                  approval_reference="approval-1" if stage == 2 else None)
    values.update(changes)
    return h.AgentEvent(**values)


def principal(stage, owner):
    return owner if stage == 2 else h.Principal(f"service-{stage}", "org-A", "agent", make_event(stage).source_agent)


def assert_denied(fn):
    try:
        fn()
    except (PermissionError, ValueError):
        return
    raise AssertionError("unsafe event was not rejected")


def test_four_stage_synthetic_journey():
    flow, owner = setup()
    assert [flow.handle(make_event(i), principal(i, owner)) for i in range(4)] == [
        "qualified", "pending_approval", "approved", "completed"]
    assert flow.journey("journey-1", owner) == (
        "qualified", "pending_approval", "approved", "completed")


def test_duplicate_delivery_is_idempotent():
    flow, owner = setup()
    event = make_event(0)
    caller = principal(0, owner)
    assert flow.handle(event, caller) == "qualified"
    assert flow.handle(event, caller) == "duplicate"
    assert len(flow.audit) == 1


def test_collision_of_idempotency_key_is_rejected():
    flow, owner = setup()
    flow.handle(make_event(0), principal(0, owner))
    assert_denied(lambda: flow.handle(make_event(0, event_id="different"), principal(0, owner)))


def test_out_of_order_delivery_is_rejected():
    flow, owner = setup()
    assert_denied(lambda: flow.handle(make_event(1), principal(1, owner)))


def test_wrong_tenant_and_unauthorized_read_are_rejected():
    flow, owner = setup()
    assert_denied(lambda: flow.handle(make_event(0, organization_id="org-B"), principal(0, owner)))
    assert_denied(lambda: flow.handle(make_event(0), h.Principal("service", "org-B", "agent", h.Agent.GROWTH)))
    assert_denied(lambda: flow.journey("journey-1", h.Principal("owner-B", "org-B", "owner")))


def test_forged_source_agent_is_rejected():
    flow, owner = setup()
    assert_denied(lambda: flow.handle(make_event(0), h.Principal("service-operations", "org-A", "agent", h.Agent.OPERATIONS)))


def test_consent_missing_revoked_expired_or_subject_mismatch():
    for consent in [
        None,
        h.Consent("consent-1", "org-A", "lead-1", NOW + timedelta(hours=1), True),
        h.Consent("consent-1", "org-A", "lead-1", NOW - timedelta(seconds=1)),
        h.Consent("consent-1", "org-A", "other-lead", NOW + timedelta(hours=1)),
    ]:
        flow, owner = setup()
        flow.consent.clear()
        if consent is not None:
            flow.stage_consent(consent)
        assert_denied(lambda: flow.handle(make_event(0), principal(0, owner)))


def test_wrong_action_and_revoked_approval_are_rejected():
    for approval in [
        h.Approval("approval-1", "org-A", "lead-1", "send_real_message", "owner-1", NOW + timedelta(hours=1)),
        h.Approval("approval-1", "org-A", "lead-1", "execute_mock_task", "owner-1", NOW + timedelta(hours=1), True),
    ]:
        flow, owner = setup()
        flow.handle(make_event(0), principal(0, owner))
        flow.handle(make_event(1), principal(1, owner))
        flow.approvals["approval-1"] = approval
        assert_denied(lambda: flow.handle(make_event(2), owner))


def test_fake_owner_and_missing_approval_are_rejected():
    flow, owner = setup()
    flow.handle(make_event(0), principal(0, owner))
    flow.handle(make_event(1), principal(1, owner))
    assert_denied(lambda: flow.handle(make_event(2), h.Principal("attacker", "org-A", "owner")))
    flow.approvals.clear()
    assert_denied(lambda: flow.handle(make_event(2), owner))


def test_unauthorized_payload_reference_is_rejected():
    flow, owner = setup()
    assert_denied(lambda: flow.handle(make_event(0, payload_reference="synthetic:unknown"), principal(0, owner)))


def test_stale_and_future_events_are_rejected():
    for timestamp in [NOW - timedelta(minutes=6), NOW + timedelta(seconds=1)]:
        flow, owner = setup()
        assert_denied(lambda: flow.handle(make_event(0, occurred_at=timestamp), principal(0, owner)))


def test_live_event_is_rejected():
    flow, owner = setup()
    assert_denied(lambda: flow.handle(make_event(0, synthetic=False), principal(0, owner)))


def test_subject_change_within_journey_is_rejected():
    flow, owner = setup()
    flow.handle(make_event(0), principal(0, owner))
    assert_denied(lambda: flow.handle(make_event(1, subject_id="another-lead"), principal(1, owner)))


def test_no_dispatch_apis_on_harness():
    flow, _ = setup()
    assert not hasattr(flow, "send")
    assert not hasattr(flow, "execute")
    assert not hasattr(flow, "deploy")
