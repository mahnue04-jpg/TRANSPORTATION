"""Phase 2M fail-closed worker foundation. Reuses 2L process-batch. Does not auto-start."""
from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.autonomy import ledger
from app.core.nova.autonomy.models import AutonomyProcessBatchOut
from app.core.nova.autonomy.v2_jobs import (
    HARD_BATCH_MAX_JOBS,
    process_batch_jobs,
    recover_stale_locks,
)
from app.core.nova.autonomy.v2_service import Phase2BError, _org_flag
from app.helpers import now, uuid4

WORKER_ENABLED_ENV = "NOVA_AUTONOMY_WORKER_ENABLED"
WORKER_ORG_ENV = "NOVA_AUTONOMY_WORKER_ORGANIZATION_ID"
WORKER_POLL_ENV = "NOVA_AUTONOMY_WORKER_POLL_INTERVAL_SECONDS"
WORKER_MAX_JOBS_ENV = "NOVA_AUTONOMY_WORKER_MAX_JOBS_PER_CYCLE"
WORKER_EMPTY_BACKOFF_ENV = "NOVA_AUTONOMY_WORKER_EMPTY_BACKOFF_SECONDS"
WORKER_ERROR_BACKOFF_ENV = "NOVA_AUTONOMY_WORKER_ERROR_BACKOFF_SECONDS"
WORKER_CRITICAL_ENV = "NOVA_AUTONOMY_WORKER_MAX_CRITICAL_FAILURES"
WORKER_INSTANCE_ENV = "NOVA_AUTONOMY_WORKER_INSTANCE_ID"
ENABLED_VALUES = frozenset({"1", "true", "on", "yes"})
DEFAULT_POLL_INTERVAL_SECONDS = 30
MIN_POLL_INTERVAL_SECONDS = 5
DEFAULT_MAX_JOBS_PER_CYCLE = 1
DEFAULT_EMPTY_BACKOFF_SECONDS = 30
DEFAULT_ERROR_BACKOFF_SECONDS = 15
DEFAULT_MAX_CRITICAL_FAILURES = 3
TRANSIENT_ERRORS = (OperationalError, TimeoutError, ConnectionError, OSError)


def env_flag_enabled(name: str, environ: dict[str, str] | None = None) -> bool:
    source = environ if environ is not None else os.environ
    raw = str(source.get(name) or "").strip().lower()
    return raw in ENABLED_VALUES


def _env_int(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _truthy(value: bool | str | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ENABLED_VALUES


@dataclass
class WorkerHealth:
    alive: bool = False
    last_successful_cycle_at: datetime | None = None
    last_error: str | None = None
    jobs_processed: int = 0
    shutdown_requested: bool = False
    enabled: bool = False
    instance_id: str = ""
    last_stopped_reason: str | None = None
    cycles_completed: int = 0
    fail_closed: bool = False


class AutonomyWorker:
    """Bounded poll worker. Fail-closed unless worker flag and org phase2 are both on."""

    def __init__(
        self,
        *,
        enabled: bool | str | None = None,
        organization_id: str | None = None,
        user: UserContext | None = None,
        poll_interval_seconds: int | None = None,
        max_jobs_per_cycle: int | None = None,
        empty_backoff_seconds: int | None = None,
        error_backoff_seconds: int | None = None,
        max_critical_failures: int | None = None,
        instance_id: str | None = None,
        session_factory: Callable[[], Session] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        from app.db.session import SessionLocal

        if enabled is None:
            self.enabled = env_flag_enabled(WORKER_ENABLED_ENV)
        else:
            self.enabled = _truthy(enabled)
        self.organization_id = (organization_id or os.getenv(WORKER_ORG_ENV) or "").strip()
        self.user = user
        self.poll_interval_seconds = max(
            MIN_POLL_INTERVAL_SECONDS,
            int(poll_interval_seconds)
            if poll_interval_seconds is not None
            else _env_int(WORKER_POLL_ENV, DEFAULT_POLL_INTERVAL_SECONDS, minimum=MIN_POLL_INTERVAL_SECONDS),
        )
        requested_max = (
            int(max_jobs_per_cycle)
            if max_jobs_per_cycle is not None
            else _env_int(
                WORKER_MAX_JOBS_ENV,
                DEFAULT_MAX_JOBS_PER_CYCLE,
                minimum=1,
                maximum=HARD_BATCH_MAX_JOBS,
            )
        )
        self.max_jobs_per_cycle = max(1, min(HARD_BATCH_MAX_JOBS, requested_max))
        self.empty_backoff_seconds = max(
            MIN_POLL_INTERVAL_SECONDS,
            int(empty_backoff_seconds)
            if empty_backoff_seconds is not None
            else _env_int(
                WORKER_EMPTY_BACKOFF_ENV,
                DEFAULT_EMPTY_BACKOFF_SECONDS,
                minimum=MIN_POLL_INTERVAL_SECONDS,
            ),
        )
        self.error_backoff_seconds = max(
            MIN_POLL_INTERVAL_SECONDS,
            int(error_backoff_seconds)
            if error_backoff_seconds is not None
            else _env_int(
                WORKER_ERROR_BACKOFF_ENV,
                DEFAULT_ERROR_BACKOFF_SECONDS,
                minimum=MIN_POLL_INTERVAL_SECONDS,
            ),
        )
        self.max_critical_failures = max(
            1,
            int(max_critical_failures)
            if max_critical_failures is not None
            else _env_int(WORKER_CRITICAL_ENV, DEFAULT_MAX_CRITICAL_FAILURES, minimum=1),
        )
        self.instance_id = (instance_id or os.getenv(WORKER_INSTANCE_ENV) or ("NWW-" + uuid4().replace("-", "")[:12].upper()))
        self._session_factory = session_factory or SessionLocal
        self._sleeper = sleeper or time.sleep
        self.shutdown_requested = False
        self.fail_closed = False
        self._running = False
        self.jobs_processed = 0
        self.cycles_completed = 0
        self.critical_failures = 0
        self.transient_failures = 0
        self.last_error: str | None = None
        self.last_successful_cycle_at: datetime | None = None
        self.last_stopped_reason: str | None = None
        self.last_sleep_seconds: float = 0.0

    def health(self) -> WorkerHealth:
        return WorkerHealth(
            alive=self._running and not self.shutdown_requested and not self.fail_closed,
            last_successful_cycle_at=self.last_successful_cycle_at,
            last_error=self.last_error,
            jobs_processed=self.jobs_processed,
            shutdown_requested=self.shutdown_requested,
            enabled=self.enabled,
            instance_id=self.instance_id,
            last_stopped_reason=self.last_stopped_reason,
            cycles_completed=self.cycles_completed,
            fail_closed=self.fail_closed,
        )

    def readiness(self) -> dict[str, Any]:
        snapshot = self.health()
        ready = snapshot.enabled and snapshot.alive and snapshot.last_error is None and not snapshot.fail_closed
        return {
            "ready": ready,
            "alive": snapshot.alive,
            "last_successful_cycle_at": snapshot.last_successful_cycle_at.isoformat()
            if snapshot.last_successful_cycle_at
            else None,
            "last_error": snapshot.last_error,
            "jobs_processed": snapshot.jobs_processed,
            "shutdown_requested": snapshot.shutdown_requested,
        }

    def request_shutdown(self, *_args: Any) -> None:
        self.shutdown_requested = True

    def handle_signal(self, signum: int, _frame: Any = None) -> None:
        self.request_shutdown()

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

    def run(self, *, max_cycles: int | None = None) -> int:
        if not self.enabled:
            self._running = False
            self.last_stopped_reason = "worker_disabled"
            return 0
        if not self.organization_id or self.user is None:
            self.fail_closed = True
            self.last_error = "worker_config_incomplete"
            self.last_stopped_reason = "fail_closed"
            return 2
        if (self.user.organization_id or "").strip() != self.organization_id:
            self.fail_closed = True
            self.last_error = "tenant_mismatch"
            self.last_stopped_reason = "tenant_mismatch"
            return 2
        self._running = True
        exit_code = 0
        try:
            cycles = 0
            while not self.shutdown_requested:
                if max_cycles is not None and cycles >= max_cycles:
                    break
                delay = self._one_cycle()
                cycles += 1
                if self.fail_closed:
                    exit_code = 2
                    break
                if self.shutdown_requested:
                    break
                self._sleep(delay)
        finally:
            self._recover_on_exit()
            self._running = False
        return exit_code

    def run_cycle(self, db: Session) -> AutonomyProcessBatchOut:
        if not self.enabled or self.shutdown_requested or self.fail_closed:
            reason = "shutdown_requested" if self.shutdown_requested else "worker_disabled"
            return self._empty(reason)
        if self.user is None or not self.organization_id:
            return self._empty("worker_config_incomplete")
        if (self.user.organization_id or "").strip() != self.organization_id:
            self._mark_critical("tenant_mismatch")
            return self._empty("tenant_mismatch")
        recover_stale_locks(db, user=self.user, organization_id=self.organization_id)
        flag = _org_flag(db, self.organization_id)
        if flag is not None and bool(flag.emergency_stop):
            return self._empty("emergency_stop")
        if flag is None or not bool(flag.phase2_enabled):
            return self._empty("phase2_disabled")
        try:
            return process_batch_jobs(
                db,
                user=self.user,
                max_jobs=self.max_jobs_per_cycle,
                requested_org=self.organization_id,
                should_claim=lambda: not self.shutdown_requested and not self.fail_closed,
            )
        except Phase2BError as exc:
            if int(getattr(exc, "status_code", 0) or 0) in {400, 403, 404}:
                return self._empty("gate_denied")
            raise

    def _one_cycle(self) -> float:
        started = time.perf_counter()
        result = self._empty("cycle_error")
        try:
            with self._session_factory() as db:
                result = self.run_cycle(db)
                self._audit_cycle(db, result, duration_ms=int((time.perf_counter() - started) * 1000))
            self.cycles_completed += 1
            self.jobs_processed += int(result.processed_count or 0)
            self.last_stopped_reason = result.stopped_reason
            self.last_successful_cycle_at = now()
            if result.stopped_reason in {"external_mutation", "tenant_mismatch", "high_or_prohibited"}:
                self._mark_critical(result.stopped_reason)
            elif result.stopped_reason == "no_eligible_jobs":
                self.last_error = None
                self.transient_failures = 0
                return float(self.empty_backoff_seconds)
            else:
                self.last_error = None
                self.transient_failures = 0
                self.critical_failures = 0
            return float(self.poll_interval_seconds)
        except TRANSIENT_ERRORS as exc:
            self.transient_failures += 1
            self.last_error = type(exc).__name__
            self.last_stopped_reason = "transient_error"
            delay = min(
                self.error_backoff_seconds * (2 ** max(self.transient_failures - 1, 0)),
                self.error_backoff_seconds * 8,
            )
            return float(max(self.error_backoff_seconds, delay))
        except Exception as exc:
            self._mark_critical(type(exc).__name__)
            self.last_stopped_reason = "critical_error"
            return float(self.error_backoff_seconds)

    def _audit_cycle(self, db: Session, result: AutonomyProcessBatchOut, *, duration_ms: int) -> None:
        if self.user is None:
            return
        detail = (
            f"instance={self.instance_id} processed={result.processed_count} "
            f"succeeded={result.succeeded_count} failed={result.failed_count} "
            f"blocked={result.blocked_count} stopped={result.stopped_reason} "
            f"duration_ms={duration_ms}"
        )
        ledger.append(
            db,
            user=self.user,
            organization_id=self.organization_id,
            action_type="worker_cycle",
            risk_class="LOW",
            approval_state="recorded",
            source_module="autonomy",
            source_ref_id=self.instance_id,
            executed=False,
            result="worker_cycle",
            verification_result=result.stopped_reason,
            detail=detail[:400],
            target_module="autonomy",
        )

    def _empty(self, reason: str) -> AutonomyProcessBatchOut:
        return AutonomyProcessBatchOut(
            requested_max_jobs=self.max_jobs_per_cycle,
            processed_count=0,
            succeeded_count=0,
            failed_count=0,
            blocked_count=0,
            stopped_reason=reason,
            mutated_external=False,
            phase2_enabled=False,
        )

    def _mark_critical(self, reason: str) -> None:
        self.critical_failures += 1
        self.last_error = reason
        if self.critical_failures >= self.max_critical_failures:
            self.fail_closed = True
            self.shutdown_requested = True
            self.last_stopped_reason = "fail_closed"

    def _sleep(self, seconds: float) -> None:
        delay = max(float(seconds), float(MIN_POLL_INTERVAL_SECONDS))
        self.last_sleep_seconds = delay
        if not self.shutdown_requested and not self.fail_closed:
            self._sleeper(delay)

    def _recover_on_exit(self) -> None:
        if self.user is None or not self.organization_id:
            return
        try:
            with self._session_factory() as db:
                recover_stale_locks(db, user=self.user, organization_id=self.organization_id)
        except Exception:
            return


def main() -> int:
    worker = AutonomyWorker()
    if not worker.enabled:
        return 0
    worker.install_signal_handlers()
    return worker.run()


if __name__ == "__main__":
    raise SystemExit(main())
