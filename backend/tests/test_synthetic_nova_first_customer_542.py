"""Six-step fictional first-customer acceptance with no external side effects."""
from datetime import datetime, timedelta, timezone

import pytest

from synthetic_nova_first_customer_542 import SyntheticCampaignBridge
from synthetic_nova_handoff_542 import (
    Agent, AgentEvent, Approval, Consent, EventType, Principal,
    SCHEMA_VERSION, SyntheticHandoff,
)

NOW = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)
OWNER = Principal("owner-1", "org-A", "owner")
STUDIO = Principal("studio-test-service", "org-A", "agent", Agent.CREATIVE_STUDIO)
ROUTES = [
    (Agent.GROWTH, Agent.WORK_REVENUE, EventType.LEAD_QUALIFIED),
    (Agent.WORK_REVENUE, Agent.OWNER, EventType.OPPORTUNITY_REVIEW),
    (Agent.OWNER, Agent.OPERATIONS, EventType.TASK_APPROVED),
    (Agent.OPERATIONS, Agent.OWNER, EventType.TASK_COMPLETED),
]


def event(source, target, kind, *, idx, subject="lead-1", subject_kind="lead",
          org="org-A", corr="campaign-1", synthetic=True, **changes):
    values = dict(schema_version=SCHEMA_VERSION, event_id=f"event-{idx}",
                  correlation_id=corr, organization_id=org, source_agent=source,
                  target_agent=target, event_type=kind, subject_kind=subject_kind,
                  subject_id=subject, synthetic=synthetic, occurred_at=NOW,
                  idempotency_key=f"idem-{idx}",
                  payload_reference="synthetic:asset-1" if idx == "asset" else "synthetic:lead-1",
                  consent_reference="consent-1" if idx == 0 else None,
                  approval_reference="approval-1" if idx == 2 else None)
    values.update(changes)
    return AgentEvent(**values)


def assets():
    return event(Agent.CREATIVE_STUDIO, Agent.GROWTH, EventType.ASSET_READY,
                 idx="asset", subject="campaign-1", subject_kind="campaign")


def flow():
    handler = SyntheticHandoff("org-A", NOW)
    handler.register_payload("synthetic:lead-1", "lead-1")
    handler.stage_consent(Consent("consent-1", "org-A", "lead-1", NOW + timedelta(hours=1)))
    handler.stage_approval(Approval("approval-1", "org-A", "lead-1",
                                    "execute_mock_task", "owner-1",
                                    NOW + timedelta(hours=1)), OWNER)
    return handler


def caller(i):
    return OWNER if i == 2 else Principal(
        f"mock-agent-{i}", "org-A", "agent", ROUTES[i][0]
    )


def lead(i, **changes):
    source, target, kind = ROUTES[i]
    return event(source, target, kind, idx=i, **changes)


def test_first_customer_creative_growth_to_completion():
    bridge = SyntheticCampaignBridge("org-A", NOW)
    handler = flow()
    asset = assets()
    assert bridge.accept_asset(asset, STUDIO) == "asset_ready"
    assert bridge.accept_asset(asset, STUDIO) == "duplicate"
    assert len(bridge._campaigns) == 1
    for i, state in enumerate(("qualified", "pending_approval", "approved", "completed")):
        current = lead(i)
        if i == 0:
            bridge.require_asset_for_lead(current)
        assert handler.handle(current, caller(i)) == state
    assert handler.journey("campaign-1", OWNER) == (
        "qualified", "pending_approval", "approved", "completed"
    )
    assert handler.handle(lead(3), caller(3)) == "duplicate"


def test_growth_lead_without_creative_asset_denied():
    bridge = SyntheticCampaignBridge("org-A", NOW)
    with pytest.raises(PermissionError):
        bridge.require_asset_for_lead(lead(0))


@pytest.mark.parametrize("caller_override", [
    Principal("forged", "org-A", "agent", Agent.GROWTH),
    Principal("studio-B", "org-B", "agent", Agent.CREATIVE_STUDIO),
    Principal("guest", "org-A", "guest"),
])
def test_asset_requires_correct_tenant_and_studio_identity(caller_override):
    with pytest.raises(PermissionError):
        SyntheticCampaignBridge("org-A", NOW).accept_asset(assets(), caller_override)


def test_asset_rejects_live_media_and_event_collisions():
    bridge = SyntheticCampaignBridge("org-A", NOW)
    with pytest.raises(PermissionError):
        bridge.accept_asset(assets().__class__(**{
            **assets().__dict__, "synthetic": False
        }), STUDIO)
    bridge.accept_asset(assets(), STUDIO)
    with pytest.raises(PermissionError):
        bridge.accept_asset(event(Agent.CREATIVE_STUDIO, Agent.GROWTH,
                                  EventType.ASSET_READY, idx="asset",
                                  subject="different-campaign",
                                  subject_kind="campaign"), STUDIO)


def test_approval_and_consent_remain_required_after_asset():
    bridge = SyntheticCampaignBridge("org-A", NOW)
    bridge.accept_asset(assets(), STUDIO)
    handler = flow()
    handler.consent.clear()
    bridge.require_asset_for_lead(lead(0))
    with pytest.raises(PermissionError):
        handler.handle(lead(0), caller(0))
    handler = flow()
    bridge.require_asset_for_lead(lead(0))
    handler.handle(lead(0), caller(0))
    handler.handle(lead(1), caller(1))
    handler.approvals.clear()
    with pytest.raises(PermissionError):
        handler.handle(lead(2), caller(2))


def test_no_live_dispatch_or_customer_data():
    bridge = SyntheticCampaignBridge("org-A", NOW)
    assert not any(hasattr(bridge, action) for action in ("send", "deploy", "charge", "dispatch"))
