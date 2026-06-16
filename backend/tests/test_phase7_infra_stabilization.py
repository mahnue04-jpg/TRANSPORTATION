"""
backend/tests/test_phase7_infra_stabilization.py

Phase 7 — Production Infrastructure Stabilization: lightweight validation tests.

These tests verify the new infrastructure modules introduced in Phase 7 without
touching the existing test suite.  The baseline (262 passed / 1 skipped / 0 failed)
must be preserved after adding these tests.
"""
from __future__ import annotations

import importlib
import os


# ── runtime_config ────────────────────────────────────────────────────────────

def test_validate_runtime_config_returns_dict():
    from app.core.runtime_config import validate_runtime_config

    result = validate_runtime_config()
    assert isinstance(result, dict)


def test_validate_runtime_config_has_required_keys():
    from app.core.runtime_config import validate_runtime_config

    result = validate_runtime_config()
    required_keys = {
        "app_env",
        "debug",
        "has_database_url",
        "has_redis_url",
        "has_openai_api_key",
        "supervision_log_retention_days",
        "missing_required",
        "missing_optional",
        "validation_status",
        "validated_at",
    }
    for key in required_keys:
        assert key in result, f"Missing key: {key}"


def test_validate_runtime_config_status_is_valid_value():
    from app.core.runtime_config import validate_runtime_config

    result = validate_runtime_config()
    assert result["validation_status"] in {"ok", "degraded", "critical"}


def test_validate_runtime_config_no_secrets_in_output():
    """Ensure secret var names / values do not leak into the result dict."""
    from app.core.runtime_config import validate_runtime_config

    result = validate_runtime_config()
    # Neither DATABASE_URL nor OPENAI_API_KEY should appear in public lists
    assert "DATABASE_URL" not in result.get("missing_required", [])
    assert "DATABASE_URL" not in result.get("missing_optional", [])
    assert "OPENAI_API_KEY" not in result.get("missing_required", [])
    assert "OPENAI_API_KEY" not in result.get("missing_optional", [])


def test_validate_runtime_config_app_env_fallback(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    from app.core import runtime_config as rc
    importlib.reload(rc)
    result = rc.validate_runtime_config()
    assert result["app_env"] == "development"


# ── system_metrics ────────────────────────────────────────────────────────────

def test_active_request_counter_increments_and_decrements():
    from app.monitoring.system_metrics import (
        decrement_active_requests,
        get_active_request_count,
        increment_active_requests,
    )

    before = get_active_request_count()
    increment_active_requests()
    assert get_active_request_count() == before + 1
    decrement_active_requests()
    assert get_active_request_count() == before


def test_active_request_counter_never_goes_negative():
    from app.monitoring.system_metrics import decrement_active_requests, get_active_request_count

    # Decrement more times than we have active requests — should clamp at 0
    for _ in range(10):
        decrement_active_requests()
    assert get_active_request_count() >= 0


def test_get_process_memory_mb_returns_none_or_float():
    from app.monitoring.system_metrics import get_process_memory_mb

    result = get_process_memory_mb()
    assert result is None or isinstance(result, float)


def test_get_process_cpu_percent_returns_none_or_float():
    from app.monitoring.system_metrics import get_process_cpu_percent

    result = get_process_cpu_percent()
    assert result is None or isinstance(result, float)


def test_get_uptime_human_readable_formats():
    from app.monitoring.system_metrics import get_uptime_human_readable

    assert get_uptime_human_readable(0) == "0s"
    assert get_uptime_human_readable(61) == "1m 1s"
    assert get_uptime_human_readable(3661) == "1h 1m 1s"
    assert get_uptime_human_readable(86400 + 3661) == "1d 1h 1m 1s"


def test_get_system_metrics_snapshot_structure():
    from app.monitoring.system_metrics import get_system_metrics_snapshot

    snapshot = get_system_metrics_snapshot(uptime_seconds=120.0)
    assert isinstance(snapshot, dict)
    assert "active_request_count" in snapshot
    assert "process_memory_mb" in snapshot
    assert "process_cpu_percent" in snapshot
    assert "uptime_human_readable" in snapshot
    assert snapshot["uptime_human_readable"] == "2m 0s"


# ── error_boundary ────────────────────────────────────────────────────────────

def test_error_boundary_module_importable():
    from app.core.error_boundary import ErrorBoundaryMiddleware

    assert ErrorBoundaryMiddleware is not None


def test_error_boundary_is_production_false_by_default(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    from app.core import error_boundary as eb
    importlib.reload(eb)
    assert eb._is_production() is False


def test_error_boundary_is_production_true_for_production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    from app.core import error_boundary as eb
    importlib.reload(eb)
    assert eb._is_production() is True


# ── supervision_snapshot ──────────────────────────────────────────────────────

def test_supervision_snapshot_has_health_classification():
    from app.monitoring.supervision_snapshot import build_supervision_snapshot

    snapshot = build_supervision_snapshot()
    assert "health_classification" in snapshot
    assert snapshot["health_classification"] in {"HEALTHY", "DEGRADED", "CRITICAL"}


def test_supervision_snapshot_has_new_phase7_fields():
    from app.monitoring.supervision_snapshot import build_supervision_snapshot

    snapshot = build_supervision_snapshot()
    assert "active_request_count" in snapshot
    assert "process_memory_mb" in snapshot
    assert "process_cpu_percent" in snapshot
    assert "uptime_human_readable" in snapshot
    assert isinstance(snapshot["active_request_count"], int)


def test_supervision_snapshot_diagnostics_version_updated():
    from app.monitoring.supervision_snapshot import build_supervision_snapshot

    snapshot = build_supervision_snapshot()
    assert snapshot["diagnostics_version"] == "1.2.0"


def test_health_classification_logic():
    from app.monitoring.supervision_snapshot import _classify_health

    assert _classify_health("unavailable", "healthy", "available") == "CRITICAL"
    assert _classify_health("alive", "unavailable", "available") == "CRITICAL"
    assert _classify_health("alive", "healthy", "unavailable") == "DEGRADED"
    assert _classify_health("degraded", "healthy", "available") == "DEGRADED"
    assert _classify_health("alive", "healthy", "available") == "HEALTHY"
