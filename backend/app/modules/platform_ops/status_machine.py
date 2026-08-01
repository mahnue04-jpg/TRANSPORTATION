"""Controlled status transitions for driver onboarding applications."""
from __future__ import annotations

from typing import Iterable

from app.modules.platform_ops.models import APPLICATION_STATUSES

TERMINAL_STATUSES = frozenset({"rejected"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted"}),
    "submitted": frozenset({"under_review", "rejected"}),
    "under_review": frozenset({"documents_pending", "background_review", "approved", "rejected", "suspended"}),
    "documents_pending": frozenset({"under_review", "background_review", "rejected"}),
    "background_review": frozenset({"approved", "rejected", "documents_pending"}),
    "approved": frozenset({"activated", "rejected", "suspended"}),
    "rejected": frozenset(),
    "suspended": frozenset({"under_review"}),
    "activated": frozenset({"suspended"}),
}

APPROVAL_SOURCE_STATUSES = frozenset({"under_review", "background_review", "documents_pending"})
ACTIVATION_SOURCE_STATUSES = frozenset({"approved"})


def normalize_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in APPLICATION_STATUSES:
        raise ValueError(f"Invalid application status: {status}")
    return normalized


def assert_transition_allowed(from_status: str, to_status: str) -> None:
    source = normalize_status(from_status)
    target = normalize_status(to_status)
    allowed = ALLOWED_TRANSITIONS.get(source, frozenset())
    if target not in allowed:
        raise ValueError(f"Status transition not allowed: {source} -> {target}")


def list_allowed_next_statuses(from_status: str) -> list[str]:
    source = normalize_status(from_status)
    return sorted(ALLOWED_TRANSITIONS.get(source, frozenset()))


def statuses_requiring_confirmation() -> Iterable[str]:
    return ("rejected", "suspended", "approved", "activated")
