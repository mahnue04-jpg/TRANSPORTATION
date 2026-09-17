"""Simulated Home Hub power-state contract.

Software-only. Does not imply a physical battery, UPS hardware, or cellular
failover is installed. Prototype backup is modeled as an external UPS concept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.helpers import now

POWER_MAINS = "MAINS_POWER"
POWER_BACKUP = "BACKUP_POWER"
POWER_LOW = "LOW_BATTERY"
POWER_SHUTDOWN = "SHUTDOWN_PENDING"
POWER_OFFLINE = "OFFLINE"
POWER_RESTORING = "RESTORING"
POWER_NORMAL = "NORMAL"

POWER_STATES = frozenset({
    POWER_MAINS,
    POWER_BACKUP,
    POWER_LOW,
    POWER_SHUTDOWN,
    POWER_OFFLINE,
    POWER_RESTORING,
    POWER_NORMAL,
})

# MAINS_POWER is the default healthy AC state. NORMAL is the post-recovery
# healthy state. Both are virtual AC-present states — not a physical battery.
HEALTHY_AC_STATES = frozenset({POWER_MAINS, POWER_NORMAL})

EVENT_POWER_LOSS = "POWER_LOSS"
EVENT_BACKUP_ACTIVE = "BACKUP_POWER_ACTIVE"
EVENT_LOW_BATTERY = "LOW_BATTERY"
EVENT_SHUTDOWN_WARNING = "SHUTDOWN_WARNING"
EVENT_POWER_RESTORED = "POWER_RESTORED"
EVENT_SYSTEM_RECOVERED = "SYSTEM_RECOVERED"

POWER_EVENTS = frozenset({
    EVENT_POWER_LOSS,
    EVENT_BACKUP_ACTIVE,
    EVENT_LOW_BATTERY,
    EVENT_SHUTDOWN_WARNING,
    EVENT_POWER_RESTORED,
    EVENT_SYSTEM_RECOVERED,
})

CMD_SET_POWER_STATE = "SET_POWER_STATE"
POWER_COMMAND_TARGETS = {
    CMD_SET_POWER_STATE: None,
    "SIMULATE_POWER_LOSS": POWER_BACKUP,
    "SIMULATE_LOW_BATTERY": POWER_LOW,
    "SIMULATE_SHUTDOWN_WARNING": POWER_SHUTDOWN,
    "SIMULATE_POWER_RESTORE": POWER_RESTORING,
    "SIMULATE_SYSTEM_RECOVER": POWER_NORMAL,
}
POWER_COMMANDS = frozenset(POWER_COMMAND_TARGETS)

_ALIASES = {
    "MAINS": POWER_MAINS,
    "MAINS_POWER": POWER_MAINS,
    "AC": POWER_MAINS,
    "NORMAL": POWER_NORMAL,
    "BATTERY": POWER_BACKUP,
    "BACKUP": POWER_BACKUP,
    "BACKUP_POWER": POWER_BACKUP,
    "UPS": POWER_BACKUP,
    "LOW": POWER_LOW,
    "LOW_BATTERY": POWER_LOW,
    "SHUTDOWN": POWER_SHUTDOWN,
    "SHUTDOWN_PENDING": POWER_SHUTDOWN,
    "OFFLINE": POWER_OFFLINE,
    "RESTORING": POWER_RESTORING,
    "RESTORE": POWER_RESTORING,
}

# Directed software transitions. Same-state is a duplicate, not invalid.
_ALLOWED = frozenset({
    (POWER_MAINS, POWER_BACKUP),
    (POWER_NORMAL, POWER_BACKUP),
    (POWER_BACKUP, POWER_LOW),
    (POWER_LOW, POWER_SHUTDOWN),
    (POWER_BACKUP, POWER_RESTORING),
    (POWER_LOW, POWER_RESTORING),
    (POWER_SHUTDOWN, POWER_RESTORING),
    (POWER_RESTORING, POWER_NORMAL),
    (POWER_MAINS, POWER_OFFLINE),
    (POWER_NORMAL, POWER_OFFLINE),
    (POWER_BACKUP, POWER_OFFLINE),
    (POWER_LOW, POWER_OFFLINE),
    (POWER_SHUTDOWN, POWER_OFFLINE),
    (POWER_RESTORING, POWER_OFFLINE),
    (POWER_OFFLINE, POWER_RESTORING),
    (POWER_OFFLINE, POWER_MAINS),
    (POWER_NORMAL, POWER_MAINS),
})

_EVENTS_FOR_TARGET = {
    POWER_BACKUP: (EVENT_POWER_LOSS, EVENT_BACKUP_ACTIVE),
    POWER_LOW: (EVENT_LOW_BATTERY,),
    POWER_SHUTDOWN: (EVENT_SHUTDOWN_WARNING,),
    POWER_RESTORING: (EVENT_POWER_RESTORED,),
    POWER_NORMAL: (EVENT_SYSTEM_RECOVERED,),
}

PHYSICAL_BATTERY_CONNECTED = False
POWER_SOURCE_KIND = "simulated_external_ups"
POWER_LABEL = (
    "SIMULATED virtual power state. No physical battery is connected. "
    "First-prototype backup is modeled as an external UPS / external backup-power concept."
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def normalize_power_state(raw: str | None) -> str | None:
    if raw is None:
        return None
    token = str(raw).strip().upper().replace("-", "_").replace(" ", "_")
    if not token:
        return None
    if token in POWER_STATES:
        return token
    return _ALIASES.get(token)


def current_power_state(state: dict[str, Any] | None) -> str:
    state = state or {}
    named = normalize_power_state(state.get("power_state"))
    if named:
        return named
    legacy = normalize_power_state(state.get("power"))
    return legacy or POWER_MAINS


def legacy_power_token(power_state: str) -> str:
    if power_state in HEALTHY_AC_STATES or power_state == POWER_RESTORING:
        return "mains"
    if power_state == POWER_OFFLINE:
        return "offline"
    return "backup"


def events_for_transition(from_state: str, to_state: str) -> tuple[str, ...]:
    if from_state == to_state:
        return ()
    return _EVENTS_FOR_TARGET.get(to_state, ())


@dataclass
class PowerTransitionResult:
    from_state: str
    to_state: str
    applied: bool
    duplicate: bool = False
    stale: bool = False
    invalid: bool = False
    reason: str = ""
    events: tuple[str, ...] = field(default_factory=tuple)
    event_at: datetime | None = None
    physical_battery_connected: bool = PHYSICAL_BATTERY_CONNECTED
    simulated: bool = True
    label: str = POWER_LABEL

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "applied": self.applied,
            "duplicate": self.duplicate,
            "stale": self.stale,
            "invalid": self.invalid,
            "reason": self.reason,
            "events": list(self.events),
            "event_at": self.event_at.isoformat() if self.event_at else None,
            "physical_battery_connected": False,
            "simulated": True,
            "power_source_kind": POWER_SOURCE_KIND,
            "label": POWER_LABEL,
        }


def evaluate_transition(
    current: str | None,
    target: str | None,
    *,
    event_at: datetime | None = None,
    last_transition_at: datetime | None = None,
) -> PowerTransitionResult:
    current_state = normalize_power_state(current) or POWER_MAINS
    target_state = normalize_power_state(target)
    stamped = _aware(event_at) or now()
    last_at = _aware(last_transition_at)

    if target_state is None:
        return PowerTransitionResult(
            from_state=current_state,
            to_state=str(target or ""),
            applied=False,
            invalid=True,
            reason="Unknown power state.",
            event_at=stamped,
        )
    if last_at is not None and stamped < last_at:
        return PowerTransitionResult(
            from_state=current_state,
            to_state=target_state,
            applied=False,
            stale=True,
            reason="Stale power event is older than the last recorded transition.",
            event_at=stamped,
        )
    if target_state == current_state:
        return PowerTransitionResult(
            from_state=current_state,
            to_state=target_state,
            applied=False,
            duplicate=True,
            reason="Power state is already at the requested value.",
            event_at=stamped,
        )
    if (current_state, target_state) not in _ALLOWED:
        return PowerTransitionResult(
            from_state=current_state,
            to_state=target_state,
            applied=False,
            invalid=True,
            reason=f"Invalid power transition {current_state} -> {target_state}.",
            event_at=stamped,
        )
    return PowerTransitionResult(
        from_state=current_state,
        to_state=target_state,
        applied=True,
        events=events_for_transition(current_state, target_state),
        event_at=stamped,
        reason=f"Simulated transition {current_state} -> {target_state}.",
    )


def apply_to_state(
    state: dict[str, Any],
    result: PowerTransitionResult,
) -> dict[str, Any]:
    """Write virtual power fields. Never sets physical_battery_connected true."""
    if result.applied:
        state["power_state"] = result.to_state
        state["power"] = legacy_power_token(result.to_state)
        transition = {
            "from_state": result.from_state,
            "to_state": result.to_state,
            "events": list(result.events),
            "at": result.event_at.isoformat() if result.event_at else None,
            "simulated": True,
            "physical_battery_connected": False,
            "label": POWER_LABEL,
        }
        state["last_power_transition"] = transition
        history = list(state.get("power_event_log") or [])
        history.append(transition)
        state["power_event_log"] = history[-20:]
    state["physical_battery_connected"] = False
    state["power_simulated"] = True
    state["power_source_kind"] = POWER_SOURCE_KIND
    state["power_label"] = POWER_LABEL
    state["_power_transition"] = result.as_dict()
    return state


def ensure_power_fields(state: dict[str, Any]) -> dict[str, Any]:
    current = current_power_state(state)
    state.setdefault("power_state", current)
    state.setdefault("power", legacy_power_token(current))
    state["physical_battery_connected"] = False
    state["power_simulated"] = True
    state["power_source_kind"] = POWER_SOURCE_KIND
    state.setdefault("power_label", POWER_LABEL)
    return state


def snapshot(state: dict[str, Any] | None) -> dict[str, Any]:
    state = ensure_power_fields(dict(state or {}))
    current = current_power_state(state)
    last = state.get("last_power_transition") if isinstance(state.get("last_power_transition"), dict) else None
    return {
        "power_state": current,
        "power_status": current,
        "power": legacy_power_token(current),
        "last_power_transition": last,
        "physical_battery_connected": False,
        "power_simulated": True,
        "power_source_kind": POWER_SOURCE_KIND,
        "power_label": POWER_LABEL,
    }


def device_status_for(power_state: str, *, privacy: bool, previous_status: str | None = None) -> str | None:
    """Map virtual power to existing device status names. None = leave unchanged."""
    if power_state == POWER_OFFLINE:
        return "OFFLINE"
    if power_state == POWER_SHUTDOWN:
        return "MAINTENANCE"
    if power_state in {POWER_BACKUP, POWER_LOW}:
        return "DEGRADED"
    if previous_status == "OFFLINE" and power_state in HEALTHY_AC_STATES | {POWER_RESTORING}:
        return "PRIVACY_MODE" if privacy else "ONLINE"
    return None
