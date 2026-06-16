"""Centralized ride lifecycle execution engine for live operations.

This module is additive and preserves existing runtime architecture by projecting
canonical lifecycle states onto legacy status values used by existing clients.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    HealthISFDispatchLog,
    HealthISFRide,
    HealthISFRideExecutionAction,
    HealthISFRideStatusHistory,
    RideStatus,
)

CANONICAL_RIDE_STATES: tuple[str, ...] = (
    RideStatus.REQUESTED.value,
    RideStatus.QUEUED.value,
    RideStatus.ASSIGNED.value,
    RideStatus.DRIVER_EN_ROUTE.value,
    RideStatus.ARRIVED.value,
    RideStatus.RIDER_ONBOARD.value,
    RideStatus.IN_PROGRESS.value,
    RideStatus.COMPLETED.value,
    RideStatus.CANCELLED.value,
    RideStatus.FAILED.value,
    RideStatus.ESCALATED.value,
)


def _record_runtime_reject(counter_name: str) -> None:
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        governor = get_runtime_governor()
        getattr(governor, counter_name)()
    except Exception:
        return None

LEGACY_TO_CANONICAL: dict[str, str] = {
    RideStatus.PENDING.value: RideStatus.QUEUED.value,
    RideStatus.ACCEPTED.value: RideStatus.ASSIGNED.value,
    RideStatus.IN_TRANSIT.value: RideStatus.IN_PROGRESS.value,
    RideStatus.COMPLETED.value: RideStatus.COMPLETED.value,
    RideStatus.CANCELLED.value: RideStatus.CANCELLED.value,
}

CANONICAL_TO_LEGACY: dict[str, str] = {
    RideStatus.REQUESTED.value: RideStatus.PENDING.value,
    RideStatus.QUEUED.value: RideStatus.PENDING.value,
    RideStatus.ASSIGNED.value: RideStatus.ACCEPTED.value,
    RideStatus.DRIVER_EN_ROUTE.value: RideStatus.ACCEPTED.value,
    RideStatus.ARRIVED.value: RideStatus.ACCEPTED.value,
    RideStatus.RIDER_ONBOARD.value: RideStatus.IN_TRANSIT.value,
    RideStatus.IN_PROGRESS.value: RideStatus.IN_TRANSIT.value,
    RideStatus.COMPLETED.value: RideStatus.COMPLETED.value,
    RideStatus.CANCELLED.value: RideStatus.CANCELLED.value,
    RideStatus.FAILED.value: RideStatus.CANCELLED.value,
    RideStatus.ESCALATED.value: RideStatus.PENDING.value,
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    RideStatus.REQUESTED.value: {RideStatus.QUEUED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value},
    RideStatus.QUEUED.value: {RideStatus.ASSIGNED.value, RideStatus.CANCELLED.value, RideStatus.ESCALATED.value, RideStatus.FAILED.value},
    RideStatus.ASSIGNED.value: {
        RideStatus.QUEUED.value,
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.CANCELLED.value,
        RideStatus.ESCALATED.value,
        RideStatus.FAILED.value,
    },
    RideStatus.DRIVER_EN_ROUTE.value: {RideStatus.ARRIVED.value, RideStatus.CANCELLED.value, RideStatus.ESCALATED.value, RideStatus.FAILED.value},
    RideStatus.ARRIVED.value: {RideStatus.RIDER_ONBOARD.value, RideStatus.CANCELLED.value, RideStatus.ESCALATED.value, RideStatus.FAILED.value},
    RideStatus.RIDER_ONBOARD.value: {RideStatus.IN_PROGRESS.value, RideStatus.CANCELLED.value, RideStatus.ESCALATED.value, RideStatus.FAILED.value},
    RideStatus.IN_PROGRESS.value: {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.ESCALATED.value, RideStatus.FAILED.value},
    RideStatus.ESCALATED.value: {RideStatus.QUEUED.value, RideStatus.ASSIGNED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value},
    RideStatus.COMPLETED.value: {RideStatus.COMPLETED.value},
    RideStatus.CANCELLED.value: {RideStatus.CANCELLED.value},
    RideStatus.FAILED.value: {RideStatus.FAILED.value, RideStatus.QUEUED.value},
}


import logging

logger = logging.getLogger("app.modules.health_isf.ride_execution_engine")
REPLAY_WINDOW_SECONDS = max(30, int(os.environ.get("HEALTH_ISF_REPLAY_WINDOW_SECONDS", "900")))

class RideLifecycleManager:
    """Lifecycle manager with transition validation and audit-safe actions."""

    @classmethod
    def normalize_state(cls, state: str | None) -> str:
        raw = str(state or "").strip().lower()
        if raw in LEGACY_TO_CANONICAL:
            return LEGACY_TO_CANONICAL[raw]
        if raw in CANONICAL_RIDE_STATES:
            return raw
        return RideStatus.REQUESTED.value

    @classmethod
    def to_legacy_status(cls, canonical_state: str) -> str:
        canonical = cls.normalize_state(canonical_state)
        return CANONICAL_TO_LEGACY.get(canonical, RideStatus.PENDING.value)

    @classmethod
    def validate_transition(cls, current_state: str, target_state: str) -> None:
        current = cls.normalize_state(current_state)
        target = cls.normalize_state(target_state)
        if target not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"Illegal ride transition: '{current}' -> '{target}'")

    @classmethod
    def transition_ride(
        cls,
        db: Session,
        ride: HealthISFRide,
        *,
        target_state: str,
        action_type: str,
        actor_user_id: str | None = None,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
        replay_key: str | None = None,
        event_id: str | None = None,
        sequence_number: int | None = None,
        monotonic_ts: float | None = None,
        source: str | None = None,
    ) -> bool:
        current_state = cls.normalize_state(ride.lifecycle_state or ride.status)
        next_state = cls.normalize_state(target_state)

        # Reject duplicate terminal transitions explicitly
        if current_state in {
            RideStatus.COMPLETED.value,
            RideStatus.CANCELLED.value,
            RideStatus.FAILED.value,
            RideStatus.ESCALATED.value,
        } and current_state == next_state:
            raise ValueError(f"Invalid duplicate terminal transition: '{current_state}' -> '{next_state}'")

        # Same-state transitions are treated as idempotent no-ops.
        if current_state == next_state:
            return False

        # Duplicate/replay protection: event_id, replay_key, sequence_number, monotonic_ts
        if event_id:
            existing_event = db.query(HealthISFRideExecutionAction).filter(
                HealthISFRideExecutionAction.organization_id == ride.organization_id,
                HealthISFRideExecutionAction.event_id == event_id,
                HealthISFRideExecutionAction.action_status == "success",
            ).first()
            if existing_event:
                _record_runtime_reject("record_duplicate_event_reject")
                logger.info({"event": "event_duplicate_rejected", "event_id": event_id, "ride_id": ride.id, "action_type": action_type})
                return False
        if replay_key:
            replayed = db.query(HealthISFRideExecutionAction).filter(
                HealthISFRideExecutionAction.organization_id == ride.organization_id,
                HealthISFRideExecutionAction.replay_key == replay_key,
                HealthISFRideExecutionAction.action_status == "success",
            ).first()
            if replayed:
                _record_runtime_reject("record_replay_event_reject")
                logger.info({"event": "event_replay_rejected", "replay_key": replay_key, "ride_id": ride.id, "action_type": action_type})
                return False
        if sequence_number is not None:
            last_seq = db.query(HealthISFRideExecutionAction).filter(
                HealthISFRideExecutionAction.organization_id == ride.organization_id,
                HealthISFRideExecutionAction.ride_id == ride.id,
                HealthISFRideExecutionAction.action_status == "success",
            ).order_by(HealthISFRideExecutionAction.sequence_number.desc()).first()
            if last_seq and last_seq.sequence_number is not None and sequence_number <= last_seq.sequence_number:
                _record_runtime_reject("record_stale_event_reject")
                logger.info({"event": "event_stale_or_out_of_order_rejected", "sequence_number": sequence_number, "ride_id": ride.id, "action_type": action_type})
                return False
        if monotonic_ts is not None:
            now_ts = time.monotonic()
            # Reject stale/future-skewed events outside replay window bounds.
            if monotonic_ts < (now_ts - REPLAY_WINDOW_SECONDS) or monotonic_ts > (now_ts + REPLAY_WINDOW_SECONDS):
                _record_runtime_reject("record_replay_event_reject")
                logger.info({
                    "event": "event_replay_window_rejected",
                    "monotonic_ts": monotonic_ts,
                    "ride_id": ride.id,
                    "action_type": action_type,
                    "replay_window_seconds": REPLAY_WINDOW_SECONDS,
                })
                return False
            last_ts = db.query(HealthISFRideExecutionAction).filter(
                HealthISFRideExecutionAction.organization_id == ride.organization_id,
                HealthISFRideExecutionAction.ride_id == ride.id,
                HealthISFRideExecutionAction.action_status == "success",
            ).order_by(HealthISFRideExecutionAction.monotonic_ts.desc()).first()
            if last_ts and last_ts.monotonic_ts is not None and monotonic_ts <= last_ts.monotonic_ts:
                _record_runtime_reject("record_stale_event_reject")
                logger.info({"event": "event_stale_or_out_of_order_rejected", "monotonic_ts": monotonic_ts, "ride_id": ride.id, "action_type": action_type})
                return False

        cls.validate_transition(current_state, next_state)

        previous_legacy_status = str(ride.status)
        next_legacy_status = cls.to_legacy_status(next_state)

        ride.lifecycle_state = next_state
        ride.status = next_legacy_status
        ride.last_status_changed_by_user_id = actor_user_id
        ride.updated_at = now()

        if next_state == RideStatus.ASSIGNED.value and not getattr(ride, "assigned_at", None):
            ride.assigned_at = now()
        if next_state == RideStatus.DRIVER_EN_ROUTE.value and not getattr(ride, "enroute_at", None):
            ride.enroute_at = now()
        if next_state == RideStatus.ARRIVED.value and not getattr(ride, "arrived_at", None):
            ride.arrived_at = now()
        if next_state == RideStatus.RIDER_ONBOARD.value and not getattr(ride, "picked_up_at", None):
            ride.picked_up_at = now()
        if next_state == RideStatus.IN_PROGRESS.value and not getattr(ride, "transporting_at", None):
            ride.transporting_at = now()

        if next_state in {
            RideStatus.ASSIGNED.value,
            RideStatus.DRIVER_EN_ROUTE.value,
            RideStatus.ARRIVED.value,
            RideStatus.RIDER_ONBOARD.value,
            RideStatus.IN_PROGRESS.value,
        } and not ride.accepted_at:
            ride.accepted_at = now()

        if next_state in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
            if not ride.completed_at:
                ride.completed_at = now()

        db.add(
            HealthISFRideStatusHistory(
                id=uuid4(),
                ride_id=ride.id,
                from_status=current_state,
                to_status=next_state,
                note=note,
                changed_by_user_id=actor_user_id,
                created_at=now(),
            )
        )
        db.add(
            HealthISFDispatchLog(
                id=uuid4(),
                ride_id=ride.id,
                driver_id=ride.driver_id,
                action=action_type,
                note=note or f"{current_state} -> {next_state} (legacy: {previous_legacy_status} -> {next_legacy_status})",
                acted_by_user_id=actor_user_id,
                created_at=now(),
            )
        )
        db.add(
            HealthISFRideExecutionAction(
                id=uuid4(),
                organization_id=ride.organization_id,
                ride_id=ride.id,
                action_type=action_type,
                from_state=current_state,
                to_state=next_state,
                action_status="success",
                replay_key=replay_key,
                payload=json.dumps(payload or {}, default=str),
                actor_user_id=actor_user_id,
                created_at=now(),
                event_id=event_id or str(uuid4()),
                sequence_number=sequence_number,
                monotonic_ts=monotonic_ts,
                source=source,
            )
        )

        correlation_id = str(
            (payload or {}).get("correlation_id")
            or (payload or {}).get("intent_id")
            or f"ride-{ride.id}-{event_id or replay_key or uuid4()}"
        )
        from app.modules.health_isf.operational_workflow_orchestration import (
            publish_phase16_operational_event,
            record_phase16_workflow_event_audit,
        )

        phase16_payload = {
            "ride_id": str(ride.id),
            "from_state": current_state,
            "to_state": next_state,
            "action_type": action_type,
            "legacy_status": {
                "from": previous_legacy_status,
                "to": next_legacy_status,
            },
            "sequence_number": sequence_number,
            "event_id": event_id,
            "replay_key": replay_key,
            "monotonic_ts": monotonic_ts,
            "source": source,
        }
        record_phase16_workflow_event_audit(
            db,
            organization_id=ride.organization_id,
            event_name="workflow_transition",
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            payload=phase16_payload,
        )

        if next_state == RideStatus.QUEUED.value:
            phase16_event_name = "ride_requested"
        elif next_state == RideStatus.ASSIGNED.value:
            phase16_event_name = "ride_assigned"
        elif next_state == RideStatus.COMPLETED.value:
            phase16_event_name = "ride_completed"
        else:
            phase16_event_name = "ride_updated"

        publish_phase16_operational_event(
            db=db,
            organization_id=ride.organization_id,
            event_name=phase16_event_name,
            payload=phase16_payload,
            correlation_id=correlation_id,
            role_scope=["dispatcher", "driver", "provider", "admin", "staff"],
            source_nonce=str(replay_key or event_id or f"ride-transition:{ride.id}:{next_state}"),
        )
        publish_phase16_operational_event(
            db=db,
            organization_id=ride.organization_id,
            event_name="workflow_transition",
            payload=phase16_payload,
            correlation_id=correlation_id,
            role_scope=["dispatcher", "admin", "staff"],
            source_nonce=str(replay_key or event_id or f"workflow-transition:{ride.id}:{next_state}"),
        )
        return True

    @classmethod
    def mark_action_failure(
        cls,
        db: Session,
        ride: HealthISFRide,
        *,
        action_type: str,
        target_state: str,
        error_message: str,
        actor_user_id: str | None = None,
        replay_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        db.add(
            HealthISFRideExecutionAction(
                id=uuid4(),
                organization_id=ride.organization_id,
                ride_id=ride.id,
                action_type=action_type,
                from_state=cls.normalize_state(ride.lifecycle_state or ride.status),
                to_state=cls.normalize_state(target_state),
                action_status="failed",
                replay_key=replay_key,
                error_message=(error_message or "")[:1024],
                payload=json.dumps(payload or {}, default=str),
                actor_user_id=actor_user_id,
                created_at=now(),
            )
        )
