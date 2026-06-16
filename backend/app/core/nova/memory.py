from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_STATE: dict[str, Any] = {
    "current_build_phase": "MVP stabilization and enterprise orchestration",
    "active_module": "health_isf",
    "last_completed_milestone": "AI voice dispatch and autonomous operations layer",
    "next_recommended_step": "Embed Mr. Nova advisory workflows into daily operations",
    "founder_priorities": [
        "Protect existing workflows",
        "Improve operational intelligence",
        "Ship production-safe increments",
    ],
    "business_setup_status": "foundation-in-progress",
    "deployment_readiness_status": "staging-validation-pending",
    "updated_at": "",
}


def _default_memory_fabric() -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "founder_continuity": [],
        "operational_history": [],
        "workflow_history": [],
        "unresolved_priorities": [],
        "deployment_state": {
            "status": "staging-validation-pending",
            "last_updated_at": now_iso,
        },
        "operational_risks": [],
        "recent_execution_history": [],
        "recommendation_history": [],
        "execution_timeline": [],
        "operational_event_timeline": [],
        "pending_actions": [],  # Nova approval-safe actions
        "business_state": {
            "objectives": [],
            "kpis": {},
            "active_initiatives": [],
            "last_reviewed_at": now_iso,
        },
        "agent_specializations": {
            "nova_founder_advisor": {
                "scope": "founder continuity and strategic execution",
                "status": "active",
            },
            "nova_operations_commander": {
                "scope": "operational risk and workflow triage",
                "status": "active",
            },
            "nova_dispatch_supervisor": {
                "scope": "dispatch recommendations and workload balance",
                "status": "active",
            },
        },
        "session_stability": {
            "heartbeat_count": 0,
            "last_heartbeat_at": None,
            "last_status": "idle",
            "last_session_id": None,
        },
        "updated_at": now_iso,
    }


class NovaMemoryStore:
    """Safe local structured memory for Nova, isolated per organization."""

    def __init__(self, path: str | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[3]
        default_path = base_dir / "data" / "nova_memory.json"
        self.path = Path(path) if path else default_path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"organizations": {}}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return {"organizations": {}}
        if not isinstance(payload, dict):
            return {"organizations": {}}
        payload.setdefault("organizations", {})
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        try:
            os.replace(temp_path, self.path)
        except PermissionError:
            # OneDrive/Windows can briefly lock the destination; fall back to direct write.
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            if temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except PermissionError:
                    # Non-critical cleanup failure; temp file will be overwritten on a later write.
                    pass

    def _ensure_state_shape(self, state: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(state or {})
        for key, value in DEFAULT_MEMORY_STATE.items():
            normalized.setdefault(key, value)
        normalized.setdefault("updated_at", self._now())

        memory_fabric = normalized.get("memory_fabric")
        if not isinstance(memory_fabric, dict):
            memory_fabric = _default_memory_fabric()
        else:
            defaults = _default_memory_fabric()
            for key, value in defaults.items():
                memory_fabric.setdefault(key, value)
            if not isinstance(memory_fabric.get("founder_continuity"), list):
                memory_fabric["founder_continuity"] = []
            if not isinstance(memory_fabric.get("operational_history"), list):
                memory_fabric["operational_history"] = []
            if not isinstance(memory_fabric.get("workflow_history"), list):
                memory_fabric["workflow_history"] = []
            if not isinstance(memory_fabric.get("unresolved_priorities"), list):
                memory_fabric["unresolved_priorities"] = []
            if not isinstance(memory_fabric.get("deployment_state"), dict):
                memory_fabric["deployment_state"] = defaults["deployment_state"]
            if not isinstance(memory_fabric.get("operational_risks"), list):
                memory_fabric["operational_risks"] = []
            if not isinstance(memory_fabric.get("recent_execution_history"), list):
                memory_fabric["recent_execution_history"] = []
            if not isinstance(memory_fabric.get("recommendation_history"), list):
                memory_fabric["recommendation_history"] = []
            if not isinstance(memory_fabric.get("execution_timeline"), list):
                memory_fabric["execution_timeline"] = []
            if not isinstance(memory_fabric.get("operational_event_timeline"), list):
                memory_fabric["operational_event_timeline"] = []
            if not isinstance(memory_fabric.get("pending_actions"), list):
                memory_fabric["pending_actions"] = []
            if not isinstance(memory_fabric.get("business_state"), dict):
                memory_fabric["business_state"] = defaults["business_state"]
            if not isinstance(memory_fabric.get("agent_specializations"), dict):
                memory_fabric["agent_specializations"] = defaults["agent_specializations"]
            if not isinstance(memory_fabric.get("session_stability"), dict):
                memory_fabric["session_stability"] = defaults["session_stability"]
            memory_fabric["updated_at"] = self._now()

        normalized["memory_fabric"] = memory_fabric
        return normalized

    def read(self, organization_id: str) -> dict[str, Any]:
        org_key = str(organization_id or "global")
        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            if org_key not in org_map:
                state = self._ensure_state_shape(dict(DEFAULT_MEMORY_STATE))
                state["updated_at"] = self._now()
                org_map[org_key] = state
                self._save(payload)
            state = self._ensure_state_shape(dict(org_map[org_key]))
            org_map[org_key] = state
            return state

    def write(self, organization_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        org_key = str(organization_id or "global")
        safe_patch = dict(patch or {})
        safe_patch.pop("organization_id", None)

        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            current = self._ensure_state_shape(dict(org_map.get(org_key) or DEFAULT_MEMORY_STATE))
            current.update(safe_patch)
            current["updated_at"] = self._now()
            org_map[org_key] = current
            self._save(payload)
            return dict(current)

    def read_fabric(self, organization_id: str) -> dict[str, Any]:
        state = self.read(organization_id)
        return dict(state.get("memory_fabric") or _default_memory_fabric())

    def append_event(
        self,
        organization_id: str,
        channel: str,
        event: dict[str, Any],
        *,
        max_items: int = 400,
    ) -> dict[str, Any]:
        org_key = str(organization_id or "global")
        channel_key = str(channel or "operational_history").strip().lower()
        if channel_key not in {"founder_continuity", "operational_history", "workflow_history"}:
            channel_key = "operational_history"

        safe_event = dict(event or {})
        safe_event.setdefault("at", self._now())

        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            current = self._ensure_state_shape(dict(org_map.get(org_key) or DEFAULT_MEMORY_STATE))
            fabric = dict(current.get("memory_fabric") or _default_memory_fabric())
            entries = list(fabric.get(channel_key) or [])

            correlation_id = str(safe_event.get("correlation_id") or "").strip()
            event_type = str(safe_event.get("event_type") or "").strip().lower()
            if correlation_id and event_type:
                for existing in entries[:50]:
                    if str(existing.get("correlation_id") or "").strip() == correlation_id and str(existing.get("event_type") or "").strip().lower() == event_type:
                        return existing

            entries.insert(0, safe_event)
            fabric[channel_key] = entries[: max(10, int(max_items))]

            execution_history = list(fabric.get("recent_execution_history") or [])
            execution_history.insert(0, {
                "event_type": safe_event.get("event_type"),
                "summary": safe_event.get("summary"),
                "source": safe_event.get("source"),
                "at": safe_event.get("at"),
                "correlation_id": safe_event.get("correlation_id"),
            })
            fabric["recent_execution_history"] = execution_history[:120]

            raw_metadata = safe_event.get("metadata")
            metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
            stage = str(metadata.get("stage") or safe_event.get("event_type") or "event")
            timeline = list(fabric.get("execution_timeline") or [])
            timeline.insert(0, {
                "timestamp": safe_event.get("at"),
                "event_type": safe_event.get("event_type"),
                "stage": stage,
                "summary": safe_event.get("summary"),
                "failure_reason": metadata.get("failure_reason") or metadata.get("error") or None,
                "recovery_attempt": metadata.get("recovery_attempt") or None,
                "deployment_change": metadata.get("deployment_change") or None,
                "recommendation": metadata.get("recommended_action") or metadata.get("suggested_action") or None,
                "correlation_id": safe_event.get("correlation_id"),
            })
            fabric["execution_timeline"] = timeline[:200]

            text = str(safe_event.get("summary") or "").lower()
            if "risk" in text or "incident" in event_type or "alert" in event_type:
                risks = list(fabric.get("operational_risks") or [])
                risks.insert(0, {
                    "summary": safe_event.get("summary"),
                    "event_type": safe_event.get("event_type"),
                    "at": safe_event.get("at"),
                    "severity": metadata.get("severity") or "watch",
                })
                fabric["operational_risks"] = risks[:80]

            fabric["updated_at"] = self._now()
            current["memory_fabric"] = fabric
            current["updated_at"] = self._now()
            org_map[org_key] = current
            self._save(payload)
            return safe_event

    def update_business_state(self, organization_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        org_key = str(organization_id or "global")
        safe_patch = dict(patch or {})

        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            current = self._ensure_state_shape(dict(org_map.get(org_key) or DEFAULT_MEMORY_STATE))
            fabric = dict(current.get("memory_fabric") or _default_memory_fabric())
            business = dict(fabric.get("business_state") or {})
            business.update(safe_patch)
            business["last_reviewed_at"] = self._now()
            fabric["business_state"] = business
            objectives = safe_patch.get("objectives")
            if isinstance(objectives, list):
                fabric["unresolved_priorities"] = [str(item).strip() for item in objectives if str(item).strip()][:30]
            fabric["updated_at"] = self._now()
            current["memory_fabric"] = fabric
            current["updated_at"] = self._now()
            org_map[org_key] = current
            self._save(payload)
            return business

    def add_recommendations(self, organization_id: str, recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        org_key = str(organization_id or "global")
        items = [dict(item or {}) for item in (recommendations or [])]
        if not items:
            return []

        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            current = self._ensure_state_shape(dict(org_map.get(org_key) or DEFAULT_MEMORY_STATE))
            fabric = dict(current.get("memory_fabric") or _default_memory_fabric())
            history = list(fabric.get("recommendation_history") or [])
            now_iso = self._now()
            for rec in items:
                stamped = dict(rec)
                stamped.setdefault("timestamp", now_iso)
                history.insert(0, stamped)
            fabric["recommendation_history"] = history[:200]
            fabric["updated_at"] = now_iso
            current["memory_fabric"] = fabric
            current["updated_at"] = now_iso
            org_map[org_key] = current
            self._save(payload)
            return items

    def update_deployment_state(self, organization_id: str, status: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        org_key = str(organization_id or "global")
        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            current = self._ensure_state_shape(dict(org_map.get(org_key) or DEFAULT_MEMORY_STATE))
            fabric = dict(current.get("memory_fabric") or _default_memory_fabric())
            deployment_state = dict(fabric.get("deployment_state") or {})
            deployment_state["status"] = str(status or deployment_state.get("status") or "watch")
            deployment_state["last_updated_at"] = self._now()
            if metadata and isinstance(metadata, dict):
                deployment_state["metadata"] = dict(metadata)
            fabric["deployment_state"] = deployment_state
            fabric["updated_at"] = self._now()
            current["memory_fabric"] = fabric
            current["updated_at"] = self._now()
            org_map[org_key] = current
            self._save(payload)
            return deployment_state

    def heartbeat(self, organization_id: str, session_id: str | None, status: str | None) -> dict[str, Any]:
        org_key = str(organization_id or "global")
        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            current = self._ensure_state_shape(dict(org_map.get(org_key) or DEFAULT_MEMORY_STATE))
            fabric = dict(current.get("memory_fabric") or _default_memory_fabric())
            stability = dict(fabric.get("session_stability") or {})
            stability["heartbeat_count"] = int(stability.get("heartbeat_count") or 0) + 1
            stability["last_heartbeat_at"] = self._now()
            stability["last_status"] = str(status or "active")
            stability["last_session_id"] = str(session_id) if session_id else stability.get("last_session_id")
            fabric["session_stability"] = stability
            fabric["updated_at"] = self._now()
            current["memory_fabric"] = fabric
            current["updated_at"] = self._now()
            org_map[org_key] = current
            self._save(payload)
            return stability

    def append_operational_events(
        self,
        organization_id: str,
        events: list[dict[str, Any]],
        *,
        max_items: int = 400,
    ) -> list[dict[str, Any]]:
        org_key = str(organization_id or "global")
        incoming = [dict(item or {}) for item in (events or [])]
        if not incoming:
            return []

        with self._lock:
            payload = self._load()
            org_map = payload.setdefault("organizations", {})
            current = self._ensure_state_shape(dict(org_map.get(org_key) or DEFAULT_MEMORY_STATE))
            fabric = dict(current.get("memory_fabric") or _default_memory_fabric())
            timeline = list(fabric.get("operational_event_timeline") or [])

            existing_keys = set()
            for item in timeline[:300]:
                event_id = str(item.get("event_id") or "").strip()
                event_type = str(item.get("event_type") or "").strip()
                correlation = str(item.get("correlation_id") or "").strip()
                if event_id:
                    existing_keys.add("id|" + event_id)
                if event_type and correlation:
                    existing_keys.add("corr|" + event_type + "|" + correlation)

            persisted: list[dict[str, Any]] = []
            for item in incoming:
                stamped = dict(item)
                stamped.setdefault("timestamp", self._now())
                stamped.setdefault("event_id", f"event:{stamped.get('event_type') or 'unknown'}:{stamped.get('timestamp')}")

                event_id = str(stamped.get("event_id") or "").strip()
                event_type = str(stamped.get("event_type") or "").strip()
                correlation = str(stamped.get("correlation_id") or "").strip()

                id_key = "id|" + event_id if event_id else ""
                corr_key = "corr|" + event_type + "|" + correlation if event_type and correlation else ""

                if (id_key and id_key in existing_keys) or (corr_key and corr_key in existing_keys):
                    continue

                if id_key:
                    existing_keys.add(id_key)
                if corr_key:
                    existing_keys.add(corr_key)

                timeline.insert(0, stamped)
                persisted.append(stamped)

            if not persisted:
                return []

            fabric["operational_event_timeline"] = timeline[: max(20, int(max_items))]
            fabric["updated_at"] = self._now()
            current["memory_fabric"] = fabric
            current["updated_at"] = self._now()
            org_map[org_key] = current
            self._save(payload)
            return persisted

    def read_operational_events(self, organization_id: str, *, limit: int = 60) -> list[dict[str, Any]]:
        fabric = self.read_fabric(organization_id)
        timeline = list(fabric.get("operational_event_timeline") or [])
        return timeline[: max(1, int(limit))]


memory_store = NovaMemoryStore()
