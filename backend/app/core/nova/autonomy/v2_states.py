"""Explicit Phase 2C workflow transitions. No background processing."""
from __future__ import annotations

OPEN_STATUSES = frozenset(
    {
        "proposed",
        "awaiting_approval",
        "approved",
        "waiting",
        "running",
        "paused",
        "failed",
    }
)
TERMINAL_STATUSES = frozenset({"cancelled", "completed", "blocked_by_policy"})
APPROVE_FROM = frozenset({"proposed", "awaiting_approval"})
PAUSE_FROM = frozenset({"approved", "waiting"})
RESUME_FROM = frozenset({"paused"})
RETRY_FROM = frozenset({"failed"})
STEP_APPROVE_FROM = frozenset({"approved", "waiting"})
INTERNAL_TEST_ACTION = "internal_test"
MAX_STEP_RETRIES = 2
MAX_WORKFLOW_RETRIES = 6
MAX_INTERNAL_STEPS = 3


def next_status(current: str, action: str) -> str | None:
    current = (current or "").strip().lower()
    action = (action or "").strip().lower()
    if action == "approve" and current in APPROVE_FROM:
        return "waiting"
    if action == "cancel" and current in OPEN_STATUSES:
        return "cancelled"
    if action == "pause" and current in PAUSE_FROM:
        return "paused"
    if action == "resume" and current in RESUME_FROM:
        return "waiting"
    if action == "retry" and current in RETRY_FROM:
        return "waiting"
    if action == "step_approve" and current in STEP_APPROVE_FROM:
        return "completed"
    if action == "emergency_stop" and current in OPEN_STATUSES:
        return "cancelled"
    return None
