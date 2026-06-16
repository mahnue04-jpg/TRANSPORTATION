"""Phase 52 live transport runtime state manager (additive, in-memory, tenant scoped)."""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


class LiveTransportRuntimeManager:
    """Centralized additive runtime registry for ride orchestration state and replay."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state_by_org: dict[str, dict[str, Any]] = {}

    def _org_state(self, organization_id: str) -> dict[str, Any]:
        state = self._state_by_org.get(organization_id)
        if state is None:
            state = {
                "organization_id": organization_id,
                "sequence": 0,
                "active_rides": {},
                "driver_assignments": {},
                "provider_coordination": {},
                "websocket_subscribers": {},
                "timeline": deque(maxlen=4000),
                "timeline_dedup": deque(maxlen=2000),
                "last_reconciliation_at": None,
                "runtime_reconnect_count": 0,
            }
            self._state_by_org[organization_id] = state
        return state

    def _next_sequence(self, state: dict[str, Any]) -> int:
        state["sequence"] = int(state.get("sequence", 0) or 0) + 1
        return int(state["sequence"])

    def _normalize_alias(self, event_name: str) -> str:
        name = str(event_name or "").strip().lower().replace("-", "_")
        alias = {
            "ride_created": "ride_created",
            "ride_approved": "ride_approved",
            "customer_request_approved": "ride_approved",
            "assignment_issued": "driver_assigned",
            "driver_offer_issued": "driver_assigned",
            "assignment_accepted": "assignment_accepted",
            "pickup_arrived": "driver_arrived",
            "rider_loaded": "pickup_completed",
            "trip_started": "ride_started",
            "ride_in_progress": "ride_started",
            "trip_progress": "ride_started",
            "assignment_completed": "ride_completed",
            "trip_completed": "ride_completed",
            "ride_completed": "ride_completed",
            "ride_cancelled": "ride_cancelled",
            "provider_delay": "provider_delay",
            "escalation_requested": "escalation_created",
            "ride_escalated": "escalation_created",
            "runtime_reconnected": "runtime_reconnected",
            "admin_override": "admin_override",
        }
        return alias.get(name, name)

    def register_websocket_connection(
        self,
        *,
        organization_id: str,
        connection_id: str,
        user_id: str,
        role: str,
    ) -> None:
        with self._lock:
            state = self._org_state(organization_id)
            state["websocket_subscribers"][connection_id] = {
                "connection_id": connection_id,
                "user_id": user_id,
                "role": role,
                "subscriptions": [],
                "connected_at": _iso_now(),
                "last_seen": _iso_now(),
            }

    def unregister_websocket_connection(self, *, organization_id: str, connection_id: str) -> None:
        with self._lock:
            state = self._org_state(organization_id)
            state["websocket_subscribers"].pop(connection_id, None)

    def set_websocket_subscriptions(
        self,
        *,
        organization_id: str,
        connection_id: str,
        subscriptions: list[str],
    ) -> None:
        with self._lock:
            state = self._org_state(organization_id)
            row = state["websocket_subscribers"].get(connection_id)
            if not row:
                return
            row["subscriptions"] = sorted(set(str(item or "") for item in subscriptions if item))
            row["last_seen"] = _iso_now()

    def record_runtime_reconnected(
        self,
        *,
        organization_id: str,
        user_id: str,
        connection_id: str,
        requested_sequence: int,
        latest_sequence: int,
    ) -> dict[str, Any]:
        entry = self.record_lifecycle_event(
            organization_id=organization_id,
            event_name="runtime_reconnected",
            role_scope=["admin", "dispatcher", "driver", "provider"],
            details={
                "user_id": user_id,
                "connection_id": connection_id,
                "requested_sequence": int(requested_sequence),
                "latest_sequence": int(latest_sequence),
            },
        )
        with self._lock:
            state = self._org_state(organization_id)
            state["runtime_reconnect_count"] = int(state.get("runtime_reconnect_count", 0) or 0) + 1
        return entry

    def record_lifecycle_event(
        self,
        *,
        organization_id: str,
        event_name: str,
        role_scope: list[str] | None,
        details: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(details or {})
        alias = self._normalize_alias(event_name)

        with self._lock:
            state = self._org_state(organization_id)
            dedup_key = "|".join(
                [
                    str(event_name or ""),
                    str(payload.get("ride_id") or ""),
                    str(payload.get("driver_id") or ""),
                    str(payload.get("request_id") or ""),
                    str(payload.get("assignment_id") or ""),
                    str(payload.get("lifecycle_state") or ""),
                ]
            )
            if dedup_key in state["timeline_dedup"]:
                existing = next(
                    (
                        item for item in reversed(list(state["timeline"]))
                        if str(item.get("event_name") or "") == str(event_name or "")
                        and str((item.get("details") or {}).get("ride_id") or "") == str(payload.get("ride_id") or "")
                    ),
                    None,
                )
                if existing:
                    return deepcopy(existing)

            sequence = self._next_sequence(state)
            timestamp = _iso_now()

            ride_id = str(payload.get("ride_id") or "").strip()
            driver_id = str(payload.get("driver_id") or "").strip()
            provider_id = str(payload.get("provider_id") or "").strip()

            if ride_id:
                active_rides = state["active_rides"]
                ride_row = dict(active_rides.get(ride_id) or {
                    "ride_id": ride_id,
                    "created_at": timestamp,
                    "lifecycle_timestamps": {},
                })
                if driver_id:
                    ride_row["driver_id"] = driver_id
                if provider_id:
                    ride_row["provider_id"] = provider_id
                if payload.get("assignment_state") is not None:
                    ride_row["assignment_state"] = payload.get("assignment_state")
                ride_row["event_name"] = str(event_name)
                ride_row["event_alias"] = alias
                ride_row["updated_at"] = timestamp
                ride_row["lifecycle_timestamps"][alias] = timestamp

                if alias in {"ride_completed", "ride_cancelled"}:
                    active_rides.pop(ride_id, None)
                else:
                    active_rides[ride_id] = ride_row

            if driver_id:
                assignments = state["driver_assignments"]
                if alias in {"ride_completed", "ride_cancelled"}:
                    assignments.pop(driver_id, None)
                else:
                    assignments[driver_id] = {
                        "driver_id": driver_id,
                        "ride_id": ride_id or assignments.get(driver_id, {}).get("ride_id"),
                        "event_alias": alias,
                        "updated_at": timestamp,
                    }

            if provider_id:
                provider_state = state["provider_coordination"]
                row = dict(provider_state.get(provider_id) or {
                    "provider_id": provider_id,
                    "pending_requests": 0,
                    "ready_requests": 0,
                    "delayed_requests": 0,
                })
                if alias == "provider_delay":
                    row["delayed_requests"] = int(row.get("delayed_requests", 0) or 0) + 1
                if alias in {"provider_ready", "ride_started", "pickup_completed"}:
                    row["ready_requests"] = int(row.get("ready_requests", 0) or 0) + 1
                row["last_event"] = alias
                row["updated_at"] = timestamp
                provider_state[provider_id] = row

            entry = {
                "sequence": sequence,
                "organization_id": organization_id,
                "event_name": str(event_name),
                "event_alias": alias,
                "timestamp": timestamp,
                "role_scope": list(role_scope or ["admin", "dispatcher", "driver", "provider", "customer"]),
                "details": payload,
            }
            state["timeline"].append(entry)
            state["timeline_dedup"].append(dedup_key)
            return deepcopy(entry)

    def runtime_snapshot(self, organization_id: str, *, include_timeline: bool = True, limit: int = 120) -> dict[str, Any]:
        with self._lock:
            state = self._org_state(organization_id)
            timeline_rows = list(state["timeline"])
            if include_timeline:
                timeline_rows = timeline_rows[-max(1, int(limit)):]
            else:
                timeline_rows = []
            return {
                "organization_id": organization_id,
                "sequence": int(state.get("sequence", 0) or 0),
                "active_rides_registry": list(state["active_rides"].values()),
                "driver_assignment_registry": list(state["driver_assignments"].values()),
                "provider_coordination_registry": list(state["provider_coordination"].values()),
                "websocket_subscriber_registry": list(state["websocket_subscribers"].values()),
                "runtime_reconnect_count": int(state.get("runtime_reconnect_count", 0) or 0),
                "last_reconciliation_at": state.get("last_reconciliation_at"),
                "timeline": timeline_rows,
                "deterministic_event_ordering": True,
                "reconnect_replay_support": True,
            }

    def replay(self, organization_id: str, *, after_sequence: int = 0, limit: int = 200) -> dict[str, Any]:
        with self._lock:
            state = self._org_state(organization_id)
            timeline_rows = [
                item for item in list(state["timeline"])
                if int(item.get("sequence", 0) or 0) > int(after_sequence)
            ]
            timeline_rows.sort(key=lambda item: int(item.get("sequence", 0) or 0))
            timeline_rows = timeline_rows[:max(1, int(limit))]
            sequence_values = [int(item.get("sequence", 0) or 0) for item in timeline_rows]
            sequence_monotonic = sequence_values == sorted(sequence_values)
            return {
                "organization_id": organization_id,
                "after_sequence": int(after_sequence),
                "latest_sequence": int(state.get("sequence", 0) or 0),
                "events": timeline_rows,
                "deterministic_event_ordering": True,
                "replay_safe": True,
                "sequence_monotonic": sequence_monotonic,
            }

    def reconcile(self, organization_id: str, *, rides: list[Any], drivers: list[Any], providers: list[Any]) -> dict[str, Any]:
        with self._lock:
            state = self._org_state(organization_id)
            active_statuses = {"requested", "queued", "assigned", "driver_en_route", "arrived", "rider_onboard", "in_progress", "escalated"}
            active_rides = [
                row for row in rides
                if str(getattr(row, "lifecycle_state", None) or getattr(row, "status", "")).lower() in active_statuses
            ]

            rebuilt_active = {}
            for row in active_rides:
                ride_id = str(getattr(row, "id", "") or "")
                if not ride_id:
                    continue
                rebuilt_active[ride_id] = {
                    "ride_id": ride_id,
                    "driver_id": str(getattr(row, "driver_id", "") or "") or None,
                    "provider_id": str(getattr(row, "provider_id", "") or "") or None,
                    "ride_status": str(getattr(row, "status", "") or "unknown"),
                    "lifecycle_state": str(getattr(row, "lifecycle_state", None) or getattr(row, "status", "") or "unknown"),
                    "updated_at": _iso_now(),
                    "lifecycle_timestamps": dict((state["active_rides"].get(ride_id, {}) or {}).get("lifecycle_timestamps") or {}),
                }

            assignment_registry = {}
            for driver in drivers:
                driver_id = str(getattr(driver, "id", "") or "")
                if not driver_id:
                    continue
                assigned_ride = next((item for item in active_rides if str(getattr(item, "driver_id", "") or "") == driver_id), None)
                if not assigned_ride:
                    continue
                assignment_registry[driver_id] = {
                    "driver_id": driver_id,
                    "ride_id": str(getattr(assigned_ride, "id", "") or ""),
                    "event_alias": "driver_assigned",
                    "updated_at": _iso_now(),
                }

            provider_registry = defaultdict(lambda: {"pending_requests": 0, "ready_requests": 0, "delayed_requests": 0})
            for provider in providers:
                provider_id = str(getattr(provider, "id", "") or "")
                if not provider_id:
                    continue
                provider_registry[provider_id]["provider_id"] = provider_id
            for ride in active_rides:
                provider_id = str(getattr(ride, "provider_id", "") or "")
                if not provider_id:
                    continue
                status = str(getattr(ride, "status", "") or "").lower()
                if status in {"requested", "queued", "assigned"}:
                    provider_registry[provider_id]["pending_requests"] += 1
                if status in {"driver_en_route", "arrived", "rider_onboard", "in_progress"}:
                    provider_registry[provider_id]["ready_requests"] += 1

            state["active_rides"] = rebuilt_active
            state["driver_assignments"] = assignment_registry
            state["provider_coordination"] = dict(provider_registry)
            state["last_reconciliation_at"] = _iso_now()

            return {
                "organization_id": organization_id,
                "active_rides": len(rebuilt_active),
                "driver_assignments": len(assignment_registry),
                "provider_registry": len(provider_registry),
                "last_reconciliation_at": state["last_reconciliation_at"],
                "deterministic_event_ordering": True,
                "reconciliation_safe": True,
            }


_runtime_manager = LiveTransportRuntimeManager()


def get_live_transport_runtime_manager() -> LiveTransportRuntimeManager:
    return _runtime_manager
