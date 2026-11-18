"""Restart/replay tests using disposable SQLite, never customer data."""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from synthetic_nova_replay_542 import SyntheticReplayLedger


def item(step: int = 0, org: str = "org-A", journey: str = "journey-1"):
    return dict(organization_id=org, correlation_id=journey,
                event_id=f"evt-{step}", idempotency_key=f"key-{step}",
                fingerprint=f"canonical-synthetic-event-{step}", step=step)


def test_completed_mock_journey_survives_reopen():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "disposable.sqlite"
        first = SyntheticReplayLedger(path)
        for stage in range(4):
            assert first.accept(**item(stage)) == "accepted"
        first.close()
        second = SyntheticReplayLedger(path)
        assert second.steps("org-A", "journey-1") == (0, 1, 2, 3)
        for stage in range(4):
            assert second.accept(**item(stage)) == "duplicate"
        assert second.steps("org-A", "journey-1") == (0, 1, 2, 3)
        second.close()


def test_reopen_partial_journey_resumes_without_duplicate_work():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "partial.sqlite"
        first = SyntheticReplayLedger(path)
        assert first.accept(**item(0)) == "accepted"
        first.close()
        second = SyntheticReplayLedger(path)
        assert second.accept(**item(0)) == "duplicate"
        assert second.accept(**item(1)) == "accepted"
        assert second.steps("org-A", "journey-1") == (0, 1)
        second.close()


def test_reject_out_of_order_stage_without_partial_write(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "out-of-order.sqlite")
    with pytest.raises(PermissionError, match="out-of-order"):
        store.accept(**item(2))
    assert store.steps("org-A", "journey-1") == ()
    assert store.accept(**item(0)) == "accepted"
    store.close()


def test_reject_conflicting_event_id_after_restart(tmp_path):
    path = tmp_path / "collision.sqlite"
    store = SyntheticReplayLedger(path)
    store.accept(**item(0))
    store.close()
    second = SyntheticReplayLedger(path)
    modified = dict(item(0), fingerprint="changed-fingerprint")
    with pytest.raises(PermissionError, match="event id collision"):
        second.accept(**modified)
    assert second.steps("org-A", "journey-1") == (0,)
    second.close()


def test_reject_conflicting_idempotency_key(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "key-collision.sqlite")
    store.accept(**item(0))
    conflicting = dict(item(1), idempotency_key="key-0")
    with pytest.raises(PermissionError, match="idempotency collision"):
        store.accept(**conflicting)
    assert store.steps("org-A", "journey-1") == (0,)
    store.close()


def test_organization_scope_keeps_ledger_entries_separate(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "orgs.sqlite")
    assert store.accept(**item(0, org="org-A")) == "accepted"
    assert store.accept(**item(0, org="org-B")) == "accepted"
    assert store.steps("org-A", "journey-1") == (0,)
    assert store.steps("org-B", "journey-1") == (0,)
    store.close()


def test_reject_same_stage_with_different_event_id(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "stage.sqlite")
    store.accept(**item(0))
    competing = dict(item(0), event_id="second-event", idempotency_key="second-key")
    with pytest.raises(PermissionError, match="out-of-order"):
        store.accept(**competing)
    assert store.steps("org-A", "journey-1") == (0,)
    store.close()


def test_invalid_step_rejected(tmp_path):
    store = SyntheticReplayLedger(tmp_path / "invalid.sqlite")
    with pytest.raises(ValueError, match="step out"):
        store.accept(**dict(item(0), step=True))
    store.close()
