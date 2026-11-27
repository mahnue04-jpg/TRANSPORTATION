"""Read-only recovery audit with durable artifact ownership links.

Offline safety check, not a production cleaner. Upload links protect files
even after a lease expires and before an artifact manifest is recorded.
Never deletes files or grants permission to delete them.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from hashlib import sha256

from .operations_recovery_triage import OrphanScan, RecoveryTriage
from .operations_recovery_with_leases import audit_with_upload_leases
from .operations_upload_artifact_links import linked_storage_keys


@dataclass(frozen=True)
class OwnershipAwareRecoveryReport:
    triage: RecoveryTriage
    active_upload_jobs: int
    linked_files_protected: tuple[str, ...]


def audit_with_artifact_links(
    connection: sqlite3.Connection, *, previous: OrphanScan,
    current: OrphanScan, minimum_age_seconds: int = 3600,
    minimum_scan_gap_seconds: int = 300,
) -> OwnershipAwareRecoveryReport:
    """Keep linked files protected regardless of lease state.

    Both trusted snapshots and the authoritative SQLite lease/link tables are
    required. Any SQL error fails closed; do not substitute empty link sets.
    """
    lease_report = audit_with_upload_leases(
        connection, previous=previous, current=current,
        minimum_age_seconds=minimum_age_seconds,
        minimum_scan_gap_seconds=minimum_scan_gap_seconds,
    )
    linked_names = {
        sha256(key.encode("utf-8")).hexdigest() + ".artifact"
        for key in linked_storage_keys(connection)
    }
    unregistered = set(current.inventory.unregistered_files)
    protected_links = linked_names & unregistered
    protected = set(lease_report.triage.protected) | protected_links
    review = set(lease_report.triage.needs_review) - protected_links
    return OwnershipAwareRecoveryReport(
        triage=RecoveryTriage(
            needs_review=tuple(sorted(review)),
            protected=tuple(sorted(protected)),
        ),
        active_upload_jobs=lease_report.active_upload_jobs,
        linked_files_protected=tuple(sorted(protected_links)),
    )
