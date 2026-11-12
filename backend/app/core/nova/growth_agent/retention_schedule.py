"""Scheduled retention processor — default-off, dry-run by default.

Reuses preview_retention / execute_retention. Durable per-org window rows provide
duplicate-run protection. Leases recover crashed workers. Deletion requires a
separate explicit flag beyond schedule enablement.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.nova.growth_agent.flags import (
    retention_delete_enabled,
    retention_schedule_enabled,
)
from app.core.nova.growth_agent.models import GaBusinessProfile, GaRetentionScheduleRun
from app.core.nova.growth_agent.retention import execute_retention, preview_retention

logger = logging.getLogger("amicor.nova.growth_agent.retention_schedule")

DEFAULT_LEASE_SECONDS = 60
DEFAULT_BATCH_LIMIT = 500
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_CLAIM_BATCH = 10


def _utcnow() -> datetime:
    return datetime.utcnow()


def _backoff_seconds(attempt_number: int) -> int:
    return min(600, 2 ** max(1, int(attempt_number)))


def current_window_key(*, now: datetime | None = None) -> str:
    """UTC calendar day window — one scheduled run per org per day."""
    stamp = now or _utcnow()
    return stamp.strftime("%Y-%m-%d")


def effective_mode() -> str:
    """Delete only when separately enabled; otherwise dry-run."""
    return "delete" if retention_delete_enabled() else "dry_run"


class RetentionScheduler:
    """Claims and processes durable retention schedule runs."""

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        scheduler_id: str | None = None,
        organization_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        claim_batch: int = DEFAULT_CLAIM_BATCH,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
    ) -> None:
        self.session_factory = session_factory
        self.scheduler_id = scheduler_id or f"ga-retention-{uuid4().hex[:12]}"
        self.organization_id = organization_id
        self.lease_seconds = max(10, int(lease_seconds))
        self.claim_batch = max(1, min(int(claim_batch), 50))
        self.batch_limit = max(1, min(int(batch_limit), 2000))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = {
            "ensured": 0,
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "dry_runs": 0,
            "deletes": 0,
            "ticks": 0,
        }

    def request_shutdown(self) -> None:
        self._stop.set()

    def ensure_pending_runs(
        self,
        db: Session,
        *,
        window_key: str | None = None,
        organization_ids: list[str] | None = None,
    ) -> list[str]:
        """Create pending durable rows for the window. Unique constraint blocks dupes."""
        window = window_key or current_window_key()
        mode = effective_mode()
        if organization_ids is None:
            q = db.query(GaBusinessProfile.organization_id).filter(
                GaBusinessProfile.activated.is_(True)
            )
            if self.organization_id:
                q = q.filter(GaBusinessProfile.organization_id == self.organization_id)
            organization_ids = [r[0] for r in q.distinct().all()]
        created: list[str] = []
        for org_id in organization_ids:
            if self.organization_id and org_id != self.organization_id:
                continue
            existing = (
                db.query(GaRetentionScheduleRun)
                .filter_by(organization_id=org_id, window_key=window)
                .one_or_none()
            )
            if existing is not None:
                continue
            row = GaRetentionScheduleRun(
                id=uuid4().hex,
                organization_id=org_id,
                window_key=window,
                status="pending",
                mode=mode,
                batch_limit=self.batch_limit,
                available_at=_utcnow(),
                attempt_number=0,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                result_json={},
            )
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                created.append(row.id)
                self.stats["ensured"] += 1
            except IntegrityError:
                # Concurrent ensurer already inserted this org+window.
                continue
        return created

    def claim_runs(self, db: Session, *, limit: int | None = None) -> list[GaRetentionScheduleRun]:
        now = _utcnow()
        batch = max(1, min(limit or self.claim_batch, 50))
        claim_token = f"{self.scheduler_id}:{uuid4().hex[:8]}"
        lease_until = now + timedelta(seconds=self.lease_seconds)

        available = (GaRetentionScheduleRun.available_at.is_(None)) | (
            GaRetentionScheduleRun.available_at <= now
        )
        lease_free = (
            (GaRetentionScheduleRun.claimed_by.is_(None))
            | (GaRetentionScheduleRun.lease_expires_at.is_(None))
            | (GaRetentionScheduleRun.lease_expires_at < now)
        )
        q = db.query(GaRetentionScheduleRun.id).filter(
            available,
            lease_free,
            GaRetentionScheduleRun.status.in_(["pending", "running", "failed"]),
            GaRetentionScheduleRun.attempt_number < GaRetentionScheduleRun.max_attempts,
        )
        if self.organization_id:
            q = q.filter(GaRetentionScheduleRun.organization_id == self.organization_id)
        candidate_ids = [
            r[0] for r in q.order_by(GaRetentionScheduleRun.created_at.asc()).limit(batch).all()
        ]
        if not candidate_ids:
            return []

        claimed: list[GaRetentionScheduleRun] = []
        for run_id in candidate_ids:
            row = (
                db.query(GaRetentionScheduleRun)
                .filter(
                    GaRetentionScheduleRun.id == run_id,
                    GaRetentionScheduleRun.status.in_(["pending", "running", "failed"]),
                    available,
                    lease_free,
                )
                .with_for_update(of=GaRetentionScheduleRun)
                .one_or_none()
            )
            if row is None:
                continue
            if self.organization_id and row.organization_id != self.organization_id:
                continue
            # Terminal completed windows are never reclaimed (duplicate protection).
            if row.status == "completed":
                continue
            row.status = "running"
            row.mode = effective_mode()
            row.claimed_by = claim_token
            row.claimed_at = now
            row.lease_expires_at = lease_until
            row.updated_at = now
            claimed.append(row)
        db.flush()
        self.stats["claimed"] += len(claimed)
        return claimed

    def process_run(self, db: Session, run: GaRetentionScheduleRun) -> dict[str, Any]:
        mode = effective_mode()
        run.mode = mode
        run.attempt_number = int(run.attempt_number or 0) + 1
        limit = max(1, min(int(run.batch_limit or self.batch_limit), 2000))
        try:
            if mode == "delete":
                result = execute_retention(
                    db,
                    run.organization_id,
                    batch_limit=limit,
                    actor_user_id=None,
                )
                # execute_retention commits; refresh run after commit
                db.refresh(run)
                self.stats["deletes"] += 1
            else:
                result = preview_retention(db, run.organization_id, batch_limit=limit)
                result = {
                    **result,
                    "scheduled": True,
                    "mode": "dry_run",
                    "delete_enabled": False,
                    "note": (
                        "Scheduled dry-run only. Set "
                        "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=true for deletion."
                    ),
                }
                self.stats["dry_runs"] += 1

            run.status = "completed"
            run.result_json = {
                "mode": mode,
                "dry_run": mode != "delete",
                "total_would_delete": result.get("total_would_delete"),
                "total_deleted": result.get("total_deleted"),
                "deleted_counts": result.get("deleted_counts"),
                "categories_summary": {
                    k: {
                        "eligible_count": v.get("eligible_count"),
                        "would_delete": v.get("would_delete"),
                    }
                    for k, v in (result.get("categories") or {}).items()
                },
                "retain_always": result.get("retain_always"),
                "scheduler_id": self.scheduler_id,
            }
            run.error_code = None
            run.claimed_by = None
            run.claimed_at = None
            run.lease_expires_at = None
            run.available_at = None
            run.completed_at = _utcnow()
            run.updated_at = _utcnow()
            self.stats["completed"] += 1
            return {"id": run.id, "status": "completed", "mode": mode, "result": run.result_json}
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "scheduled retention failed org=%s window=%s",
                run.organization_id,
                run.window_key,
            )
            return self._fail_or_retry(run, error_code=type(exc).__name__)

    def _fail_or_retry(self, run: GaRetentionScheduleRun, *, error_code: str) -> dict[str, Any]:
        run.error_code = error_code
        run.claimed_by = None
        run.claimed_at = None
        run.lease_expires_at = None
        run.updated_at = _utcnow()
        max_attempts = int(run.max_attempts or DEFAULT_MAX_ATTEMPTS)
        if int(run.attempt_number or 0) >= max_attempts:
            run.status = "failed"
            run.completed_at = _utcnow()
            run.result_json = {
                **(run.result_json or {}),
                "error_code": error_code,
                "terminal": True,
            }
            self.stats["failed"] += 1
            return {"id": run.id, "status": "failed", "error": error_code}
        delay = _backoff_seconds(run.attempt_number)
        run.status = "failed"  # reclaimable failed with attempts remaining
        run.available_at = _utcnow() + timedelta(seconds=delay)
        self.stats["failed"] += 1
        return {
            "id": run.id,
            "status": "failed",
            "error": error_code,
            "retry_at": run.available_at.isoformat() + "Z",
            "attempt_number": run.attempt_number,
        }

    def run_once(
        self,
        *,
        limit: int | None = None,
        window_key: str | None = None,
        ensure: bool = True,
    ) -> dict[str, Any]:
        """Ensure pending window rows, claim, and process one batch."""
        db = self.session_factory()
        results: list[dict[str, Any]] = []
        try:
            if ensure:
                self.ensure_pending_runs(db, window_key=window_key)
                db.commit()
            window = window_key or current_window_key()
            claimed = self.claim_runs(db, limit=limit)
            for run in claimed:
                if self._stop.is_set():
                    if run.status == "running":
                        run.status = "pending"
                        run.claimed_by = None
                        run.claimed_at = None
                        run.lease_expires_at = None
                    continue
                results.append(self.process_run(db, run))
            self.stats["ticks"] += 1
            already_done = []
            if self.organization_id and not claimed:
                existing = (
                    db.query(GaRetentionScheduleRun)
                    .filter_by(organization_id=self.organization_id, window_key=window)
                    .one_or_none()
                )
                if existing is not None and existing.status == "completed":
                    already_done.append(
                        {
                            "id": existing.id,
                            "window_key": existing.window_key,
                            "status": existing.status,
                            "mode": existing.mode,
                            "result": existing.result_json,
                            "note": "Duplicate window protected — prior completed run reused.",
                        }
                    )
                    self.stats["skipped"] += 1
            db.commit()
            return {
                "scheduler_id": self.scheduler_id,
                "window_key": window,
                "schedule_enabled": retention_schedule_enabled(),
                "delete_enabled": retention_delete_enabled(),
                "mode": effective_mode(),
                "claimed": len(claimed),
                "processed": len(results),
                "results": results,
                "already_completed_window": already_done,
                "stats": dict(self.stats),
                "organization_id": self.organization_id,
                "dry_run_default": True,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def run_loop(self, *, poll_seconds: float = 30.0) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            if not retention_schedule_enabled() and os.getenv("TESTING", "").lower() not in {
                "1",
                "true",
                "yes",
            }:
                self._stop.wait(max(1.0, float(poll_seconds)))
                continue
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "retention scheduler tick failed scheduler_id=%s", self.scheduler_id
                )
            self._stop.wait(max(1.0, float(poll_seconds)))

    def start_background(self, *, poll_seconds: float = 30.0) -> threading.Thread:
        if self._thread and self._thread.is_alive():
            return self._thread
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run_loop,
            kwargs={"poll_seconds": poll_seconds},
            name=f"nova-ga-retention-{self.scheduler_id}",
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def join(self, timeout: float | None = 5.0) -> None:
        self.request_shutdown()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


_RUNTIME_SCHEDULER: RetentionScheduler | None = None
_RUNTIME_LOCK = threading.Lock()


def get_runtime_scheduler() -> RetentionScheduler | None:
    return _RUNTIME_SCHEDULER


def start_runtime_scheduler(
    session_factory: sessionmaker, *, poll_seconds: float = 30.0
) -> RetentionScheduler | None:
    global _RUNTIME_SCHEDULER
    if not retention_schedule_enabled():
        return None
    with _RUNTIME_LOCK:
        if (
            _RUNTIME_SCHEDULER
            and _RUNTIME_SCHEDULER._thread
            and _RUNTIME_SCHEDULER._thread.is_alive()
        ):
            return _RUNTIME_SCHEDULER
        scheduler = RetentionScheduler(session_factory)
        scheduler.start_background(poll_seconds=poll_seconds)
        _RUNTIME_SCHEDULER = scheduler
        logger.info(
            "Nova Growth Agent retention scheduler started id=%s mode=%s",
            scheduler.scheduler_id,
            effective_mode(),
        )
        return scheduler


def stop_runtime_scheduler(timeout: float = 5.0) -> None:
    global _RUNTIME_SCHEDULER
    with _RUNTIME_LOCK:
        scheduler = _RUNTIME_SCHEDULER
        _RUNTIME_SCHEDULER = None
    if scheduler:
        scheduler.join(timeout=timeout)
        logger.info(
            "Nova Growth Agent retention scheduler stopped id=%s", scheduler.scheduler_id
        )


def recent_runs_for_org(db: Session, organization_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        db.query(GaRetentionScheduleRun)
        .filter_by(organization_id=organization_id)
        .order_by(GaRetentionScheduleRun.created_at.desc())
        .limit(max(1, min(limit, 50)))
        .all()
    )
    return [
        {
            "id": r.id,
            "window_key": r.window_key,
            "status": r.status,
            "mode": r.mode,
            "attempt_number": r.attempt_number,
            "error_code": r.error_code,
            "result": r.result_json,
            "claimed_by": r.claimed_by,
            "lease_expires_at": r.lease_expires_at.isoformat() + "Z" if r.lease_expires_at else None,
            "completed_at": r.completed_at.isoformat() + "Z" if r.completed_at else None,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }
        for r in rows
    ]
