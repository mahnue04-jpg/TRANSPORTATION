"""Pure, read-only policy for triaging potentially orphaned local artifacts.

Never deletes a file. Inventory consistency is necessary but insufficient:
a future production worker must coordinate durable leases, transaction state,
backup policy, operator approval, and a final recheck before any cleanup.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .operations_artifact_inventory import OrphanInventory


@dataclass(frozen=True)
class FileObservation:
    name: str
    size: int
    modified_at: float


@dataclass(frozen=True)
class OrphanScan:
    observed_at: float
    inventory: OrphanInventory
    files: tuple[FileObservation, ...]


@dataclass(frozen=True)
class RecoveryTriage:
    needs_review: tuple[str, ...]
    protected: tuple[str, ...]


def triage_orphan_artifacts(
    *, previous: OrphanScan, current: OrphanScan,
    active_lease_expirations: dict[str, float],
    minimum_age_seconds: int = 3600,
    minimum_scan_gap_seconds: int = 300,
) -> RecoveryTriage:
    """Identify *review-only* candidates after two stable inventory snapshots.

    An absent/invalid lease record does not grant deletion permission. Both
    scans must be supplied by a trusted worker using an authoritative lease
    registry; results are advisory and no files are opened or deleted.
    """
    if (
        not isinstance(minimum_age_seconds, int)
        or isinstance(minimum_age_seconds, bool)
        or minimum_age_seconds < 3600
        or not isinstance(minimum_scan_gap_seconds, int)
        or isinstance(minimum_scan_gap_seconds, bool)
        or minimum_scan_gap_seconds < 300
        or not isinstance(active_lease_expirations, dict)
    ):
        raise ValueError("Invalid recovery policy")
    if not isinstance(previous, OrphanScan) or not isinstance(current, OrphanScan):
        raise ValueError("Two trusted scans are required")
    if not all(
        isinstance(t, (int, float)) and isfinite(t)
        for t in (previous.observed_at, current.observed_at)
    ):
        raise ValueError("Invalid scan timestamps")
    if current.observed_at - previous.observed_at < minimum_scan_gap_seconds:
        raise ValueError("Scans are too close or out of order")
    if not all(
        isinstance(v, (int, float)) and isfinite(v)
        for v in active_lease_expirations.values()
    ):
        raise ValueError("Lease registry must be valid")
    older = {entry.name: entry for entry in previous.files}
    newer = {entry.name: entry for entry in current.files}
    candidates = set(previous.inventory.unregistered_files) & set(
        current.inventory.unregistered_files
    )
    protected = set(current.inventory.unregistered_files) - candidates
    approved_for_review = set()
    for name in candidates:
        old, new = older.get(name), newer.get(name)
        if (
            old is None or new is None
            or not isinstance(old.size, int) or old.size < 0
            or not isinstance(new.size, int) or new.size < 0
            or not isinstance(old.modified_at, (int, float))
            or not isinstance(new.modified_at, (int, float))
            or not isfinite(old.modified_at) or not isfinite(new.modified_at)
            or old.size != new.size or old.modified_at != new.modified_at
            or new.modified_at > previous.observed_at
            or current.observed_at - new.modified_at < minimum_age_seconds
            or active_lease_expirations.get(name, float("-inf")) > current.observed_at
        ):
            protected.add(name)
        else:
            approved_for_review.add(name)
    # Any newly registered or unexpected entry is never a cleanup candidate.
    protected.update(current.inventory.registered_files)
    protected.update(current.inventory.unexpected_entries)
    protected.update(current.inventory.missing_files)
    return RecoveryTriage(
        needs_review=tuple(sorted(approved_for_review)),
        protected=tuple(sorted(protected)),
    )
