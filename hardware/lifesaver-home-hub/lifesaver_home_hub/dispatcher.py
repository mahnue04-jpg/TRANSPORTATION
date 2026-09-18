"""Command dispatcher. Shared Lifesaver vocabulary. STOP always wins."""
from __future__ import annotations

from typing import Any

from lifesaver_home_hub.emulator import VEHICLE_FORBIDDEN, HomeHubEmulator
from lifesaver_home_hub.safety import COPY

ALIASES = {
    "PING": "DEVICE_PING",
    "GET_DEVICE_HEALTH": "GET_DEVICE_HEALTH",
    "SPEAKER_TEST": "AUDIO_TEST",
    "STOP_MOTOR": "ROTATE_STOP",
    "DEVICE_RESTART": "DEVICE_RESTART",
    "CAMERA_ON": "CAMERA_ENABLE",
    "CAMERA_OFF": "CAMERA_DISABLE",
    "MIC_ON": "MIC_ENABLE",
    "MIC_OFF": "MIC_DISABLE",
    "PRIVACY_ON": "PRIVACY_ENABLE",
    "PRIVACY_OFF": "PRIVACY_DISABLE",
}


def normalize(command: str) -> str:
    value = (command or "").strip().upper().replace("-", "_").replace(" ", "_")
    return ALIASES.get(value, value)


def dispatch(hub: HomeHubEmulator, command: str, extra: dict[str, Any] | None = None, *, client_command_id: str | None = None, token: str | None = None) -> dict[str, Any]:
    extra = extra or {}
    command = normalize(command)
    if command in VEHICLE_FORBIDDEN:
        raise ValueError("Vehicle-control commands are not supported.")
    row = hub.queue.enqueue(command, client_command_id=client_command_id, extra=extra)
    if row.get("idempotent"):
        return {"command": row, "twin": hub.digital_twin(), "idempotent": True}

    if command == "ROTATE_STOP":
        hub.queue.advance(row["command_id"], "RECEIVED", ack=True)
        hub.motor.stop(reason="software")
        hub.queue.advance(row["command_id"], "COMPLETED", ack=True)
        return _finish(hub, row, "COMPLETED")

    if hub.network["state"] == "disconnected" and command not in {"PRIVACY_ENABLE", "CAMERA_DISABLE", "MIC_DISABLE"}:
        hub.queue.advance(row["command_id"], "FAILED")
        hub.offline_banner = "OFFLINE — CLOUD CONNECTION UNAVAILABLE"
        hub.last_error = "offline"
        return _finish(hub, row, "FAILED", cloud_success=False)

    if command not in {"DEVICE_PING", "GET_STATUS", "GET_DEVICE_HEALTH"}:
        try:
            hub.identity.validate_token(token)
        except PermissionError as exc:
            hub.queue.advance(row["command_id"], "REJECTED")
            raise exc

    hub.queue.advance(row["command_id"], "EXECUTING", ack=True)
    privacy = hub.effective_privacy()

    if command in {"DEVICE_PING", "GET_STATUS", "GET_DEVICE_HEALTH"}:
        hub.heartbeat.beat(latency_ms=hub.network["latency_ms"])
    elif command == "CAMERA_ENABLE":
        if privacy or hub.camera["failed"] or not hub.camera["available"]:
            hub.camera["state"] = "off"
        else:
            hub.camera["state"] = "on"
            hub.camera["initializing"] = False
    elif command == "CAMERA_DISABLE":
        hub.camera["state"] = "off"
        hub.camera["initializing"] = False
    elif command == "MIC_ENABLE":
        hub.mic["state"] = "off" if privacy or hub.mic["failed"] else "on"
    elif command == "MIC_DISABLE":
        hub.mic["state"] = "off"
    elif command == "AUDIO_TEST":
        hub.speaker["last_test"] = "tone_simulated" if hub.speaker["available"] else "failed"
    elif command == "PRIVACY_ENABLE":
        hub.apply_privacy(True)
    elif command == "PRIVACY_DISABLE":
        if hub.privacy_switch != "PRIVACY_SWITCH_ON":
            hub.privacy_mode = False
    elif command in {"ROTATE_LEFT", "ROTATE_RIGHT", "ROTATE_HOME", "ROTATE_TO_ANGLE"}:
        hub.motor.apply(command, angle=extra.get("angle"), privacy=privacy)
    elif command == "DEVICE_RESTART":
        recover_agent(hub)
    elif command == "SET_OFFLINE":
        apply_fault(hub, "network_disconnect")
    elif command == "SET_ONLINE":
        apply_fault(hub, "network_reconnect")
    else:
        if command.startswith("SIMULATE_") or command in {"SENSOR_SAMPLE", "SET_MOTION"}:
            pass
        else:
            hub.last_error = "unknown_command"
            hub.queue.advance(row["command_id"], "REJECTED")
            return _finish(hub, row, "REJECTED")

    hub.queue.advance(row["command_id"], "COMPLETED", ack=True)
    return _finish(hub, row, "COMPLETED")


def apply_fault(hub: HomeHubEmulator, kind: str) -> dict[str, Any]:
    if kind == "network_disconnect":
        hub.network["state"] = "disconnected"
        hub.device_state = "offline"
        hub.offline_banner = "OFFLINE — CLOUD CONNECTION UNAVAILABLE"
        hub.motor.apply("NETWORK_LOSS")
        hub.heartbeat.miss()
        hub.heartbeat.miss()
        hub.heartbeat.miss()
        event = hub.safety.emit("DEVICE_OFFLINE", device_id=hub.identity.device_id)
        hub.safety_event_status = "NEEDS_REVIEW"
        return event
    if kind == "network_reconnect":
        hub.network["state"] = "connected"
        hub.device_state = "ready"
        hub.offline_banner = None
        hub.heartbeat.recover()
        return hub.digital_twin()
    if kind == "camera_failure":
        hub.camera["failed"] = True
        hub.camera["state"] = "failed"
        hub.camera["available"] = False
    elif kind == "mic_failure":
        hub.mic["failed"] = True
        hub.mic["state"] = "failed"
    elif kind == "motor_obstruction":
        hub.motor.apply("MOTOR_OBSTRUCTION")
        event = hub.safety.emit("MOTOR_OBSTRUCTION", device_id=hub.identity.device_id)
        hub.safety_event_status = "NEEDS_REVIEW"
        return event
    elif kind == "motor_timeout":
        hub.motor.apply("MOTOR_TIMEOUT")
    elif kind == "power_loss":
        hub.power["ac"] = False
        hub.device_state = "degraded"
        event = hub.safety.emit("POWER_LOSS", device_id=hub.identity.device_id)
        hub.safety_event_status = "NEEDS_REVIEW"
        return event
    elif kind == "low_battery":
        hub.power["battery_percent"] = 8
        hub.power["low_battery"] = True
    elif kind == "high_temperature":
        hub.thermal["state"] = "high"
        hub.thermal["temperature_c"] = 78.0
        hub.device_state = "degraded"
        event = hub.safety.emit("HIGH_TEMPERATURE", device_id=hub.identity.device_id)
        hub.safety_event_status = "NEEDS_REVIEW"
        return event
    elif kind == "possible_fall":
        event = hub.safety.emit("POSSIBLE_FALL", device_id=hub.identity.device_id)
        hub.safety_event_status = "NEEDS_REVIEW"
        return event
    elif kind == "device_tipped":
        event = hub.safety.emit("DEVICE_TIPPED", device_id=hub.identity.device_id)
        hub.safety_event_status = "NEEDS_REVIEW"
        return event
    elif kind == "agent_restart":
        recover_agent(hub)
    return hub.digital_twin()


def recover_agent(hub: HomeHubEmulator) -> dict[str, Any]:
    privacy = hub.effective_privacy()
    token = hub.identity.device_token
    pairing = hub.identity.pairing_state
    hub.device_state = "restarting"
    hub.motor.reset()
    hub.camera["initializing"] = False
    hub.camera["state"] = "off"
    hub.mic["state"] = "off"
    if privacy:
        hub.apply_privacy(True)
    hub.identity.device_token = token
    hub.identity.pairing_state = pairing
    hub.device_state = "ready"
    hub.heartbeat.recover()
    hub.audit.write("agent_restart", device_id=hub.identity.device_id)
    return hub.digital_twin()


def _finish(hub: HomeHubEmulator, row: dict[str, Any], status: str, *, cloud_success: bool = True) -> dict[str, Any]:
    hub.last_command = row["command"]
    hub.last_outcome = status
    hub.last_ack = status in {"COMPLETED", "ACKNOWLEDGED"}
    hub.identity.last_seen = hub.heartbeat.last_seen
    hub.audit.write(
        "command",
        device_id=hub.identity.device_id,
        command_id=row["command_id"],
        command=row["command"],
        status=status,
    )
    return {
        "command": hub.queue.get(row["command_id"]),
        "twin": hub.digital_twin(),
        "idempotent": False,
        "cloud_success": cloud_success,
        "summary": COPY if hub.safety_event_status == "NEEDS_REVIEW" else None,
        "emergency_services_contacted": False,
    }
