"""Central Work & Revenue live-action configuration.

Missing, empty, or malformed environment variables are OFF.
A capability cannot turn on unless the master allow switch is also explicitly true.
Production additionally requires an explicit owner override token. Even then, live
adapters are unimplemented, so the safety policy still blocks execution.
"""
from __future__ import annotations

import os
from typing import Any

from app.runtime_contract import _resolve_runtime_environment

CAPABILITIES = (
    "LIVE_DISCOVERY",
    "EXTERNAL_SUBMISSION",
    "CLIENT_CONTACT",
    "REPORT_SEND",
    "INVOICE_SEND",
    "FINANCIAL_EXECUTION",
    "CALENDAR_ACTIONS",
    "NOTIFICATIONS",
)

_TRUE = {"1", "true", "yes", "on"}
_MASTER_ENV = "NOVA_WR_ALLOW_LIVE_ACTIONS"
_PRODUCTION_OVERRIDE_ENV = "NOVA_WR_PRODUCTION_LIVE_OVERRIDE"
_PRODUCTION_OVERRIDE_VALUE = "OWNER_AUTHORIZED_PRODUCTION_LIVE"
_CAPABILITY_ENV = {
    "LIVE_DISCOVERY": "NOVA_WR_LIVE_DISCOVERY",
    "EXTERNAL_SUBMISSION": "NOVA_WR_EXTERNAL_SUBMISSION",
    "CLIENT_CONTACT": "NOVA_WR_CLIENT_CONTACT",
    "REPORT_SEND": "NOVA_WR_REPORT_SEND",
    "INVOICE_SEND": "NOVA_WR_INVOICE_SEND",
    "FINANCIAL_EXECUTION": "NOVA_WR_FINANCIAL_EXECUTION",
    "CALENDAR_ACTIONS": "NOVA_WR_CALENDAR_ACTIONS",
    "NOTIFICATIONS": "NOVA_WR_NOTIFICATIONS",
}

# Conservative mapping: V1 boolean names stay available through engine_guardrails().
V1_FLAG_NAMES = {
    "LIVE_DISCOVERY_ENABLED": "LIVE_DISCOVERY",
    "EXTERNAL_SUBMISSION_ENABLED": "EXTERNAL_SUBMISSION",
    "AUTONOMOUS_CLIENT_CONTACT_ENABLED": "CLIENT_CONTACT",
    "REPORT_SEND_ENABLED": "REPORT_SEND",
    "INVOICE_SEND_ENABLED": "INVOICE_SEND",
    "FINANCIAL_ACTIONS_ENABLED": "FINANCIAL_EXECUTION",
    "CALENDAR_ACTIONS_ENABLED": "CALENDAR_ACTIONS",
    "NOTIFICATIONS_ENABLED": "NOTIFICATIONS",
}


def _env_true(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in _TRUE


def runtime_environment() -> str:
    return str(_resolve_runtime_environment() or "").strip().lower() or "development"


def is_production_runtime() -> bool:
    return runtime_environment() in {"production", "prod"}


def master_live_actions_allowed() -> bool:
    return _env_true(_MASTER_ENV)


def production_live_override_present() -> bool:
    raw = (os.getenv(_PRODUCTION_OVERRIDE_ENV) or "").strip()
    return raw == _PRODUCTION_OVERRIDE_VALUE


def capability_env_name(capability: str) -> str:
    key = str(capability or "").strip().upper()
    return _CAPABILITY_ENV.get(key, f"NOVA_WR_{key}")


def is_capability_enabled(capability: str) -> bool:
    """Return True only when every conservative switch is explicitly on."""
    key = str(capability or "").strip().upper()
    if key not in CAPABILITIES:
        return False
    if not master_live_actions_allowed():
        return False
    if not _env_true(capability_env_name(key)):
        return False
    if is_production_runtime() and not production_live_override_present():
        return False
    return True


def capability_status(capability: str | None = None) -> dict[str, Any]:
    keys = (str(capability).strip().upper(),) if capability else CAPABILITIES
    rows: dict[str, Any] = {}
    for key in keys:
        if key not in CAPABILITIES:
            continue
        env_name = capability_env_name(key)
        rows[key] = {
            "capability": key,
            "enabled": is_capability_enabled(key),
            "env_var": env_name,
            "env_present": os.getenv(env_name) is not None,
            "master_allow": master_live_actions_allowed(),
            "production": is_production_runtime(),
            "production_override": production_live_override_present() if is_production_runtime() else None,
            "default": False,
            "live_adapter_implemented": False,
            "secrets_exposed": False,
        }
    return rows if capability else rows


def capabilities_surface() -> dict[str, Any]:
    status = capability_status()
    return {
        "version": "v2",
        "runtime_environment": runtime_environment(),
        "production": is_production_runtime(),
        "master_live_actions_allowed": master_live_actions_allowed(),
        "missing_env_means_off": True,
        "live_execution_implemented": False,
        "secrets_exposed": False,
        "background_worker": False,
        "live_connectors": False,
        "capabilities": status,
        "enabled": {key: bool(row["enabled"]) for key, row in status.items()},
        "live_disabled": {
            "LIVE_DISCOVERY": False,
            "EXTERNAL_SUBMISSION": False,
            "CLIENT_CONTACT": False,
            "REPORT_SEND": False,
            "INVOICE_SEND": False,
            "FINANCIAL_EXECUTION": False,
            "BACKGROUND_WORKER": False,
            "LIVE_CONNECTORS": False,
        },
        "core_readiness": {
            "qualification": True,
            "owner_review": True,
            "preparation": True,
            "manual_submission_recording": True,
            "engagement_tracking": True,
            "deliverables": True,
            "invoice_support": True,
            "revenue_tracking": True,
            "partial_payments": True,
            "scheduler_preparation": True,
            "audit_logging": True,
            "tenant_isolation": True,
            "approval_lifecycle": True,
            "idempotency": True,
            "migration_readiness": True,
            "monitoring_readiness": True,
            "canonical_alembic_production": True,
            "lazy_v2_schema_in_production": False,
        },
        "semantic_guards": {
            "APPROVED_EQUALS_SUBMITTED": False,
            "APPROVED_EQUALS_PAID": False,
            "COMPLETE_EQUALS_PAID": False,
            "OWNER_APPROVAL_REQUIRED": True,
            "APPROVAL_EQUALS_EXECUTION": False,
        },
    }
