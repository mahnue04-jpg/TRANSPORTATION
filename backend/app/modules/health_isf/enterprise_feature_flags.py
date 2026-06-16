"""Backend-governed enterprise feature flags for autonomous intelligence systems."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    normalize_role,
)


@dataclass(frozen=True)
class FeatureGate:
    name: str
    enabled: bool
    allowed_roles: frozenset[str]


_ENV_MAP = {
    "AI_AUTONOMOUS_MODE": "AMICOR_AI_AUTONOMOUS_MODE",
    "AI_PREDICTIVE_OPERATIONS": "AMICOR_AI_PREDICTIVE_OPERATIONS",
    "AI_AUTO_ESCALATION": "AMICOR_AI_AUTO_ESCALATION",
    "AI_INCIDENT_AUTORECOVERY": "AMICOR_AI_INCIDENT_AUTORECOVERY",
    "AI_MULTI_AGENT_RUNTIME": "AMICOR_AI_MULTI_AGENT_RUNTIME",
    "ENABLE_AI_REASONING": "AMICOR_ENABLE_AI_REASONING",
    "ENABLE_AI_PREDICTIONS": "AMICOR_ENABLE_AI_PREDICTIONS",
    "ENABLE_AI_MEMORY": "AMICOR_ENABLE_AI_MEMORY",
    "ENABLE_AUTONOMOUS_ACTIONS": "AMICOR_ENABLE_AUTONOMOUS_ACTIONS",
}


def _is_enabled(flag_name: str, default: bool = False) -> bool:
    env_name = _ENV_MAP.get(flag_name, flag_name)
    value = os.getenv(env_name, "1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_feature_gate(flag_name: str) -> FeatureGate:
    role_defaults = {
        "AI_AUTONOMOUS_MODE": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER}),
        "AI_PREDICTIVE_OPERATIONS": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER, ROLE_ANALYTICS_READONLY}),
        "AI_AUTO_ESCALATION": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER}),
        "AI_INCIDENT_AUTORECOVERY": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER}),
        "AI_MULTI_AGENT_RUNTIME": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER, ROLE_STAFF}),
        "ENABLE_AI_REASONING": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER, ROLE_STAFF, ROLE_ANALYTICS_READONLY}),
        "ENABLE_AI_PREDICTIONS": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER, ROLE_ANALYTICS_READONLY}),
        "ENABLE_AI_MEMORY": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER, ROLE_STAFF, ROLE_ANALYTICS_READONLY}),
        "ENABLE_AUTONOMOUS_ACTIONS": frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER}),
    }
    return FeatureGate(
        name=flag_name,
        enabled=_is_enabled(flag_name, default=False),
        allowed_roles=role_defaults.get(flag_name, frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT})),
    )


def is_feature_enabled(flag_name: str, role: str | None = None) -> bool:
    gate = get_feature_gate(flag_name)
    if not gate.enabled:
        return False
    if role is None:
        return True
    return normalize_role(role) in gate.allowed_roles


def get_feature_snapshot(role: str | None = None) -> dict[str, bool]:
    return {
        name: is_feature_enabled(name, role=role)
        for name in _ENV_MAP
    }
