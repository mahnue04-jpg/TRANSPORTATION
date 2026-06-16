from __future__ import annotations

from app.core.nova.health_check_engine import CheckStatus, health_check_engine


async def test_rollback_integrity_is_healthy_when_no_failed_actions() -> None:
    org = "phase7d-zero-failures-org"
    result = await health_check_engine._check_rollback_integrity(org)

    assert result.status == CheckStatus.HEALTHY
    assert "no failed actions" in result.message.lower()
    assert result.details.get("failed_count") == 0
    assert result.details.get("recovery_rate") == 1.0
