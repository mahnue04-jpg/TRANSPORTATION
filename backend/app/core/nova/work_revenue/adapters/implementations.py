"""Disabled, dry-run, and test-only mock adapters. No live side effects."""
from __future__ import annotations

from app.core.nova.work_revenue.adapters.contracts import (
    AdapterRequest,
    AdapterResult,
    WorkAdapter,
    _base_result,
    validate_request,
)


class DisabledAdapter:
    mode = "disabled"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def available(self) -> bool:
        return False

    def validate(self, request: AdapterRequest) -> AdapterResult:
        error = validate_request(self.kind, request)
        if error:
            return _base_result(self.kind, self.mode, request, status="INVALID", message=error)
        return _base_result(
            self.kind,
            self.mode,
            request,
            status="DISABLED",
            message="Adapter is disabled. Nothing was sent, charged, or submitted.",
        )

    def execute(self, request: AdapterRequest) -> AdapterResult:
        return self.validate(request)


class UnavailableAdapter:
    mode = "unavailable"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def available(self) -> bool:
        return False

    def validate(self, request: AdapterRequest) -> AdapterResult:
        error = validate_request(self.kind, request)
        if error:
            return _base_result(self.kind, self.mode, request, status="INVALID", message=error)
        return _base_result(
            self.kind,
            self.mode,
            request,
            status="UNAVAILABLE",
            message="Adapter is unavailable. No live connector is configured.",
        )

    def execute(self, request: AdapterRequest) -> AdapterResult:
        return self.validate(request)


class DryRunAdapter:
    mode = "dry_run"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def available(self) -> bool:
        return True

    def validate(self, request: AdapterRequest) -> AdapterResult:
        error = validate_request(self.kind, request)
        if error:
            return _base_result(self.kind, self.mode, request, status="INVALID", message=error)
        if not request.owner_approved:
            return _base_result(
                self.kind,
                self.mode,
                request,
                status="OWNER_AUTHORIZATION_REQUIRED",
                message="Owner approval is required before a dry-run can be recorded.",
            )
        return _base_result(
            self.kind,
            self.mode,
            request,
            status="VALID",
            message="Dry-run validation passed. Nothing was sent.",
            ok=True,
        )

    def execute(self, request: AdapterRequest) -> AdapterResult:
        checked = self.validate(request)
        if not checked.ok:
            return checked
        result = _base_result(
            self.kind,
            self.mode,
            request,
            status="DRY_RUN",
            message="Dry-run recorded. No external side effects.",
            ok=True,
        )
        return AdapterResult(
            ok=True,
            mode=self.mode,
            kind=self.kind,
            status="DRY_RUN",
            message=result.message,
            idempotency_key=request.idempotency_key,
            executed=False,
            details={**result.details, "dry_run": True},
            timeout_seconds=result.timeout_seconds,
            retry_limit=result.retry_limit,
            secrets_exposed=False,
        )


class MockAdapter:
    """Local/test adapter only. Never performs network or financial work."""

    mode = "mock"

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._seen: set[str] = set()

    def available(self) -> bool:
        return True

    def validate(self, request: AdapterRequest) -> AdapterResult:
        error = validate_request(self.kind, request)
        if error:
            return _base_result(self.kind, self.mode, request, status="INVALID", message=error)
        return _base_result(
            self.kind,
            self.mode,
            request,
            status="VALID",
            message="Mock adapter validation passed. Test-only. No live connector.",
            ok=True,
        )

    def execute(self, request: AdapterRequest) -> AdapterResult:
        checked = self.validate(request)
        if not checked.ok:
            return checked
        duplicate = request.idempotency_key in self._seen
        self._seen.add(request.idempotency_key)
        return AdapterResult(
            ok=True,
            mode=self.mode,
            kind=self.kind,
            status="MOCK_RECORDED" if not duplicate else "DUPLICATE",
            message="Mock adapter recorded a local result. No external call was made.",
            idempotency_key=request.idempotency_key,
            executed=False,
            duplicate=duplicate,
            details={"mock": True, "dry_run": True, "external_target": request.external_target},
            timeout_seconds=checked.timeout_seconds,
            retry_limit=checked.retry_limit,
            secrets_exposed=False,
        )


def disabled_adapter(kind: str) -> WorkAdapter:
    return DisabledAdapter(kind)


def dry_run_adapter(kind: str) -> WorkAdapter:
    return DryRunAdapter(kind)


def mock_adapter(kind: str) -> WorkAdapter:
    return MockAdapter(kind)
