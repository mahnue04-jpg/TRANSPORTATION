"""Adapter registry. Production default is disabled for every kind."""
from __future__ import annotations

from app.core.nova.work_revenue.adapters.contracts import ADAPTER_KINDS, KIND_TO_CAPABILITY, WorkAdapter
from app.core.nova.work_revenue.adapters.implementations import disabled_adapter, dry_run_adapter, mock_adapter
from app.core.nova.work_revenue.config import is_capability_enabled

_TEST_MOCKS: dict[str, WorkAdapter] = {}


def use_mock_adapters(enabled: bool = True) -> None:
    _TEST_MOCKS.clear()
    if enabled:
        for kind in ADAPTER_KINDS:
            _TEST_MOCKS[kind] = mock_adapter(kind)


def clear_mock_adapters() -> None:
    _TEST_MOCKS.clear()


def get_adapter(kind: str, *, dry_run: bool = False) -> WorkAdapter:
    if kind not in ADAPTER_KINDS:
        return disabled_adapter(kind)
    if kind in _TEST_MOCKS:
        return _TEST_MOCKS[kind]
    capability = KIND_TO_CAPABILITY[kind]
    if dry_run:
        return dry_run_adapter(kind)
    if is_capability_enabled(capability):
        # Conservative: even an enabled capability has no live connector.
        return disabled_adapter(kind)
    return disabled_adapter(kind)


def adapter_inventory() -> list[dict[str, object]]:
    rows = []
    for kind in ADAPTER_KINDS:
        adapter = get_adapter(kind)
        rows.append(
            {
                "kind": kind,
                "capability": KIND_TO_CAPABILITY[kind],
                "mode": adapter.mode,
                "available": adapter.available(),
                "live_implemented": False,
                "timeout_seconds": 8,
                "retry_limit": 0,
            }
        )
    return rows
