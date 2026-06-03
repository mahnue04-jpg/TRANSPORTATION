"""
Service layer for real-time operations in Health ISF.
Handles event logging, activity tracking, and concurrent assignment protection.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional, List

from sqlalchemy import and_, desc, delete
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    RealTimeEvent,
    DispatcherActivityLog,
    RideAssignmentLock,
    HealthISFRide,
    HealthISFDriver,
    EventType,
    ActivityAction,
    DispatchEventRetry,
    DispatchDeadLetterEvent,
    DispatchIdempotencyKey,
    OperationalAlertLog,
)
from app.modules.health_isf.operations import (
    get_operational_metrics_registry,
    log_operational_event,
)

logger = logging.getLogger("amicor.health_isf.realtime_service")


class RealTimeEventService:
    """Service for managing real-time events."""
    
    @staticmethod
    def log_event(
        db: Session,
        organization_id: str,
        event_type: EventType,
        payload: dict,
        ride_id: Optional[str] = None,
        driver_id: Optional[str] = None,
        created_by_user_id: Optional[str] = None,
    ) -> RealTimeEvent:
        """Log a real-time event."""
        event = RealTimeEvent(
            id=uuid4(),
            organization_id=organization_id,
            event_type=event_type,
            ride_id=ride_id,
            driver_id=driver_id,
            payload=json.dumps(payload),
            created_by_user_id=created_by_user_id,
            created_at=now(),
        )
        db.add(event)
        db.commit()
        metrics = get_operational_metrics_registry()
        metrics.increment("dispatch.events.persisted")
        metrics.record_event_ts("dispatch_events")
        log_operational_event(
            "dispatch.event.persisted",
            organization_id=organization_id,
            event_type=str(event_type),
            ride_id=ride_id,
            driver_id=driver_id,
            created_by_user_id=created_by_user_id,
        )
        logger.info(f"Logged event: {event_type} for org {organization_id}")
        return event
    
    @staticmethod
    def get_recent_events(
        db: Session,
        organization_id: str,
        limit: int = 100,
        minutes: int = 60,
    ) -> List[RealTimeEvent]:
        """Get recent events for an organization."""
        since = now() - timedelta(minutes=minutes)
        events = db.query(RealTimeEvent).filter(
            and_(
                RealTimeEvent.organization_id == organization_id,
                RealTimeEvent.created_at >= since,
            )
        ).order_by(desc(RealTimeEvent.created_at)).limit(limit).all()
        return events
    
    @staticmethod
    def get_ride_events(
        db: Session,
        ride_id: str,
    ) -> List[RealTimeEvent]:
        """Get all events for a specific ride."""
        events = db.query(RealTimeEvent).filter(
            RealTimeEvent.ride_id == ride_id
        ).order_by(desc(RealTimeEvent.created_at)).all()
        return events
    
    @staticmethod
    def cleanup_old_events(
        db: Session,
        organization_id: str,
        days: int = 7,
    ) -> int:
        """Delete events older than specified days."""
        cutoff = now() - timedelta(days=days)
        result = db.execute(
            delete(RealTimeEvent).where(
                and_(
                    RealTimeEvent.organization_id == organization_id,
                    RealTimeEvent.created_at < cutoff,
                )
            )
        )
        db.commit()
        count = int(getattr(result, "rowcount", 0) or 0)
        logger.info(f"Cleaned up {count} old events for org {organization_id}")
        return count


class ActivityLogService:
    """Service for managing dispatcher activity logs."""
    
    @staticmethod
    def log_activity(
        db: Session,
        organization_id: str,
        action: ActivityAction,
        description: str,
        ride_id: Optional[str] = None,
        driver_id: Optional[str] = None,
        details: Optional[dict] = None,
        actor_user_id: Optional[str] = None,
    ) -> DispatcherActivityLog:
        """Log a dispatcher activity."""
        activity = DispatcherActivityLog(
            id=uuid4(),
            organization_id=organization_id,
            action=action,
            ride_id=ride_id,
            driver_id=driver_id,
            description=description,
            details=json.dumps(details) if details else None,
            actor_user_id=actor_user_id,
            created_at=now(),
        )
        db.add(activity)
        db.commit()
        log_operational_event(
            "dispatcher.activity.logged",
            organization_id=organization_id,
            action=str(action),
            ride_id=ride_id,
            driver_id=driver_id,
            actor_user_id=actor_user_id,
        )
        logger.info(f"Logged activity: {action} for org {organization_id}")
        return activity
    
    @staticmethod
    def get_activity_feed(
        db: Session,
        organization_id: str,
        limit: int = 50,
        skip: int = 0,
        ride_id: Optional[str] = None,
    ) -> tuple[List[DispatcherActivityLog], int]:
        """Get activity feed for an organization with optional ride filter."""
        query = db.query(DispatcherActivityLog).filter(
            DispatcherActivityLog.organization_id == organization_id
        )
        if ride_id:
            query = query.filter(DispatcherActivityLog.ride_id == ride_id)
        
        total = query.count()
        activities = query.order_by(
            desc(DispatcherActivityLog.created_at)
        ).offset(skip).limit(limit).all()
        return activities, total
    
    @staticmethod
    def get_ride_activities(
        db: Session,
        ride_id: str,
    ) -> List[DispatcherActivityLog]:
        """Get all activities for a specific ride."""
        activities = db.query(DispatcherActivityLog).filter(
            DispatcherActivityLog.ride_id == ride_id
        ).order_by(desc(DispatcherActivityLog.created_at)).all()
        return activities
    
    @staticmethod
    def cleanup_old_activities(
        db: Session,
        organization_id: str,
        days: int = 30,
    ) -> int:
        """Delete activities older than specified days."""
        cutoff = now() - timedelta(days=days)
        result = db.execute(
            delete(DispatcherActivityLog).where(
                and_(
                    DispatcherActivityLog.organization_id == organization_id,
                    DispatcherActivityLog.created_at < cutoff,
                )
            )
        )
        db.commit()
        count = int(getattr(result, "rowcount", 0) or 0)
        logger.info(f"Cleaned up {count} old activities for org {organization_id}")
        return count


class ConcurrentAssignmentService:
    """Service for managing concurrent ride assignment protection."""

    _cleanup_lock = threading.Lock()
    _cleanup_cooldown_seconds = 15.0
    _last_cleanup_attempt_monotonic = 0.0
    
    @staticmethod
    def acquire_assignment_lock(
        db: Session,
        ride_id: str,
        user_id: Optional[str] = None,
        lock_duration_seconds: int = 30,
    ) -> Optional[RideAssignmentLock]:
        """Acquire a lock for ride assignment."""
        # Clean up expired locks first
        now_time = now()
        db.query(RideAssignmentLock).filter(
            RideAssignmentLock.expires_at <= now_time
        ).delete()
        
        # Check if lock already exists
        existing_lock = db.query(RideAssignmentLock).filter(
            RideAssignmentLock.ride_id == ride_id
        ).first()
        
        if existing_lock:
            logger.warning(f"Lock already exists for ride {ride_id}")
            return None
        
        # Create new lock
        lock = RideAssignmentLock(
            id=uuid4(),
            ride_id=ride_id,
            locked_by_user_id=user_id,
            locked_at=now_time,
            expires_at=now_time + timedelta(seconds=lock_duration_seconds),
        )
        db.add(lock)
        db.commit()
        logger.info(f"Acquired lock for ride {ride_id}")
        return lock
    
    @staticmethod
    def release_assignment_lock(
        db: Session,
        ride_id: str,
    ) -> bool:
        """Release a lock for ride assignment."""
        lock = db.query(RideAssignmentLock).filter(
            RideAssignmentLock.ride_id == ride_id
        ).first()
        
        if not lock:
            return False
        
        db.delete(lock)
        db.commit()
        logger.info(f"Released lock for ride {ride_id}")
        return True
    
    @staticmethod
    def has_assignment_lock(
        db: Session,
        ride_id: str,
    ) -> bool:
        """Check if ride has an active assignment lock."""
        lock = db.query(RideAssignmentLock).filter(
            and_(
                RideAssignmentLock.ride_id == ride_id,
                RideAssignmentLock.expires_at > now(),
            )
        ).first()
        return lock is not None
    
    @staticmethod
    def validate_ride_version(
        db: Session,
        ride_id: str,
        expected_version: int,
    ) -> bool:
        """Validate ride version for optimistic locking."""
        ride = db.query(HealthISFRide).filter(
            HealthISFRide.id == ride_id
        ).first()
        
        if not ride:
            return False
        
        return ride.version == expected_version
    
    @staticmethod
    def increment_ride_version(
        db: Session,
        ride_id: str,
    ) -> int:
        """Increment ride version for optimistic locking."""
        ride = db.query(HealthISFRide).filter(
            HealthISFRide.id == ride_id
        ).first()
        
        if not ride:
            return -1
        
        ride.version += 1
        db.commit()
        return ride.version
    
    @staticmethod
    def cleanup_expired_locks(db: Session) -> int:
        """Clean up expired locks."""
        return ConcurrentAssignmentService._cleanup_expired_locks_internal(db, force=False)

    @staticmethod
    def _cleanup_expired_locks_internal(db: Session, *, force: bool) -> int:
        if not force:
            now_monotonic = time.monotonic()
            last_attempt = float(getattr(ConcurrentAssignmentService, "_last_cleanup_attempt_monotonic", 0.0) or 0.0)
            cooldown = float(getattr(ConcurrentAssignmentService, "_cleanup_cooldown_seconds", 15.0) or 0.0)
            if cooldown > 0 and (now_monotonic - last_attempt) < cooldown:
                logger.debug("Skipping expired assignment lock cleanup during cooldown window")
                return 0
            if not ConcurrentAssignmentService._cleanup_lock.acquire(blocking=False):
                logger.debug("Skipping expired assignment lock cleanup because another cleanup is active")
                return 0
        else:
            ConcurrentAssignmentService._cleanup_lock.acquire()

        ConcurrentAssignmentService._last_cleanup_attempt_monotonic = time.monotonic()
        now_time = now()
        try:
            result = db.execute(
                delete(RideAssignmentLock).where(
                    RideAssignmentLock.expires_at <= now_time
                )
            )
            db.commit()
            count = int(getattr(result, "rowcount", 0) or 0)
            logger.info(f"Cleaned up {count} expired locks")
            return count
        except OperationalError as exc:
            db.rollback()
            message = str(exc).lower()
            if "database is locked" in message or "database table is locked" in message:
                logger.warning("Expired assignment lock cleanup skipped under SQLite write contention")
                return 0
            raise
        finally:
            ConcurrentAssignmentService._cleanup_lock.release()

    @staticmethod
    def force_cleanup_expired_locks(db: Session) -> int:
        """Run cleanup immediately, bypassing the background cooldown window."""
        return ConcurrentAssignmentService._cleanup_expired_locks_internal(db, force=True)

    @staticmethod
    def get_assignment_lock_details(
        db: Session,
        ride_id: str,
    ) -> Optional[dict]:
        """Return active lock metadata for a ride."""
        lock = db.query(RideAssignmentLock).filter(
            and_(
                RideAssignmentLock.ride_id == ride_id,
                RideAssignmentLock.expires_at > now(),
            )
        ).first()
        if not lock:
            return None
        return {
            "lock_id": lock.id,
            "ride_id": lock.ride_id,
            "locked_by_user_id": lock.locked_by_user_id,
            "locked_at": lock.locked_at,
            "expires_at": lock.expires_at,
            "lock_active": True,
        }

    @staticmethod
    def list_active_assignment_locks(
        db: Session,
        *,
        organization_id: str,
        limit: int = 200,
    ) -> List[dict]:
        """List active assignment locks scoped to an organization."""
        now_time = now()
        rows = (
            db.query(RideAssignmentLock, HealthISFRide)
            .join(HealthISFRide, HealthISFRide.id == RideAssignmentLock.ride_id)
            .filter(
                HealthISFRide.organization_id == organization_id,
                RideAssignmentLock.expires_at > now_time,
            )
            .order_by(desc(RideAssignmentLock.locked_at))
            .limit(limit)
            .all()
        )
        payload: List[dict] = []
        for lock, ride in rows:
            payload.append(
                {
                    "lock_id": lock.id,
                    "ride_id": lock.ride_id,
                    "ride_status": str(getattr(ride, "status", "unknown") or "unknown"),
                    "lifecycle_state": str(getattr(ride, "lifecycle_state", None) or getattr(ride, "status", "unknown") or "unknown"),
                    "passenger_name": str(getattr(ride, "passenger_name", "") or "Unknown passenger"),
                    "locked_by_user_id": lock.locked_by_user_id,
                    "locked_at": lock.locked_at,
                    "expires_at": lock.expires_at,
                    "lock_active": True,
                }
            )
        return payload

    @staticmethod
    def claim_or_refresh_assignment_lock(
        db: Session,
        *,
        ride_id: str,
        user_id: Optional[str],
        lock_duration_seconds: int = 90,
        force: bool = False,
    ) -> Optional[RideAssignmentLock]:
        """Claim or refresh ownership lock for dispatcher coordination."""
        now_time = now()
        db.query(RideAssignmentLock).filter(
            RideAssignmentLock.expires_at <= now_time
        ).delete()

        lock = db.query(RideAssignmentLock).filter(
            RideAssignmentLock.ride_id == ride_id
        ).first()

        if lock:
            if lock.locked_by_user_id == user_id or force:
                lock.locked_by_user_id = user_id
                lock.locked_at = now_time
                lock.expires_at = now_time + timedelta(seconds=max(15, int(lock_duration_seconds)))
                db.commit()
                return lock
            return None

        lock = RideAssignmentLock(
            id=uuid4(),
            ride_id=ride_id,
            locked_by_user_id=user_id,
            locked_at=now_time,
            expires_at=now_time + timedelta(seconds=max(15, int(lock_duration_seconds))),
        )
        db.add(lock)
        db.commit()
        return lock

    @staticmethod
    def handoff_assignment_lock(
        db: Session,
        *,
        ride_id: str,
        from_user_id: Optional[str],
        to_user_id: str,
        lock_duration_seconds: int = 120,
        force: bool = False,
    ) -> Optional[RideAssignmentLock]:
        """Transfer ownership lock to another dispatcher user."""
        now_time = now()
        lock = db.query(RideAssignmentLock).filter(
            and_(
                RideAssignmentLock.ride_id == ride_id,
                RideAssignmentLock.expires_at > now_time,
            )
        ).first()
        if not lock:
            if not force:
                return None
            return ConcurrentAssignmentService.claim_or_refresh_assignment_lock(
                db,
                ride_id=ride_id,
                user_id=to_user_id,
                lock_duration_seconds=lock_duration_seconds,
                force=True,
            )

        if not force and lock.locked_by_user_id not in {from_user_id, to_user_id}:
            return None

        lock.locked_by_user_id = to_user_id
        lock.locked_at = now_time
        lock.expires_at = now_time + timedelta(seconds=max(15, int(lock_duration_seconds)))
        db.commit()
        return lock


class RetryQueueService:
    """Retry queue service for failed real-time dispatch events."""

    @staticmethod
    def enqueue_failed_event(
        db: Session,
        organization_id: str,
        event_type: str,
        payload: dict,
        error_message: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        ride_id: Optional[str] = None,
        driver_id: Optional[str] = None,
        max_attempts: int = 5,
    ) -> DispatchEventRetry:
        if idempotency_key:
            existing = db.query(DispatchEventRetry).filter(
                DispatchEventRetry.idempotency_key == idempotency_key
            ).first()
            if existing:
                existing.organization_id = organization_id
                existing.event_type = event_type
                existing.payload = json.dumps(payload)
                existing.last_error = error_message
                existing.ride_id = ride_id
                existing.driver_id = driver_id
                existing.max_attempts = max_attempts
                existing.updated_at = now()
                if existing.status != "completed":
                    existing.status = "queued"
                    existing.next_retry_at = now()
                db.commit()
                logger.info(
                    "Reused existing dispatch retry event %s for idempotency key %s",
                    existing.id,
                    idempotency_key,
                )
                return existing

        retry_event = DispatchEventRetry(
            id=uuid4(),
            organization_id=organization_id,
            event_type=event_type,
            payload=json.dumps(payload),
            status="queued",
            attempts=0,
            max_attempts=max_attempts,
            next_retry_at=now(),
            last_error=error_message,
            idempotency_key=idempotency_key,
            ride_id=ride_id,
            driver_id=driver_id,
            created_at=now(),
            updated_at=now(),
        )
        db.add(retry_event)
        db.commit()
        logger.warning("Queued failed dispatch event %s (%s)", retry_event.id, event_type)
        return retry_event

    @staticmethod
    def enqueue_retry(
        db: Session,
        ride_id: str,
        organization_id: str,
        operation_type: str,
        max_retries: int = 3,
        payload: Optional[dict] = None,
    ) -> DispatchEventRetry:
        return RetryQueueService.enqueue_failed_event(
            db,
            organization_id=organization_id,
            event_type=operation_type,
            payload=payload or {"ride_id": ride_id, "operation_type": operation_type},
            error_message="manual_retry_requested",
            idempotency_key=f"manual-retry:{organization_id}:{ride_id}:{operation_type}",
            ride_id=ride_id,
            max_attempts=max_retries,
        )

    @staticmethod
    def get_due_events(db: Session, limit: int = 100) -> List[DispatchEventRetry]:
        return db.query(DispatchEventRetry).filter(
            and_(
                DispatchEventRetry.status == "queued",
                DispatchEventRetry.next_retry_at <= now(),
            )
        ).order_by(DispatchEventRetry.next_retry_at.asc()).limit(limit).all()

    @staticmethod
    def mark_retry_success(db: Session, event_id: str) -> bool:
        retry_event = db.query(DispatchEventRetry).filter(DispatchEventRetry.id == event_id).first()
        if not retry_event:
            return False
        retry_event.status = "completed"
        retry_event.updated_at = now()
        db.commit()
        return True

    @staticmethod
    def mark_retry_failure(db: Session, event_id: str, error_message: str) -> bool:
        retry_event = db.query(DispatchEventRetry).filter(DispatchEventRetry.id == event_id).first()
        if not retry_event:
            return False

        retry_event.attempts += 1
        retry_event.last_error = error_message[:1024]
        retry_event.updated_at = now()

        if retry_event.attempts >= retry_event.max_attempts:
            retry_event.status = "dead_letter"
            dead_letter = DispatchDeadLetterEvent(
                id=uuid4(),
                retry_event_id=retry_event.id,
                organization_id=retry_event.organization_id,
                event_type=retry_event.event_type,
                payload=retry_event.payload,
                error_message=retry_event.last_error,
                created_at=now(),
            )
            db.add(dead_letter)
        else:
            retry_event.status = "queued"
            backoff_seconds = min(300, 2 ** retry_event.attempts)
            retry_event.next_retry_at = now() + timedelta(seconds=backoff_seconds)

        db.commit()
        return True

    @staticmethod
    def get_queue_stats(db: Session, organization_id: Optional[str] = None) -> dict:
        query = db.query(DispatchEventRetry)
        dead_letter_query = db.query(DispatchDeadLetterEvent)
        if organization_id:
            query = query.filter(DispatchEventRetry.organization_id == organization_id)
            dead_letter_query = dead_letter_query.filter(DispatchDeadLetterEvent.organization_id == organization_id)

        return {
            "queued": query.filter(DispatchEventRetry.status == "queued").count(),
            "completed": query.filter(DispatchEventRetry.status == "completed").count(),
            "dead_letter": query.filter(DispatchEventRetry.status == "dead_letter").count(),
            "failed": query.filter(
                and_(
                    DispatchEventRetry.status == "queued",
                    DispatchEventRetry.attempts > 0,
                )
            ).count(),
            "dead_letters_total": dead_letter_query.count(),
        }


class IdempotencyService:
    """Idempotency service for dispatch operations and event replay protection."""

    @staticmethod
    def reserve_key(
        db: Session,
        idempotency_key: str,
        scope: str,
        resource_id: Optional[str] = None,
        expires_in_hours: int = 24,
    ) -> bool:
        existing = db.query(DispatchIdempotencyKey).filter(
            DispatchIdempotencyKey.idempotency_key == idempotency_key
        ).first()
        if existing:
            return False

        key = DispatchIdempotencyKey(
            id=uuid4(),
            idempotency_key=idempotency_key,
            scope=scope,
            resource_id=resource_id,
            processed_at=now(),
            expires_at=now() + timedelta(hours=expires_in_hours),
        )
        db.add(key)
        db.commit()
        return True

    @staticmethod
    def get_key(db: Session, idempotency_key: str) -> Optional[DispatchIdempotencyKey]:
        return db.query(DispatchIdempotencyKey).filter(
            DispatchIdempotencyKey.idempotency_key == idempotency_key
        ).first()

    @staticmethod
    def bind_resource(db: Session, idempotency_key: str, resource_id: str) -> bool:
        key = db.query(DispatchIdempotencyKey).filter(
            DispatchIdempotencyKey.idempotency_key == idempotency_key
        ).first()
        if not key:
            return False
        key.resource_id = resource_id
        db.commit()
        return True

    @staticmethod
    def cleanup_expired_keys(db: Session) -> int:
        result = db.execute(
            delete(DispatchIdempotencyKey).where(
                and_(
                    DispatchIdempotencyKey.expires_at.is_not(None),
                    DispatchIdempotencyKey.expires_at <= now(),
                )
            )
        )
        db.commit()
        return int(getattr(result, "rowcount", 0) or 0)


class OperationalAlertService:
    """Persistence for generated operational alerts."""

    @staticmethod
    def _safe_json(raw: Optional[str]) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _merge_payload(base: Optional[dict[str, Any]], incoming: Optional[dict[str, Any]]) -> dict[str, Any]:
        result = dict(base or {})
        for key, value in (incoming or {}).items():
            result[key] = value
        return result

    @staticmethod
    def log_alert(
        db: Session,
        organization_id: str,
        alert_type: str,
        severity: str,
        message: str,
        payload: Optional[dict] = None,
        incident_key: Optional[str] = None,
        target_roles: Optional[list[str]] = None,
        notification_channels: Optional[list[str]] = None,
        deduplicate_open_incident: bool = True,
    ) -> OperationalAlertLog:
        existing: Optional[OperationalAlertLog] = None
        if deduplicate_open_incident and incident_key:
            existing = (
                db.query(OperationalAlertLog)
                .filter(
                    OperationalAlertLog.organization_id == organization_id,
                    OperationalAlertLog.incident_key == incident_key,
                    OperationalAlertLog.alert_state.in_(["open", "acknowledged", "escalated"]),
                    OperationalAlertLog.resolved_at.is_(None),
                )
                .order_by(OperationalAlertLog.created_at.desc())
                .first()
            )

        if existing is not None:
            existing.message = message
            existing.severity = severity
            existing.payload = json.dumps(
                OperationalAlertService._merge_payload(
                    OperationalAlertService._safe_json(existing.payload),
                    payload,
                )
            )
            existing.target_roles_json = json.dumps(list(target_roles or []))
            existing.notification_channels_json = json.dumps(list(notification_channels or []))
            existing.last_seen_at = now()
            existing.occurrence_count = int(existing.occurrence_count or 0) + 1
            if str(existing.alert_state or "").lower() == "resolved":
                existing.alert_state = "open"
                existing.resolved_at = None
            db.commit()
            db.refresh(existing)
            return existing

        alert = OperationalAlertLog(
            id=uuid4(),
            organization_id=organization_id,
            alert_type=alert_type,
            severity=severity,
            alert_state="open",
            incident_key=incident_key,
            escalation_level=0,
            target_roles_json=json.dumps(list(target_roles or [])),
            notification_channels_json=json.dumps(list(notification_channels or [])),
            escalation_chain_json=json.dumps([]),
            occurrence_count=1,
            message=message,
            payload=json.dumps(payload) if payload else None,
            last_seen_at=now(),
            created_at=now(),
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert

    @staticmethod
    def list_alert_history(
        db: Session,
        organization_id: str,
        state: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 200,
    ) -> list[OperationalAlertLog]:
        query = db.query(OperationalAlertLog).filter(OperationalAlertLog.organization_id == organization_id)
        if state:
            query = query.filter(OperationalAlertLog.alert_state == state)
        if severity:
            query = query.filter(OperationalAlertLog.severity == severity)
        return query.order_by(OperationalAlertLog.created_at.desc()).limit(max(1, min(limit, 1000))).all()

    @staticmethod
    def acknowledge_alert(
        db: Session,
        organization_id: str,
        alert_id: str,
        acknowledged_by_user_id: Optional[str],
    ) -> Optional[OperationalAlertLog]:
        alert = (
            db.query(OperationalAlertLog)
            .filter(
                OperationalAlertLog.organization_id == organization_id,
                OperationalAlertLog.id == alert_id,
            )
            .first()
        )
        if alert is None:
            return None
        alert.alert_state = "acknowledged"
        alert.acknowledged_by_user_id = acknowledged_by_user_id
        alert.acknowledged_at = now()
        alert.last_seen_at = now()
        db.commit()
        db.refresh(alert)
        return alert

    @staticmethod
    def resolve_alert(
        db: Session,
        organization_id: str,
        alert_id: str,
        resolved_by_user_id: Optional[str],
        resolution_note: Optional[str] = None,
    ) -> Optional[OperationalAlertLog]:
        alert = (
            db.query(OperationalAlertLog)
            .filter(
                OperationalAlertLog.organization_id == organization_id,
                OperationalAlertLog.id == alert_id,
            )
            .first()
        )
        if alert is None:
            return None

        payload = OperationalAlertService._safe_json(alert.payload)
        payload["resolved_by_user_id"] = resolved_by_user_id
        payload["resolution_note"] = resolution_note

        alert.payload = json.dumps(payload)
        alert.alert_state = "resolved"
        alert.resolved_at = now()
        alert.last_seen_at = now()
        db.commit()
        db.refresh(alert)
        return alert

    @staticmethod
    def escalate_alert(
        db: Session,
        organization_id: str,
        alert_id: str,
        escalated_by_user_id: Optional[str],
        summary: Optional[str] = None,
    ) -> Optional[OperationalAlertLog]:
        alert = (
            db.query(OperationalAlertLog)
            .filter(
                OperationalAlertLog.organization_id == organization_id,
                OperationalAlertLog.id == alert_id,
            )
            .first()
        )
        if alert is None:
            return None

        chain_raw = OperationalAlertService._safe_json(alert.escalation_chain_json)
        chain_entries = list(chain_raw.get("entries") or []) if isinstance(chain_raw, dict) else []
        chain_entries.append(
            {
                "escalated_at": now().isoformat(),
                "escalated_by_user_id": escalated_by_user_id,
                "summary": summary or "manual_escalation",
                "new_level": int(alert.escalation_level or 0) + 1,
            }
        )

        alert.escalation_level = int(alert.escalation_level or 0) + 1
        alert.alert_state = "escalated"
        alert.escalated_at = now()
        alert.last_seen_at = now()
        alert.escalation_chain_json = json.dumps({"entries": chain_entries})
        db.commit()
        db.refresh(alert)
        return alert
