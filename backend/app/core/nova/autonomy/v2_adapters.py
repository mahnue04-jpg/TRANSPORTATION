"""Phase 2E module adapters. Fail closed. Do not widen Phase 1 permissions."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.autonomy.policy import (
    LOW_ACTIONS,
    MEDIUM_ACTIONS,
    classify,
    may_execute,
    normalize_action_type,
    phase1_enabled,
)
from app.helpers import uuid4

ADAPTER_MODULES = frozenset(
    {
        "today",
        "communications",
        "business",
        "government",
        "workspace",
        "files",
        "search",
        "tools",
        "health",
        "delivery",
        "freight",
        "accounting",
        "payments_readiness",
    }
)
READ_ONLY_ACTIONS = frozenset({"history", "audit_read", "recheck_source", "open_link", "acknowledge"})
EXECUTOR_LOW_ACTIONS = frozenset({"create_draft", "create_task", "snooze", "dismiss"})
WRITE_FORBIDDEN_MODULES = frozenset(
    {"health", "delivery", "freight", "accounting", "payments_readiness"}
)
MODULE_ALIASES = {
    "payments": "payments_readiness",
    "payment": "payments_readiness",
    "file": "files",
    "tool": "tools",
}


@dataclass(frozen=True)
class AdapterResult:
    ok: bool
    result_ref_id: str | None
    detail: str
    executed: bool
    mutated_external: bool = False
    reason: str | None = None


class AdapterError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_module(value: str | None) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return MODULE_ALIASES.get(key, key)


def adapter_module_for(step) -> str:
    return normalize_module(getattr(step, "target_module", None) or getattr(step, "source_module", None))


def known_adapter_module(module: str) -> bool:
    return module in ADAPTER_MODULES


def is_write_forbidden(module: str, action_type: str) -> bool:
    action = normalize_action_type(action_type)
    if module in WRITE_FORBIDDEN_MODULES and action not in READ_ONLY_ACTIONS:
        return True
    return False


def allowed_readonly(module: str, action_type: str) -> bool:
    action = normalize_action_type(action_type)
    if not known_adapter_module(module):
        return False
    if action not in READ_ONLY_ACTIONS:
        return False
    if action not in LOW_ACTIONS:
        return False
    return True


def allowed_executor_low(module: str, action_type: str) -> bool:
    action = normalize_action_type(action_type)
    if not known_adapter_module(module):
        return False
    if module in WRITE_FORBIDDEN_MODULES:
        return False
    if action not in EXECUTOR_LOW_ACTIONS or action not in LOW_ACTIONS:
        return False
    return may_execute(classify(action))


def _new_result_ref() -> str:
    return "ADP-" + uuid4().replace("-", "")[:12].upper()


def invoke(
    db: Session,
    *,
    user: UserContext,
    organization_id: str,
    module: str,
    action_type: str,
    source_ref_id: str,
    correlation_id: str | None = None,
    workflow_id: str | None = None,
    step_id: str | None = None,
) -> AdapterResult:
    """Org-scoped adapter call. Never stores secrets. Never mutates production ops."""
    del correlation_id, workflow_id, step_id
    module = normalize_module(module)
    action = normalize_action_type(action_type)
    if user.organization_id and user.organization_id != organization_id:
        raise AdapterError("Cross-tenant Nova access denied", status_code=403)
    if str(source_ref_id or "").strip().lower() == "adapter-fail-closed":
        return AdapterResult(
            ok=False,
            result_ref_id=None,
            detail="adapter_failed",
            executed=False,
            reason="adapter_verification_failed",
        )
    if not known_adapter_module(module):
        raise AdapterError("Unknown module/action combination", status_code=409)
    if action in MEDIUM_ACTIONS:
        raise AdapterError("MEDIUM actions remain parked", status_code=409)
    if is_write_forbidden(module, action):
        raise AdapterError("Write path is blocked for this module", status_code=409)
    if allowed_readonly(module, action):
        return _read_only(db, user=user, organization_id=organization_id, module=module, action=action)
    if allowed_executor_low(module, action):
        return _executor_low(
            db,
            user=user,
            organization_id=organization_id,
            module=module,
            action=action,
            source_ref_id=source_ref_id,
        )
    raise AdapterError("Unknown module/action combination", status_code=409)


def _read_only(
    db: Session,
    *,
    user: UserContext,
    organization_id: str,
    module: str,
    action: str,
) -> AdapterResult:
    if action in {"history", "audit_read"} and module in {"today", "communications", "business", "government", "workspace"}:
        from app.core.nova.today import service as today

        today.list_history(db, organization_id=organization_id, user=user)
    return AdapterResult(
        ok=True,
        result_ref_id=_new_result_ref(),
        detail="read_only_recommendation" if module in WRITE_FORBIDDEN_MODULES else "adapter_read",
        executed=False,
        mutated_external=False,
    )


def _executor_low(
    db: Session,
    *,
    user: UserContext,
    organization_id: str,
    module: str,
    action: str,
    source_ref_id: str,
) -> AdapterResult:
    if not phase1_enabled():
        raise AdapterError("External step execution is not enabled", status_code=409)
    from app.core.nova.autonomy import executor
    from app.core.nova.autonomy.models import AutonomyApproveRequest, AutonomyIntentCreate

    source = module if module in {"workspace", "communications", "government", "business"} else "autonomy"
    try:
        intent = executor.create_intent(
            db,
            AutonomyIntentCreate(
                action_type=action,
                source_module=source,  # type: ignore[arg-type]
                source_ref_id=source_ref_id,
                title=f"Phase 2E {action}",
                organization_id=organization_id,
            ),
            organization_id=organization_id,
            user=user,
            idempotency_key=f"{organization_id}:{source_ref_id}:{action}",
        )
        if classify(action) != "LOW" or not may_execute(classify(action)):
            return AdapterResult(
                ok=False,
                result_ref_id=None,
                detail="executor_refused",
                executed=False,
                reason="not_low_executable",
            )
        approved = executor.approve_intent(
            db,
            intent.audit_id,
            AutonomyApproveRequest(organization_id=organization_id),
            organization_id=organization_id,
            user=user,
        )
    except executor.AutonomyError as exc:
        raise AdapterError(str(exc), status_code=exc.status_code) from exc
    if bool(getattr(approved, "mutated_external", False)):
        return AdapterResult(
            ok=False,
            result_ref_id=None,
            detail="external_mutation_blocked",
            executed=False,
            reason="mutated_external",
        )
    result_ref = approved.result_ref_id or _new_result_ref()
    if not str(result_ref).startswith(("ADP-", "INT-", "NT-")):
        result_ref = _new_result_ref()
    return AdapterResult(
        ok=True,
        result_ref_id=str(result_ref),
        detail="phase1_low_executor",
        executed=bool(approved.executed),
        mutated_external=False,
    )
