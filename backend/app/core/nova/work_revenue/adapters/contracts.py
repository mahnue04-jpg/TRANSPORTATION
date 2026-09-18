"""Work & Revenue adapter contracts. No real third-party connections."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


ADAPTER_KINDS = (
    "opportunity_discovery",
    "external_submission",
    "email_client_communication",
    "report_delivery",
    "invoice_delivery",
    "calendar",
    "notification",
    "payment_processor",
)

KIND_TO_CAPABILITY = {
    "opportunity_discovery": "LIVE_DISCOVERY",
    "external_submission": "EXTERNAL_SUBMISSION",
    "email_client_communication": "CLIENT_CONTACT",
    "report_delivery": "REPORT_SEND",
    "invoice_delivery": "INVOICE_SEND",
    "calendar": "CALENDAR_ACTIONS",
    "notification": "NOTIFICATIONS",
    "payment_processor": "FINANCIAL_EXECUTION",
}

MODES = ("disabled", "unavailable", "dry_run", "mock")


@dataclass(frozen=True)
class AdapterRequest:
    organization_id: str
    owner_user_id: str
    action_type: str
    idempotency_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    owner_approved: bool = False
    dry_run: bool = True
    timeout_seconds: int = 8
    retry_limit: int = 0
    timezone: str = "America/Chicago"
    external_target: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    ok: bool
    mode: str
    kind: str
    status: str
    message: str
    idempotency_key: str
    executed: bool = False
    duplicate: bool = False
    retryable: bool = False
    timeout_seconds: int = 8
    retry_limit: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    secrets_exposed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "kind": self.kind,
            "status": self.status,
            "message": self.message,
            "idempotency_key": self.idempotency_key,
            "executed": self.executed,
            "duplicate": self.duplicate,
            "retryable": self.retryable,
            "timeout_seconds": self.timeout_seconds,
            "retry_limit": self.retry_limit,
            "details": dict(self.details),
            "secrets_exposed": False,
        }


class WorkAdapter(Protocol):
    kind: str
    mode: str

    def available(self) -> bool: ...
    def validate(self, request: AdapterRequest) -> AdapterResult: ...
    def execute(self, request: AdapterRequest) -> AdapterResult: ...


def _base_result(kind: str, mode: str, request: AdapterRequest, *, status: str, message: str, ok: bool = False) -> AdapterResult:
    return AdapterResult(
        ok=ok,
        mode=mode,
        kind=kind,
        status=status,
        message=message,
        idempotency_key=request.idempotency_key,
        executed=False,
        timeout_seconds=max(1, min(int(request.timeout_seconds or 8), 15)),
        retry_limit=max(0, min(int(request.retry_limit or 0), 2)),
        details={"external_target": request.external_target, "timezone": request.timezone},
        secrets_exposed=False,
    )


def validate_request(kind: str, request: AdapterRequest) -> str | None:
    if not request.organization_id or not request.owner_user_id:
        return "organization and owner are required"
    if not request.idempotency_key or len(request.idempotency_key) > 120:
        return "idempotency_key is required and must be <= 120 characters"
    if kind not in ADAPTER_KINDS:
        return "unknown adapter kind"
    if not request.action_type:
        return "action_type is required"
    return None
