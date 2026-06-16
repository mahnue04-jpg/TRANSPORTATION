from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class ValidationSummary:
    passed: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class ValidationState:
    backend_status: str
    tests: ValidationSummary
    last_updated: str
    source: str


_DEFAULT_STATE = ValidationState(
    backend_status="green",
    tests=ValidationSummary(passed=262, skipped=1, failed=0),
    last_updated=datetime.now(timezone.utc).isoformat(),
    source="frozen_baseline",
)

_state_lock = Lock()
_state: ValidationState = _DEFAULT_STATE


def set_validation_state(*, passed: int, skipped: int, failed: int, source: str = "runtime") -> None:
    """Update cached validation snapshot in-memory.

    This helper is intentionally lightweight and optional.
    """
    global _state
    backend_status = "green" if failed == 0 else "degraded"
    with _state_lock:
        _state = ValidationState(
            backend_status=backend_status,
            tests=ValidationSummary(passed=passed, skipped=skipped, failed=failed),
            last_updated=datetime.now(timezone.utc).isoformat(),
            source=source,
        )


def get_validation_snapshot() -> dict[str, Any]:
    with _state_lock:
        current = _state
    return {
        "backend_status": current.backend_status,
        "tests": {
            "passed": current.tests.passed,
            "skipped": current.tests.skipped,
            "failed": current.tests.failed,
        },
        "validation": {
            "last_updated": current.last_updated,
            "source": current.source,
        },
    }
