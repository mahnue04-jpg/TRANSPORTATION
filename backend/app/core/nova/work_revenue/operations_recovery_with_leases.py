"""Conservative read-only integration between SQLite leases and recovery triage.

No deletion, production adapter, or customer API. When an active upload lease
exists, an unregistered artifact cannot be proven unrelated to that upload:
therefore ALL orphan candidates are protected pending authoritative linkage.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .operations_recovery_triage import (
    OrphanScan, RecoveryTriage, triage_orphan_artifacts,
)
from .operations_upload_leases import active_lease_expirations


@dataclass(frozen=True)
class LeaseAwareRecoveryReport:
    triage: RecoveryTriage
    active_upload_jobs: int
    blocked_by_active_uploads: bool


def audit_with_upload_leases(
    connection: sqlite3.Connection, *,
    previous: OrphanScan, current: OrphanScan,
    minimum_age_seconds: int = 3600,
    minimum_scan_gap_seconds: int = 300,
) -> LeaseAwareRecoveryReport:
    """Return review-only candidates, never authorize filesystem mutation.

    The input snapshots must come from trusted read-only inventories. The
    calling worker must use a single, authoritative lease database and ensure
    uploaded files cannot race between snapshot and lease lookup. A global
    lease guard is intentional until artifacts are linked to jobs durably.
    """
    # Run the existing two-scan and age validation first.
    assessed = triage_orphan_artifacts(
        previous=previous, current=current, active_lease_expirations={},
        minimum_age_seconds=minimum_age_seconds,
        minimum_scan_gap_seconds=minimum_scan_gap_seconds,
    )
    active = active_lease_expirations(connection, at=current.observed_at)
    if active:
        return LeaseAwareRecoveryReport(
            triage=RecoveryTriage(
                needs_review=(),
                protected=tuple(sorted(
                    set(assessed.protected) |
                    set(assessed.needs_review)
                )),
            ),
            active_upload_jobs=len(active),
            blocked_by_active_uploads=True,
        )
    return LeaseAwareRecoveryReport(
        triage=assessed,
        active_upload_jobs=0,
        blocked_by_active_uploads=False,
    )
