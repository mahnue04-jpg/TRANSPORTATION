"""Durable mock delivery worker — default-off, never live transports.

Features:
- Atomic job claiming with leases
- Bounded retries + exponential backoff
- Restart recovery (stale lease reclaim)
- Duplicate protection via delivery idempotency keys
- Tenant isolation (optional org scope)
- Consent / opt-out / pause / quiet-hours recheck before processing
- Graceful shutdown via stop event
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.nova.growth_agent.errors import ConsentRequiredError, GrowthAgentError
from app.core.nova.growth_agent.flags import REAL_EMAIL_SEND, REAL_SMS_SEND, background_worker_enabled
from app.core.nova.growth_agent.models import (
    GaContact,
    GaDeliveryAttempt,
    GaWorkflowDefinition,
    GaWorkerHeartbeat,
    GaWorkflowRun,
)
from app.core.nova.growth_agent.quiet_hours import in_quiet_hours, next_send_after_quiet_hours
from app.core.nova.growth_agent import workflows as wf_mod

logger = logging.getLogger("amicor.nova.growth_agent.worker")

DEFAULT_LEASE_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BATCH_SIZE = 10
STALE_MULTIPLIER = 1  # reclaim when lease_expires_at < now


def _utcnow() -> datetime:
    return datetime.utcnow()


def _backoff_seconds(attempt_number: int) -> int:
    # 2, 4, 8, 16, 32 ... capped at 300s
    return min(300, 2 ** max(1, int(attempt_number)))


class MockDeliveryWorker:
    """Processes queued/retrying mock deliveries only."""

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        worker_id: str | None = None,
        organization_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        service_factory: Callable[[Session], Any] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.worker_id = worker_id or f"ga-worker-{uuid4().hex[:12]}"
        self.organization_id = organization_id
        self.lease_seconds = max(5, int(lease_seconds))
        self.batch_size = max(1, min(int(batch_size), 100))
        self.service_factory = service_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = {
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "suppressed": 0,
            "deferred_quiet_hours": 0,
            "ticks": 0,
        }

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def request_shutdown(self) -> None:
        self._stop.set()
        self._heartbeat(status="stopping")

    def _heartbeat(self, *, status: str, db: Session | None = None) -> None:
        owns = db is None
        session = db or self.session_factory()
        try:
            row = session.get(GaWorkerHeartbeat, self.worker_id)
            if row is None:
                row = GaWorkerHeartbeat(
                    worker_id=self.worker_id,
                    status=status,
                    jobs_claimed=self.stats["claimed"],
                    jobs_completed=self.stats["completed"],
                    jobs_failed=self.stats["failed"],
                    last_beat_at=_utcnow(),
                    meta_json={
                        "organization_id": self.organization_id,
                        "mock_only": True,
                        "live_email": False,
                        "live_sms": False,
                    },
                )
                session.add(row)
            else:
                row.status = status
                row.jobs_claimed = self.stats["claimed"]
                row.jobs_completed = self.stats["completed"]
                row.jobs_failed = self.stats["failed"]
                row.last_beat_at = _utcnow()
                row.meta_json = {
                    "organization_id": self.organization_id,
                    "mock_only": True,
                    "live_email": bool(REAL_EMAIL_SEND),
                    "live_sms": bool(REAL_SMS_SEND),
                    "deferred_quiet_hours": self.stats["deferred_quiet_hours"],
                    "suppressed": self.stats["suppressed"],
                }
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.exception("growth worker heartbeat failed worker_id=%s", self.worker_id)
        finally:
            if owns:
                session.close()

    def release_held_claims(self, db: Session) -> int:
        """Release any running jobs still held by this worker (graceful stop / join timeout)."""
        prefix = f"{self.worker_id}:"
        rows = (
            db.query(GaDeliveryAttempt)
            .filter(
                GaDeliveryAttempt.status == "running",
                GaDeliveryAttempt.claimed_by.isnot(None),
                GaDeliveryAttempt.claimed_by.like(f"{prefix}%"),
            )
            .all()
        )
        released = 0
        for row in rows:
            row.status = "queued"
            row.claimed_by = None
            row.claimed_at = None
            row.lease_expires_at = None
            released += 1
        if released:
            db.flush()
        return released

    def claim_jobs(self, db: Session, *, limit: int | None = None) -> list[GaDeliveryAttempt]:
        """Atomically claim a batch of available mock delivery jobs."""
        if self._stop.is_set():
            # Graceful shutdown: never take new leases after stop is requested.
            return []
        now = _utcnow()
        batch = max(1, min(limit or self.batch_size, 100))
        claim_token = f"{self.worker_id}:{uuid4().hex[:8]}"
        lease_until = now + timedelta(seconds=self.lease_seconds)

        # Claim queued/retrying jobs, or running jobs whose lease expired (restart recovery).
        available = (GaDeliveryAttempt.available_at.is_(None)) | (GaDeliveryAttempt.available_at <= now)
        lease_free = (
            (GaDeliveryAttempt.claimed_by.is_(None))
            | (GaDeliveryAttempt.lease_expires_at.is_(None))
            | (GaDeliveryAttempt.lease_expires_at < now)
        )
        q = db.query(GaDeliveryAttempt.id).filter(
            GaDeliveryAttempt.provider == "mock",
            available,
            lease_free,
            GaDeliveryAttempt.status.in_(["queued", "retrying", "running"]),
        )
        if self.organization_id:
            q = q.filter(GaDeliveryAttempt.organization_id == self.organization_id)
        candidate_ids = [r[0] for r in q.order_by(GaDeliveryAttempt.created_at.asc()).limit(batch).all()]
        if not candidate_ids:
            return []

        claimed_ids: list[str] = []
        for job_id in candidate_ids:
            # Compare-and-set claim per row for cross-worker safety.
            row = (
                db.query(GaDeliveryAttempt)
                .filter(
                    GaDeliveryAttempt.id == job_id,
                    GaDeliveryAttempt.status.in_(["queued", "retrying", "running"]),
                    available,
                    lease_free,
                )
                .with_for_update(of=GaDeliveryAttempt)
                .one_or_none()
            )
            if row is None:
                continue
            if self.organization_id and row.organization_id != self.organization_id:
                continue
            row.status = "running"
            row.claimed_by = claim_token
            row.claimed_at = now
            row.lease_expires_at = lease_until
            claimed_ids.append(row.id)
        db.flush()
        self.stats["claimed"] += len(claimed_ids)
        if not claimed_ids:
            return []
        return (
            db.query(GaDeliveryAttempt)
            .filter(GaDeliveryAttempt.id.in_(claimed_ids), GaDeliveryAttempt.claimed_by == claim_token)
            .all()
        )

    def process_attempt(self, db: Session, attempt: GaDeliveryAttempt) -> dict[str, Any]:
        from app.core.nova.growth_agent.service import GrowthAgentService

        if REAL_EMAIL_SEND or REAL_SMS_SEND:
            # Belt-and-suspenders: never process if live flags somehow flipped.
            attempt.status = "failed"
            attempt.error_code = "LIVE_SEND_FORBIDDEN"
            attempt.claimed_by = None
            attempt.lease_expires_at = None
            self.stats["failed"] += 1
            return {"id": attempt.id, "status": "failed", "error": "LIVE_SEND_FORBIDDEN", "live_send": False}

        svc = self.service_factory(db) if self.service_factory else GrowthAgentService(db)
        profile = svc._profile(attempt.organization_id)
        if profile is None:
            return self._fail_or_retry(attempt, error_code="PROFILE_MISSING")

        run = (
            db.query(GaWorkflowRun)
            .filter_by(id=attempt.workflow_run_id, organization_id=attempt.organization_id)
            .one_or_none()
        )
        contact = (
            svc._org_query(GaContact, attempt.organization_id)
            .filter_by(id=run.contact_id)
            .one_or_none()
            if run
            else None
        )

        if run is None or contact is None:
            return self._fail_or_retry(attempt, error_code="RUN_OR_CONTACT_MISSING")

        # Quiet hours deferral (does not burn a hard failure).
        quiet = profile.quiet_hours_json or {}
        now = _utcnow()
        if in_quiet_hours(now, quiet, tz_name=profile.timezone or "America/Chicago"):
            nxt = next_send_after_quiet_hours(now, quiet, tz_name=profile.timezone or "America/Chicago")
            attempt.status = "retrying"
            attempt.available_at = nxt.replace(tzinfo=None) if getattr(nxt, "tzinfo", None) else nxt
            attempt.claimed_by = None
            attempt.claimed_at = None
            attempt.lease_expires_at = None
            attempt.error_code = "QUIET_HOURS"
            self.stats["deferred_quiet_hours"] += 1
            return {
                "id": attempt.id,
                "status": "retrying",
                "error": "QUIET_HOURS",
                "available_at": attempt.available_at.isoformat() + "Z" if attempt.available_at else None,
                "live_send": False,
                "mock": True,
            }

        purpose = "transactional"
        wf = (
            db.query(GaWorkflowDefinition)
            .filter_by(id=run.workflow_id, organization_id=attempt.organization_id)
            .one_or_none()
        )
        if wf:
            purpose = wf.purpose or "transactional"

        consents = svc.consent_records_for(attempt.organization_id, contact.id)
        channel = attempt.channel if attempt.channel != "web" else "email"
        try:
            wf_mod.validate_send_allowed(
                purpose=purpose,
                channel=channel,
                consent_records=consents,
                do_not_contact=bool(contact.do_not_contact),
                agent_paused=bool(profile.agent_paused),
                agent_disabled=bool(profile.agent_disabled),
            )
        except (ConsentRequiredError, GrowthAgentError) as exc:
            attempt.status = "suppressed"
            attempt.error_code = getattr(exc, "code", "SUPPRESSED")
            attempt.claimed_by = None
            attempt.claimed_at = None
            attempt.lease_expires_at = None
            attempt.payload_redacted_json = {"reason": str(getattr(exc, "code", "SUPPRESSED"))}
            self.stats["suppressed"] += 1
            if run and run.status not in {"completed", "suppressed"}:
                run.status = "suppressed"
                run.stop_reason = attempt.error_code
            return {
                "id": attempt.id,
                "status": "suppressed",
                "error": attempt.error_code,
                "live_send": False,
                "mock": True,
            }

        body = None
        if isinstance(run.preview_json, dict):
            for msg in run.preview_json.get("messages") or []:
                key = f"{run.id}:{msg.get('step_id')}:{msg.get('channel')}"
                if key == attempt.idempotency_key:
                    body = msg.get("body_preview")
                    break

        try:
            # Already terminal? Duplicate protection.
            if attempt.status == "sent_mock":
                return {"id": attempt.id, "status": "sent_mock", "deduped": True, "live_send": False, "mock": True}

            processed = svc._process_delivery_attempt(
                attempt.organization_id,
                attempt,
                profile=profile,
                channel=attempt.channel,
                body=body,
                dry_run=True,
            )
            attempt.claimed_by = None
            attempt.claimed_at = None
            attempt.lease_expires_at = None
            attempt.available_at = None
            if run and run.status not in {"suppressed"}:
                run.status = "completed"
            self.stats["completed"] += 1
            processed["mock"] = True
            processed["live_send"] = False
            processed["worker_id"] = self.worker_id
            return processed
        except Exception as exc:  # noqa: BLE001
            logger.exception("mock delivery processing failed id=%s", attempt.id)
            return self._fail_or_retry(attempt, error_code=type(exc).__name__)

    def _fail_or_retry(self, attempt: GaDeliveryAttempt, *, error_code: str) -> dict[str, Any]:
        attempt.attempt_number = int(attempt.attempt_number or 1) + 1
        max_attempts = int(attempt.max_attempts or DEFAULT_MAX_ATTEMPTS)
        attempt.error_code = error_code
        attempt.claimed_by = None
        attempt.claimed_at = None
        attempt.lease_expires_at = None
        if attempt.attempt_number >= max_attempts:
            attempt.status = "failed"
            self.stats["failed"] += 1
            return {
                "id": attempt.id,
                "status": "failed",
                "error": error_code,
                "attempt_number": attempt.attempt_number,
                "live_send": False,
                "mock": True,
            }
        delay = _backoff_seconds(attempt.attempt_number)
        attempt.status = "retrying"
        attempt.available_at = _utcnow() + timedelta(seconds=delay)
        self.stats["failed"] += 1
        return {
            "id": attempt.id,
            "status": "retrying",
            "error": error_code,
            "attempt_number": attempt.attempt_number,
            "available_at": attempt.available_at.isoformat() + "Z",
            "live_send": False,
            "mock": True,
        }

    def run_once(self, *, limit: int | None = None) -> dict[str, Any]:
        """Claim and process one batch. Safe to call from tests or HTTP tick."""
        if not background_worker_enabled() and os.getenv("TESTING", "").lower() not in {"1", "true", "yes"}:
            # Still allow explicit recover paths; tick endpoint checks flags separately.
            pass
        db = self.session_factory()
        results: list[dict[str, Any]] = []
        released_on_stop = 0
        try:
            if self._stop.is_set():
                # Ensure no dangling leases remain if stop arrived mid-flight.
                released_on_stop = self.release_held_claims(db)
                self.stats["ticks"] += 1
                db.commit()
                self._heartbeat(status="stopping", db=db)
                return {
                    "worker_id": self.worker_id,
                    "claimed": 0,
                    "processed": 0,
                    "released_on_stop": released_on_stop,
                    "results": [],
                    "stats": dict(self.stats),
                    "live_send": False,
                    "mock_only": True,
                    "organization_id": self.organization_id,
                    "shutdown": True,
                }
            claimed = self.claim_jobs(db, limit=limit)
            for attempt in claimed:
                if self._stop.is_set():
                    # Graceful: release unprocessed claims back to queued.
                    if attempt.status == "running":
                        attempt.status = "queued"
                        attempt.claimed_by = None
                        attempt.claimed_at = None
                        attempt.lease_expires_at = None
                        released_on_stop += 1
                    continue
                results.append(self.process_attempt(db, attempt))
            if self._stop.is_set():
                released_on_stop += self.release_held_claims(db)
            self.stats["ticks"] += 1
            db.commit()
            self._heartbeat(status="running" if not self._stop.is_set() else "stopping", db=db)
            return {
                "worker_id": self.worker_id,
                "claimed": len(claimed),
                "processed": len(results),
                "released_on_stop": released_on_stop,
                "results": results,
                "stats": dict(self.stats),
                "live_send": False,
                "mock_only": True,
                "organization_id": self.organization_id,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def run_loop(self, *, poll_seconds: float = 2.0) -> None:
        self._stop.clear()
        self._heartbeat(status="running")
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("growth mock worker tick failed worker_id=%s", self.worker_id)
            self._stop.wait(max(0.2, float(poll_seconds)))
        self._heartbeat(status="stopped")

    def start_background(self, *, poll_seconds: float = 2.0) -> threading.Thread:
        if self._thread and self._thread.is_alive():
            return self._thread
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run_loop,
            kwargs={"poll_seconds": poll_seconds},
            name=f"nova-ga-mock-worker-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def join(self, timeout: float | None = 5.0) -> None:
        self.request_shutdown()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        # Belt-and-suspenders: release any leases still held if the thread timed out.
        db = self.session_factory()
        try:
            released = self.release_held_claims(db)
            if released:
                db.commit()
            else:
                db.rollback()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception(
                "growth worker failed to release claims on join worker_id=%s", self.worker_id
            )
        finally:
            db.close()
        self._heartbeat(status="stopped")


# Process-global optional runtime (started only when env flag is on).
_RUNTIME_WORKER: MockDeliveryWorker | None = None
_RUNTIME_LOCK = threading.Lock()


def get_runtime_worker() -> MockDeliveryWorker | None:
    return _RUNTIME_WORKER


def start_runtime_worker(session_factory: sessionmaker, *, poll_seconds: float = 2.0) -> MockDeliveryWorker | None:
    global _RUNTIME_WORKER
    if not background_worker_enabled():
        return None
    with _RUNTIME_LOCK:
        if _RUNTIME_WORKER and _RUNTIME_WORKER._thread and _RUNTIME_WORKER._thread.is_alive():
            return _RUNTIME_WORKER
        worker = MockDeliveryWorker(session_factory)
        worker.start_background(poll_seconds=poll_seconds)
        _RUNTIME_WORKER = worker
        logger.info("Nova Growth Agent mock delivery worker started id=%s", worker.worker_id)
        return worker


def stop_runtime_worker(timeout: float = 5.0) -> None:
    global _RUNTIME_WORKER
    with _RUNTIME_LOCK:
        worker = _RUNTIME_WORKER
        _RUNTIME_WORKER = None
    if worker:
        worker.join(timeout=timeout)
        logger.info("Nova Growth Agent mock delivery worker stopped id=%s", worker.worker_id)
