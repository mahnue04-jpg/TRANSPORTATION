"""Role helpers for driver onboarding permissions."""
from __future__ import annotations

from app.auth import (
    DEFAULT_ROLE,
    ROLE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_DRIVER_SUPPORT,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_SUPERVISOR,
    normalize_role,
    resolve_session_role,
)

REVIEW_ROLES = frozenset(
    {
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN_SUPPORT,
        ROLE_SUPERVISOR,
        ROLE_DISPATCHER,
        ROLE_DRIVER_SUPPORT,
        ROLE_COMPLIANCE_OFFICER,
    }
)

COMPLIANCE_ROLES = frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_COMPLIANCE_OFFICER, ROLE_SUPERVISOR})

APPROVAL_ROLES = frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_SUPERVISOR})

ACTIVATION_ROLES = frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_SUPERVISOR})


def user_role(user, token_payload: dict | None = None) -> str:
    if token_payload:
        return resolve_session_role(user, token_payload)
    session_role = getattr(user, "session_role", None) or getattr(user, "role", None)
    return normalize_role(session_role or DEFAULT_ROLE)


def can_review(user, token_payload: dict | None = None) -> bool:
    return user_role(user, token_payload) in REVIEW_ROLES


def can_view_compliance(user, token_payload: dict | None = None) -> bool:
    return user_role(user, token_payload) in COMPLIANCE_ROLES


def can_approve(user, token_payload: dict | None = None) -> bool:
    return user_role(user, token_payload) in APPROVAL_ROLES


def can_activate(user, token_payload: dict | None = None) -> bool:
    return user_role(user, token_payload) in ACTIVATION_ROLES


def is_driver_role(user, token_payload: dict | None = None) -> bool:
    return user_role(user, token_payload) == ROLE_DRIVER
