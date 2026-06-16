"""Governance validation summary helpers for safe reporting."""

from __future__ import annotations

from typing import Any


def build_governance_validation_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    passed = sum(1 for item in items if item.get("passed"))
    return {
        "status": "ok",
        "total_checks": total,
        "passed_checks": passed,
        "failed_checks": total - passed,
        "checks": items,
    }
