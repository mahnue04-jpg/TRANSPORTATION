"""Shared device command contract. Adapters stay interchangeable."""
from __future__ import annotations

COMMAND_ALIASES = {
    "PING": "DEVICE_PING",
    "GET_STATUS": "GET_STATUS",
    "GET_DEVICE_HEALTH": "GET_DEVICE_HEALTH",
    "CAMERA_ON": "CAMERA_ENABLE",
    "CAMERA_OFF": "CAMERA_DISABLE",
    "MICROPHONE_ON": "MIC_ENABLE",
    "MICROPHONE_OFF": "MIC_DISABLE",
    "SPEAKER_TEST": "AUDIO_TEST",
    "ROTATION_STOP": "ROTATE_STOP",
    "PRIVACY_ON": "PRIVACY_ENABLE",
    "PRIVACY_OFF": "PRIVACY_DISABLE",
    "START_VIDEO_SESSION": "START_VIDEO_SESSION",
    "END_VIDEO_SESSION": "END_VIDEO_SESSION",
    "SIMULATE_MOTION": "SET_MOTION",
    "SIMULATE_FALL": "SIMULATE_FALL_EVENT",
    "RESTART_DEVICE": "DEVICE_RESTART_SIMULATED",
    "DEVICE_RESTART": "DEVICE_RESTART_SIMULATED",
    "ROTATE_TO_ANGLE": "ROTATE_TO_ANGLE",
    "STOP_MOTOR": "ROTATE_STOP",
    "DISPLAY_ON": "DISPLAY_ENABLE",
    "DISPLAY_OFF": "DISPLAY_DISABLE",
    "SAFE_DRIVE_MODE_ON": "SAFE_MODE_ENABLE",
    "SAFE_DRIVE_MODE_OFF": "SAFE_MODE_DISABLE",
    "LIFESAVER_LINK_STATUS": "LIFESAVER_LINK_STATUS",
    "NOVA_LINK_STATUS": "NOVA_LINK_STATUS",
    "CONNECTION_TEST": "CONNECTION_TEST",
    "AUDIO_TEST": "AUDIO_TEST",
}

LIFECYCLE = frozenset({
    "QUEUED",
    "SENT_LOCAL",
    "ACKNOWLEDGED",
    "COMPLETED",
    "FAILED",
    "TIMED_OUT",
    "CANCELLED",
    "REJECTED",
})

PAIRING_STATES = frozenset({
    "DISCOVERED",
    "PENDING_PAIR",
    "PAIRED",
    "ONLINE",
    "DEGRADED",
    "OFFLINE",
    "UNPAIRED",
})

VIDEO_PHASES = (
    "REQUESTED",
    "RINGING_SIMULATED",
    "ACCEPTED",
    "ACTIVE_SIMULATED",
    "DECLINED",
    "ENDED",
    "FAILED",
)

VIDEO_ROLES = frozenset({"patient", "user", "caregiver", "family", "provider"})

SAFETY_REVIEW = frozenset({
    "DETECTED",
    "NEEDS_REVIEW",
    "ACKNOWLEDGED",
    "FALSE_ALARM",
    "ESCALATION_SIMULATED",
    "RESOLVED",
})

ADAPTER_TYPES = frozenset({"simulated", "local_lan", "raspberry_pi", "local_pi", "offline"})

VEHICLE_FORBIDDEN = frozenset({
    "STEER",
    "STEERING",
    "BRAKE",
    "BRAKING",
    "THROTTLE",
    "ACCELERATE",
    "IGNITION",
    "IGNITION_ON",
    "IGNITION_OFF",
    "LOCK",
    "UNLOCK",
    "DOOR_LOCK",
    "DOOR_UNLOCK",
    "VEHICLE_CONTROL",
})


def normalize_command(raw: str) -> str:
    value = (raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    return COMMAND_ALIASES.get(value, value)
