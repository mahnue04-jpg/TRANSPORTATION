"""Single production safety policy for Work & Revenue live actions.

Every live action is blocked unless ALL required conditions are true.
Tonight no live adapter is implemented, so execution cannot succeed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.nova.work_revenue.config import (
    CAPABILITIES,
    is_capability_enabled,
    is_production_runtime,
    runtime_environment,
)

REQUIRED_CONDITIONS = (
    "capability_enabled",
    "correct_environment",
    "tenant_authorized",
    "owner_approved",
    "adapter_implemented",
    "required_facts_available",
    "terms_policy_satisfied",
    "not_duplicated",
)

LIVE_ACTION_TYPES = {
    "LIVE_DISCOVERY": "LIVE_DISCOVERY",
    "EXTERNAL_SUBMISSION": "EXTERNAL_SUBMISSION",
    "CLIENT_CONTACT": "CLIENT_CONTACT",
    "REPORT_SEND": "REPORT_SEND",
    "INVOICE_SEND": "INVOICE_SEND",
    "FINANCIAL_EXECUTION": "FINANCIAL_EXECUTION",
    "CALENDAR_ACTIONS": "CALENDAR_ACTIONS",
    "NOTIFICATIONS": "NOTIFICATIONS",
}

# Conservative: live execution is never the correct environment in V2 core,
# even if a capability flag is flipped. Dry-run / prepare / audit are allowed.
LIVE_EXECUTION_ENVIRONMENTS: set[str] = set()


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    action_type: str
    reason: str
    blocked_reasons: tuple[str, ...] = ()
    conditions: dict[str, bool] = field(default_factory=dict)
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action_type": self.action_type,
            "reason": self.reason,
            "blocked_reasons": list(self.blocked_reasons),
            "conditions": dict(self.conditions),
            "dry_run": self.dry_run,
            "production": is_production_runtime(),
            "runtime_environment": runtime_environment(),
        }


def _condition_map(
    *,
    capability: str,
    tenant_authorized: bool,
    owner_approved: bool,
    adapter_implemented: bool,
    required_facts_available: bool,
    terms_policy_satisfied: bool,
    not_duplicated: bool,
    dry_run: bool,
) -> dict[str, bool]:
    capability_on = is_capability_enabled(capability)
    env_ok = (not dry_run) and (runtime_environment() in LIVE_EXECUTION_ENVIRONMENTS)
    return {
        "capability_enabled": capability_on,
        "correct_environment": env_ok,
        "tenant_authorized": bool(tenant_authorized),
        "owner_approved": bool(owner_approved),
        "adapter_implemented": bool(adapter_implemented),
        "required_facts_available": bool(required_facts_available),
        "terms_policy_satisfied": bool(terms_policy_satisfied),
        "not_duplicated": bool(not_duplicated),
    }


def evaluate_live_action(
    action_type: str,
    *,
    tenant_authorized: bool = False,
    owner_approved: bool = False,
    adapter_implemented: bool = False,
    required_facts_available: bool = False,
    terms_policy_satisfied: bool = False,
    not_duplicated: bool = True,
    dry_run: bool = False,
) -> SafetyDecision:
    capability = LIVE_ACTION_TYPES.get(str(action_type or "").strip().upper(), "")
    if capability not in CAPABILITIES:
        return SafetyDecision(
            allowed=False,
            action_type=str(action_type or ""),
            reason="Unknown live action type",
            blocked_reasons=("unknown_action_type",),
            conditions={name: False for name in REQUIRED_CONDITIONS},
            dry_run=dry_run,
        )
    conditions = _condition_map(
        capability=capability,
        tenant_authorized=tenant_authorized,
        owner_approved=owner_approved,
        adapter_implemented=adapter_implemented,
        required_facts_available=required_facts_available,
        terms_policy_satisfied=terms_policy_satisfied,
        not_duplicated=not_duplicated,
        dry_run=dry_run,
    )
    # Dry-run still cannot claim live adapter implementation or production execution.
    if dry_run:
        conditions["adapter_implemented"] = False
        conditions["correct_environment"] = False
        blocked = tuple(name for name, ok in conditions.items() if not ok)
        return SafetyDecision(
            allowed=False,
            action_type=capability,
            reason="Dry-run only. Live execution is disabled.",
            blocked_reasons=blocked or ("dry_run_not_live_execution",),
            conditions=conditions,
            dry_run=True,
        )
    blocked = tuple(name for name, ok in conditions.items() if not ok)
    if blocked:
        return SafetyDecision(
            allowed=False,
            action_type=capability,
            reason="Live action blocked: " + ", ".join(blocked),
            blocked_reasons=blocked,
            conditions=conditions,
            dry_run=False,
        )
    # Defense in depth: even a fully green map cannot execute in V2 core.
    return SafetyDecision(
        allowed=False,
        action_type=capability,
        reason="Live adapters are not implemented. Execution remains blocked.",
        blocked_reasons=("adapter_implemented", "correct_environment"),
        conditions={**conditions, "adapter_implemented": False, "correct_environment": False},
        dry_run=False,
    )


def require_live_action(action_type: str, **kwargs: Any) -> SafetyDecision:
    decision = evaluate_live_action(action_type, **kwargs)
    return decision
