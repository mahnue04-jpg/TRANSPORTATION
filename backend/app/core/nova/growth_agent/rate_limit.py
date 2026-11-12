"""Atomic shared widget rate limiting for multi-worker deployments.

Uses durable counters keyed by org + bucket + window. Survives process restart.
Primary enforcement is SQL compare-and-set — not process-local memory.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.models import GaRateLimitCounter

# SQLite same-process threads can share a connection pool unsafely; serialize locally.
# Postgres/multi-process still rely on atomic SQL UPDATE ... WHERE count < :limit.
_SQLITE_GATE = threading.Lock()


def _window_start(now_ts: float | None = None, *, window_seconds: int = 60) -> int:
    ts = int(now_ts if now_ts is not None else time.time())
    return ts - (ts % max(1, int(window_seconds)))


def check_and_increment(
    db: Session,
    *,
    organization_id: str,
    bucket_key: str,
    limit: int,
    window_seconds: int = 60,
    now_ts: float | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Atomically consume one unit from the shared window.

    Raises GrowthAgentError(RATE_LIMITED) when the window is already at limit.
    When commit=True (default), the counter mutation is committed before unlock so
    concurrent workers observe the durable count immediately.
    """
    if limit <= 0:
        raise GrowthAgentError("RATE_LIMITED", "Too many requests", http_status=429)

    window = _window_start(now_ts, window_seconds=window_seconds)
    key = (bucket_key or "").strip()[:160]
    org = (organization_id or "").strip()
    if not org or not key:
        raise GrowthAgentError("VALIDATION", "rate limit requires organization_id and bucket_key")

    now = datetime.utcnow()
    params = {
        "org": org,
        "key": key,
        "window": window,
        "limit": int(limit),
        "now": now,
        "id": uuid4().hex,
    }

    dialect = db.get_bind().dialect.name
    gate = _SQLITE_GATE if dialect == "sqlite" else None
    if gate:
        gate.acquire()
    try:
        result = _check_and_increment_unlocked(
            db, params=params, limit=limit, window=window, window_seconds=window_seconds
        )
        if commit:
            db.commit()
        return result
    except Exception:
        if commit:
            db.rollback()
        raise
    finally:
        if gate:
            gate.release()


def _check_and_increment_unlocked(
    db: Session,
    *,
    params: dict[str, Any],
    limit: int,
    window: int,
    window_seconds: int,
) -> dict[str, Any]:
    org = params["org"]
    key = params["key"]

    def _try_increment() -> int:
        result = db.execute(
            text(
                """
                UPDATE nova_ga_rate_limit_counters
                SET count = count + 1, updated_at = :now
                WHERE organization_id = :org
                  AND bucket_key = :key
                  AND window_start = :window
                  AND count < :limit
                """
            ),
            params,
        )
        return int(result.rowcount or 0)

    if _try_increment() == 1:
        count = (
            db.query(GaRateLimitCounter.count)
            .filter_by(organization_id=org, bucket_key=key, window_start=window)
            .scalar()
        )
        db.flush()
        return {
            "allowed": True,
            "count": int(count or 0),
            "limit": limit,
            "window_start": window,
            "window_seconds": window_seconds,
            "shared": True,
        }

    # Ensure a window row exists. ON CONFLICT DO NOTHING is race-safe across workers.
    db.execute(
        text(
            """
            INSERT INTO nova_ga_rate_limit_counters
                (id, organization_id, bucket_key, window_start, count, updated_at)
            VALUES (:id, :org, :key, :window, 0, :now)
            ON CONFLICT(organization_id, bucket_key, window_start) DO NOTHING
            """
        ),
        params,
    )
    db.flush()

    if _try_increment() == 1:
        count = (
            db.query(GaRateLimitCounter.count)
            .filter_by(organization_id=org, bucket_key=key, window_start=window)
            .scalar()
        )
        db.flush()
        return {
            "allowed": True,
            "count": int(count or 0),
            "limit": limit,
            "window_start": window,
            "window_seconds": window_seconds,
            "shared": True,
        }

    raise GrowthAgentError("RATE_LIMITED", "Too many requests", http_status=429)


def current_count(
    db: Session,
    *,
    organization_id: str,
    bucket_key: str,
    window_seconds: int = 60,
    now_ts: float | None = None,
) -> int:
    window = _window_start(now_ts, window_seconds=window_seconds)
    row = (
        db.query(GaRateLimitCounter)
        .filter_by(
            organization_id=organization_id,
            bucket_key=bucket_key,
            window_start=window,
        )
        .one_or_none()
    )
    return int(row.count) if row else 0
