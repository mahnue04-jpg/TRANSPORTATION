"""Deterministic Autonomy Phase 1 policy. Overrides model confidence and retries."""
from __future__ import annotations

import os
from typing import Literal

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role

RiskClass = Literal["LOW", "MEDIUM", "HIGH", "PROHIBITED"]
ApprovalState = Literal[
    "proposed",
    "awaiting_approval",
    "approved",
    "blocked",
    "rejected",
    "completed",
]

LOW_ACTIONS = frozenset(
    {
        "create_draft",
        "create_task",
        "acknowledge",
        "recheck_source",
        "open_link",
        "snooze",
        "dismiss",
        "history",
        "audit_read",
    }
)
MEDIUM_ACTIONS = frozenset(
    {
        "send_email",
        "email_send",
        "submit_form",
        "form_submission",
        "update_record",
        "internal_record_update",
    }
)
HIGH_ACTIONS = frozenset(
    {
        "send_money",
        "billing",
        "refund",
        "refunds",
        "payout",
        "payouts",
        "stripe",
        "stripe_execute",
        "contract",
        "contracts",
        "legal_filing",
        "legal_filings",
        "ride_cancel",
        "ride_cancellation",
        "compliance_submit",
        "compliance_sensitive",
        "health_action",
        "safety_action",
        "payroll",
        "tax",
        "ledger_execute",
        "live_key",
        "driver_action",
        "payment_action",
    }
)
PROHIBITED_ACTIONS = frozenset(
    {
        "silent_send",
        "silent_file",
        "hidden_delete",
        "destructive_delete",
        "delete",
        "autonomous_send",
        "government_filing",
        "file_government",
        "driver_001",
        "health_write",
        "delivery_write",
        "freight_write",
        "private_pay",
        "private_pay_write",
    }
)

_TRUE = {"1", "true", "on", "yes"}


def phase1_enabled() -> bool:
    return os.getenv("NOVA_AUTONOMY_PHASE1", "").strip().lower() in _TRUE


def normalize_action_type(action_type: str | None) -> str:
    return str(action_type or "").strip().lower().replace("-", "_").replace(" ", "_")


def classify(action_type: str | None, **_ignored: object) -> RiskClass:
    """Risk class is deterministic. Extra kwargs (confidence, retries) are ignored."""
    key = normalize_action_type(action_type)
    if key in LOW_ACTIONS:
        return "LOW"
    if key in MEDIUM_ACTIONS:
        return "MEDIUM"
    if key in HIGH_ACTIONS:
        return "HIGH"
    return "PROHIBITED"


def may_execute(risk_class: RiskClass) -> bool:
    return risk_class == "LOW"


def is_blocked(risk_class: RiskClass) -> bool:
    return risk_class in {"HIGH", "PROHIBITED"}


def can_act(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}


def execution_state_for(status: str | None, *, executed: bool = False) -> str:
    if executed:
        return "executed"
    if status in {"done", "approved"}:
        return "executed"
    if status in {"snoozed", "dismissed"}:
        return "executed"
    if status == "blocked":
        return "blocked"
    return "not_executed"


def approval_state_for(risk_class: RiskClass, status: str | None = None) -> ApprovalState:
    if is_blocked(risk_class):
        return "blocked"
    if status in {"done", "approved", "snoozed", "dismissed"}:
        return "completed"
    if risk_class == "MEDIUM":
        return "awaiting_approval"
    return "awaiting_approval"


def labels_for(action_type: str | None, status: str | None = None, *, executed: bool = False) -> dict[str, str]:
    risk = classify(action_type)
    return {
        "risk_class": risk,
        "approval_state": approval_state_for(risk, status),
        "execution_state": execution_state_for(status, executed=executed),
    }
