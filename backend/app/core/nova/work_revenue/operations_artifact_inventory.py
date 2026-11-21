"""Read-only orphan inventory for isolated local test artifacts.

No deletion is performed. Production reconciliation needs transactional
ownership checks, leases, aging, backups, audit trail, and operator review.
Do not run this prototype against customer storage.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .operations_local_artifact_store import LocalPrivateArtifactStore

_NAME = re.compile(r"^[0-9a-f]{64}\.artifact$")


@dataclass(frozen=True)
class OrphanInventory:
    registered_files: tuple[str, ...]
    unregistered_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    unexpected_entries: tuple[str, ...]


def inventory_local_artifacts(
    connection: sqlite3.Connection, store: LocalPrivateArtifactStore,
) -> OrphanInventory:
    """Compare private files to trusted SQL metadata without mutating either.

    This cannot tell an orphan from a concurrently uploading file and MUST NOT
    be used to authorize automatic deletion.
    """
    if not isinstance(store, LocalPrivateArtifactStore):
        raise TypeError("Expected isolated private artifact store")
    rows = connection.execute(
        "SELECT storage_key FROM operations_csv_artifact_manifest"
    ).fetchall()
    registered = {
        sha256(row[0].encode("utf-8")).hexdigest() + ".artifact"
        for row in rows
    }
    found: set[str] = set()
    unexpected: set[str] = set()
    # lstat avoids following symlinks while building this read-only report.
    for item in store.root.iterdir():
        stat = item.lstat()
        if not _NAME.fullmatch(item.name) or not item.is_file() or item.is_symlink():
            unexpected.add(item.name)
        elif os.path.isfile(item) and stat.st_size >= 0:
            found.add(item.name)
    return OrphanInventory(
        registered_files=tuple(sorted(found & registered)),
        unregistered_files=tuple(sorted(found - registered)),
        missing_files=tuple(sorted(registered - found)),
        unexpected_entries=tuple(sorted(unexpected)),
    )
