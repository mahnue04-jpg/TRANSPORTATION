"""Pure recovery policy tests; no deletion, live uploads or paid services."""
from dataclasses import replace

import pytest

from app.core.nova.work_revenue.operations_artifact_inventory import OrphanInventory
from app.core.nova.work_revenue.operations_recovery_triage import (
    FileObservation, OrphanScan, triage_orphan_artifacts,
)


def _scan(time, *, orphan=("orphan.artifact",), size=10, modified=100):
    return OrphanScan(
        observed_at=time,
        inventory=OrphanInventory(
            registered_files=("valid.artifact",),
            unregistered_files=orphan,
            missing_files=("missing.artifact",),
            unexpected_entries=("symlink",),
        ),
        files=tuple(
            FileObservation(name=name, size=size, modified_at=modified)
            for name in orphan
        ),
    )


def test_stable_old_orphan_is_review_only_and_registered_stays_protected():
    result = triage_orphan_artifacts(
        previous=_scan(3700), current=_scan(4100),
        active_lease_expirations={},
    )
    assert result.needs_review == ("orphan.artifact",)
    assert {"valid.artifact", "missing.artifact", "symlink"} <= set(result.protected)


def test_active_lease_prevents_candidate():
    result = triage_orphan_artifacts(
        previous=_scan(3700), current=_scan(4100),
        active_lease_expirations={"orphan.artifact": 4200},
    )
    assert not result.needs_review
    assert "orphan.artifact" in result.protected


@pytest.mark.parametrize("current", [
    _scan(4100, size=11),
    _scan(4100, modified=500),
    _scan(4100, modified=4000),
    _scan(4100, orphan=()),
])
def test_changed_recent_or_disappeared_orphan_not_reviewed(current):
    result = triage_orphan_artifacts(
        previous=_scan(3700), current=current,
        active_lease_expirations={},
    )
    assert not result.needs_review


def test_recent_orphan_protected_even_with_stable_snapshots():
    result = triage_orphan_artifacts(
        previous=_scan(3700, modified=1000),
        current=_scan(4100, modified=1000),
        active_lease_expirations={},
    )
    assert not result.needs_review


@pytest.mark.parametrize("previous,current", [
    (_scan(3800), _scan(4000)),
    (_scan(4200), _scan(4100)),
])
def test_scan_interval_enforced(previous, current):
    with pytest.raises(ValueError):
        triage_orphan_artifacts(
            previous=previous, current=current,
            active_lease_expirations={},
        )


def test_invalid_lease_data_fail_closed():
    with pytest.raises(ValueError):
        triage_orphan_artifacts(
            previous=_scan(3700), current=_scan(4100),
            active_lease_expirations={"orphan.artifact": float("nan")},
        )
