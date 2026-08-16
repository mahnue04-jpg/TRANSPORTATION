"""Durable AI Approval Engine workflow statuses and transitions."""
from __future__ import annotations

WORKFLOW_STATUSES = frozenset(
    {
        "PENDING",
        "AI_REVIEW",
        "ACTION_REQUIRED",
        "EXTERNAL_VERIFICATION",
        "READY_FOR_APPROVAL",
        "OWNER_APPROVED",
        "APPROVED",
        "ACTIVE",
        "FLAGGED",
        "RESTRICTED",
        "SUSPENDED",
        "CORRECTIVE_ACTION",
        "REAPPROVAL_REQUIRED",
        "REJECTED",
        "EXPIRED",
    }
)

# Deterministic transitions. ACTIVE is never reachable without passing activation gates
# in workflow.py (requirements + owner approval), not merely by listing it here.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"AI_REVIEW", "REJECTED"}),
    "AI_REVIEW": frozenset(
        {
            "ACTION_REQUIRED",
            "EXTERNAL_VERIFICATION",
            "READY_FOR_APPROVAL",
            "FLAGGED",
            "REJECTED",
        }
    ),
    "ACTION_REQUIRED": frozenset(
        {
            "AI_REVIEW",
            "EXTERNAL_VERIFICATION",
            "READY_FOR_APPROVAL",
            "FLAGGED",
            "REJECTED",
            "EXPIRED",
        }
    ),
    "EXTERNAL_VERIFICATION": frozenset(
        {
            "AI_REVIEW",
            "ACTION_REQUIRED",
            "READY_FOR_APPROVAL",
            "FLAGGED",
            "REJECTED",
            "EXPIRED",
        }
    ),
    "READY_FOR_APPROVAL": frozenset(
        {
            "OWNER_APPROVED",
            "ACTION_REQUIRED",
            "EXTERNAL_VERIFICATION",
            "REJECTED",
            "CORRECTIVE_ACTION",
            "FLAGGED",
        }
    ),
    "OWNER_APPROVED": frozenset({"APPROVED", "ACTION_REQUIRED", "RESTRICTED", "REJECTED"}),
    "APPROVED": frozenset({"ACTIVE", "RESTRICTED", "SUSPENDED", "REAPPROVAL_REQUIRED", "EXPIRED"}),
    "ACTIVE": frozenset(
        {
            "RESTRICTED",
            "SUSPENDED",
            "CORRECTIVE_ACTION",
            "REAPPROVAL_REQUIRED",
            "EXPIRED",
            "FLAGGED",
        }
    ),
    "FLAGGED": frozenset(
        {
            "AI_REVIEW",
            "ACTION_REQUIRED",
            "EXTERNAL_VERIFICATION",
            "READY_FOR_APPROVAL",
            "RESTRICTED",
            "SUSPENDED",
            "REJECTED",
        }
    ),
    "RESTRICTED": frozenset(
        {
            "CORRECTIVE_ACTION",
            "REAPPROVAL_REQUIRED",
            "ACTIVE",
            "SUSPENDED",
            "EXPIRED",
            "AI_REVIEW",
        }
    ),
    "SUSPENDED": frozenset(
        {
            "CORRECTIVE_ACTION",
            "REAPPROVAL_REQUIRED",
            "AI_REVIEW",
            "REJECTED",
            "EXPIRED",
        }
    ),
    "CORRECTIVE_ACTION": frozenset(
        {
            "AI_REVIEW",
            "ACTION_REQUIRED",
            "EXTERNAL_VERIFICATION",
            "READY_FOR_APPROVAL",
            "REAPPROVAL_REQUIRED",
            "RESTRICTED",
            "SUSPENDED",
        }
    ),
    "REAPPROVAL_REQUIRED": frozenset(
        {
            "AI_REVIEW",
            "READY_FOR_APPROVAL",
            "OWNER_APPROVED",
            "RESTRICTED",
            "SUSPENDED",
            "REJECTED",
        }
    ),
    "REJECTED": frozenset(),
    "EXPIRED": frozenset({"REAPPROVAL_REQUIRED", "AI_REVIEW", "REJECTED"}),
}

TERMINAL_STATUSES = frozenset({"REJECTED"})

FINGERPRINT_STATUSES = frozenset(
    {"NOT_REQUIRED", "PENDING", "REQUIRED", "COMPLETE", "FAILED"}
)

REQUIREMENT_TIMING = frozenset(
    {
        "required_now",
        "required_before_activation",
        "conditional",
        "future_requirement",
        "not_required",
    }
)

REQUIREMENT_TRAFFIC = frozenset({"green", "yellow", "red"})

SERVICE_TIERS = frozenset(
    {
        "BASE_PRIVATE_AMBULATORY",
        "STS_ELIGIBLE",
        "FUTURE_MHCP_NEMT",
    }
)

TRAINING_STATUSES = frozenset(
    {"assigned", "in_progress", "completed", "failed", "expired", "retraining_required"}
)

ACTOR_TYPES = frozenset({"AI", "USER", "SYSTEM", "EXTERNAL"})

EXTERNAL_VERIFICATION_STATUSES = frozenset(
    {
        "NOT_STARTED",
        "ACTION_REQUIRED",
        "SUBMITTED",
        "PENDING_EXTERNAL",
        "VERIFIED",
        "FAILED",
        "EXPIRED",
        "MANUAL_REVIEW",
    }
)


def normalize_status(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized not in WORKFLOW_STATUSES:
        raise ValueError(f"Invalid approval workflow status: {status}")
    return normalized


def assert_transition_allowed(from_status: str, to_status: str) -> None:
    source = normalize_status(from_status)
    target = normalize_status(to_status)
    if target not in ALLOWED_TRANSITIONS.get(source, frozenset()):
        raise ValueError(f"Approval workflow transition not allowed: {source} -> {target}")


def list_allowed_next_statuses(from_status: str) -> list[str]:
    return sorted(ALLOWED_TRANSITIONS.get(normalize_status(from_status), frozenset()))
