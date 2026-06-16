"""Governance registry constants and replay-safe helpers for enterprise AI control."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
)

GOVERNANCE_AUDIT_PREFIX = "ai.governance."
GOVERNANCE_APPROVAL_EVENT = "ai.governance.approval_recorded"
GOVERNANCE_PROPOSAL_EVENT = "ai.governance.proposal_recorded"
GOVERNANCE_EXECUTION_EVENT = "ai.governance.execution_policy_checked"
GOVERNANCE_REASONING_EVENT = "ai.governance.reasoning_registered"
GOVERNANCE_PREDICTION_EVENT = "ai.governance.prediction_registered"
GOVERNANCE_TIMELINE_EVENT = "ai.governance.timeline_reconstructed"
GOVERNANCE_CORRELATION_EVENT = "ai.governance.correlation_reconstructed"

DEFAULT_CONFIDENCE_THRESHOLD = 0.65
DEFAULT_APPROVAL_EXPIRATION_MINUTES = 30
DEFAULT_GOVERNANCE_ROLES = frozenset(
    {
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN_SUPPORT,
        ROLE_DISPATCHER,
        ROLE_STAFF,
        ROLE_ANALYTICS_READONLY,
    }
)
EXECUTION_ROLES = frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER})
APPROVAL_ROLES = frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER})
REVIEW_ROLES = frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER, ROLE_STAFF, ROLE_ANALYTICS_READONLY})


@dataclass(frozen=True)
class GovernancePolicy:
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    approval_expiration_minutes: int = DEFAULT_APPROVAL_EXPIRATION_MINUTES
    approval_required: bool = True
    rollback_required: bool = True
    tenant_scoped: bool = True
    append_only_audit: bool = True


GOVERNANCE_POLICY = GovernancePolicy()
