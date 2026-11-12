"""Typed errors for Growth Agent APIs."""

from __future__ import annotations


class GrowthAgentError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def as_dict(self) -> dict:
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class TenantRequiredError(GrowthAgentError):
    def __init__(self, message: str = "Organization scope is required") -> None:
        super().__init__("TENANT_REQUIRED", message, http_status=403)


class CrossTenantError(GrowthAgentError):
    def __init__(self, message: str = "Cross-tenant access denied") -> None:
        super().__init__("CROSS_TENANT_DENIED", message, http_status=403)


class FeatureDisabledError(GrowthAgentError):
    def __init__(self, message: str = "Growth Agent is disabled") -> None:
        super().__init__("GROWTH_AGENT_DISABLED", message, http_status=404)


class ConsentRequiredError(GrowthAgentError):
    def __init__(self, message: str = "Consent required before this action") -> None:
        super().__init__("CONSENT_REQUIRED", message, http_status=403)


class DoubleBookError(GrowthAgentError):
    def __init__(self, message: str = "Slot already booked") -> None:
        super().__init__("DOUBLE_BOOK", message, http_status=409)


class IdempotencyConflictError(GrowthAgentError):
    def __init__(self, message: str = "Idempotency key conflict") -> None:
        super().__init__("IDEMPOTENCY_CONFLICT", message, http_status=409)
