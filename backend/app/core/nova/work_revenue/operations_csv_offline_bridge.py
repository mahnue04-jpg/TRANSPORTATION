"""Synthetic-only handoff from authenticated Work tasks to the offline CSV queue.

This module does NOT expose an HTTP route and MUST NOT be used with customer
files. Durable production work needs tenant-bound Postgres job records and
encrypted object storage, not local SQLite CSV text.
"""
from __future__ import annotations

import os
import sqlite3

from .operations_csv_runner import PreparedCSVJob, prepare_csv_job
from .operations_job_queue import JobConflict, ensure_schema
from .operations_owner_csv_api import (
    _completed_task_ids, _eligible_engagement, _eligible_task,
)


def prepare_synthetic_scoped_csv(
    db: sqlite3.Connection, *, owner_org: str, owner_user: str,
    engagement: dict, task_id: str, request_id: str,
    synthetic_csv: str, now: int,
) -> PreparedCSVJob:
    """Exercise an exact authorized task->idempotent job->review handoff in tests.

    Caller supplies owner identity only from a synthetic fixture; this is not
    a production authentication adapter. The environment guard is intentional.
    """
    if os.getenv("TESTING", "").strip().lower() != "true":
        raise JobConflict("Offline CSV bridge is restricted to synthetic tests")
    if not all(
        isinstance(value, str) and 0 < len(value.strip()) <= 80
        and all(ord(c) >= 32 and ord(c) != 127 and c not in ":/" for c in value)
        for value in (owner_org, owner_user, task_id, request_id)
    ):
        raise JobConflict("Invalid synthetic job scope")
    if not isinstance(engagement, dict) or not _eligible_engagement(
        engagement, owner_org, owner_user
    ):
        raise JobConflict("Engagement not authorized for synthetic CSV")
    eng_id = engagement.get("engagement_id")
    if not isinstance(eng_id, str) or not eng_id or len(eng_id) > 80 or ":" in eng_id:
        raise JobConflict("Invalid synthetic engagement ID")
    matches = [
        task for task in engagement.get("tasks", [])
        if isinstance(task, dict) and task.get("task_id") == task_id
    ]
    if len(matches) != 1 or not _eligible_task(
        matches[0], _completed_task_ids(engagement)
    ):
        raise JobConflict("Task not authorized for synthetic CSV")

    # Isolate by both tenant and owner, and bind retry identities to the
    # engagement and task so another assignment cannot reuse the same key.
    tenant = f"{owner_org}:{owner_user}"
    scoped_request = f"{eng_id}:{task_id}:{request_id}"
    if len(scoped_request) > 256:
        raise JobConflict("Synthetic request identity too long")
    ensure_schema(db)
    return prepare_csv_job(
        db, tenant_id=tenant, request_id=scoped_request,
        raw_csv=synthetic_csv, now=now,
    )
