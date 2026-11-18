"""Owner-only synthetic journey projection tests."""
from pathlib import Path

import pytest

from synthetic_nova_replay_542 import SyntheticReplayLedger
from synthetic_nova_workspace_542 import read_synthetic_journey


def event(step, org="org-A", journey="journey-1"):
    return dict(organization_id=org, correlation_id=journey,
                event_id=f"evt-{step}", idempotency_key=f"key-{step}",
                fingerprint=f"synthetic-fingerprint-{step}", step=step)


def view(store, org="org-A", journey="journey-1", viewer_org="org-A", role="owner"):
    return read_synthetic_journey(
        store, organization_id=org, correlation_id=journey,
        viewer_organization=viewer_org, viewer_role=role)


def test_owner_sees_completed_synthetic_journey(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "workspace.sqlite")
    for stage in range(4):
        store.accept(**event(stage))
    result = view(store)
    assert result.status == "completed"
    assert result.assigned_agent == "owner"
    assert [row[0] for row in result.events] == [
        "qualified", "pending_approval", "approved", "completed"]
    assert result.pending_owner_approval is False
    store.close()


def test_owner_sees_pending_approval(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "pending.sqlite")
    store.accept(**event(0))
    store.accept(**event(1))
    result = view(store)
    assert result.status == "pending_approval"
    assert result.assigned_agent == "owner"
    assert result.pending_owner_approval is True
    store.close()


def test_unknown_journey_is_private_empty_projection(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "unknown.sqlite")
    result = view(store)
    assert result.status == "not_found"
    assert result.events == ()
    store.close()


@pytest.mark.parametrize("viewer_org,role", [
    ("org-B", "owner"), ("org-A", "agent"), ("org-A", "guest"),
])
def test_unauthorized_viewer_denied(tmp_path, viewer_org, role):
    store = SyntheticReplayLedger(tmp_path / "denied.sqlite")
    store.accept(**event(0))
    with pytest.raises(PermissionError, match="authorization"):
        view(store, viewer_org=viewer_org, role=role)
    store.close()


def test_org_isolation_in_workspace_projection(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "tenant.sqlite")
    store.accept(**event(0, org="org-A"))
    store.accept(**event(0, org="org-B"))
    store.accept(**event(1, org="org-B"))
    assert view(store, org="org-A", viewer_org="org-A").status == "qualified"
    assert view(store, org="org-B", viewer_org="org-B").status == "pending_approval"
    store.close()


def test_projection_survives_disposable_restart(tmp_path):
    path = tmp_path / "restart.sqlite"
    store = SyntheticReplayLedger(path)
    store.accept(**event(0))
    store.accept(**event(1))
    store.close()
    again = SyntheticReplayLedger(path)
    assert view(again).pending_owner_approval is True
    again.close()
