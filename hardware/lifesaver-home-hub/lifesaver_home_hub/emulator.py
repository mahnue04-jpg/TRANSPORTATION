"""High-fidelity Home Hub emulator. No real media, GPIO, or emergency calls."""
from __future__ import annotations

from typing import Any

from lifesaver_home_hub.audit import AuditLog, now_iso
from lifesaver_home_hub.config import load_config
from lifesaver_home_hub.heartbeat import HeartbeatMonitor
from lifesaver_home_hub.identity import IdentityStore
from lifesaver_home_hub.motor import MotorController
from lifesaver_home_hub.queue import CommandQueue
from lifesaver_home_hub.safety import SafetyPipeline
from lifesaver_home_hub.version import AGENT_NAME, AGENT_VERSION, DEVICE_TYPE, PROTOCOL_VERSION

PRIVACY_SWITCH_ON = "PRIVACY_SWITCH_ON"
PRIVACY_SWITCH_OFF = "PRIVACY_SWITCH_OFF"
PRIVACY_SWITCH_UNKNOWN = "UNKNOWN"
TRACKING_STATES = (
    "TRACKING_DISABLED",
    "TARGET_NOT_PRESENT",
    "TARGET_PRESENT",
    "TRACKING_AVAILABLE",
    "TRACKING_ACTIVE",
    "TRACKING_PAUSED",
    "PRIVACY_BLOCKED",
    "LOST_TARGET",
)
VIDEO_STATES = (
    "REQUESTED",
    "RINGING",
    "ACCEPTED",
    "CAMERA_STARTING",
    "ACTIVE_SIMULATED",
    "PAUSED",
    "PRIVACY_BLOCKED",
    "DECLINED",
    "ENDED",
    "FAILED",
)
VEHICLE_FORBIDDEN = frozenset({
    "STEER", "STEERING", "BRAKE", "BRAKING", "THROTTLE", "ACCELERATE",
    "IGNITION", "IGNITION_ON", "IGNITION_OFF", "LOCK", "UNLOCK",
    "DOOR_LOCK", "DOOR_UNLOCK", "VEHICLE_CONTROL",
})


class HomeHubEmulator:
    def __init__(self) -> None:
        self.config = load_config()
        self.identity = IdentityStore()
        self.motor = MotorController(min_angle=self.config.min_angle, max_angle=self.config.max_angle)
        self.queue = CommandQueue()
        self.heartbeat = HeartbeatMonitor(offline_after_misses=self.config.offline_after_misses)
        self.safety = SafetyPipeline()
        self.audit = AuditLog()
        self.reset_runtime()

    def reset_runtime(self) -> None:
        self.device_state = "ready"
        self.privacy_mode = False
        self.privacy_switch = PRIVACY_SWITCH_OFF
        self.camera = {"available": True, "state": "off", "initializing": False, "failed": False, "stream_ready": False}
        self.mic = {"available": True, "state": "off", "muted": False, "failed": False}
        self.speaker = {"available": True, "last_test": None, "volume": 40}
        self.power = {"ac": True, "battery_backup": True, "battery_percent": 98, "low_battery": False}
        self.thermal = {"state": "normal", "temperature_c": 31.2}
        self.network = {"state": "connected", "latency_ms": 4}
        self.tracking = {"state": "TRACKING_DISABLED", "x": None, "y": None, "confidence": None, "timestamp": None}
        self.video = {"state": "ENDED", "session_id": None}
        self.last_command = None
        self.last_outcome = None
        self.last_ack = None
        self.last_error = None
        self.self_test = None
        self.offline_banner = None
        self.safety_event_status = "none"
        self.connected_health_display: list[str] = []

    def digital_twin(self) -> dict[str, Any]:
        privacy = self.effective_privacy()
        return {
            "agent": AGENT_NAME,
            "agent_version": AGENT_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "device_type": DEVICE_TYPE,
            "device_state": self.device_state,
            "connected": self.network["state"] == "connected" and self.identity.pairing_state != "UNPAIRED",
            "paired": self.identity.pairing_state in {"PAIRED", "ONLINE", "DEGRADED"},
            "identity": self.identity.snapshot(),
            "firmware_version": self.identity.firmware_version,
            "ip_host": self.config.host,
            "privacy_mode": privacy,
            "privacy_switch": self.privacy_switch,
            "camera": self._camera_view(privacy),
            "microphone": self._mic_view(privacy),
            "speaker": dict(self.speaker),
            "motor": self.motor.snapshot(),
            "power": dict(self.power),
            "thermal": dict(self.thermal),
            "network": dict(self.network),
            "heartbeat": self.heartbeat.snapshot(),
            "tracking": dict(self.tracking),
            "video": dict(self.video),
            "safety_event_status": self.safety_event_status,
            "last_command": self.last_command,
            "last_outcome": self.last_outcome,
            "last_acknowledgement": self.last_ack,
            "last_error": self.last_error,
            "self_test": self.self_test,
            "offline_banner": self.offline_banner,
            "simulation_badge": "LOCAL PROTOTYPE" if self.config.mode == "local_pi" else "SIMULATION",
            "hardware_note": "NOT CONNECTED TO REAL HARDWARE",
            "emergency_services_contacted": False,
            "real_camera_streaming": False,
            "debug_controls": self.config.debug_controls,
            "connected_health_display": list(self.connected_health_display),
        }

    def set_connected_health_display(self, cards: list[str]) -> None:
        clean: list[str] = []
        for item in cards[:8]:
            text = str(item).strip()[:160]
            if text:
                clean.append(text)
        self.connected_health_display = clean

    def effective_privacy(self) -> bool:
        return self.privacy_mode or self.privacy_switch == PRIVACY_SWITCH_ON

    def _camera_view(self, privacy: bool) -> dict[str, Any]:
        blocked = privacy or self.camera["failed"] or not self.camera["available"]
        return {
            "available": self.camera["available"] and not privacy,
            "state": "privacy-blocked" if privacy else ("failed" if self.camera["failed"] else self.camera["state"]),
            "initializing": bool(self.camera["initializing"]) and not blocked,
            "failed": self.camera["failed"],
            "privacy_blocked": privacy,
            "stream_ready": False,
            "recording": False,
        }

    def _mic_view(self, privacy: bool) -> dict[str, Any]:
        return {
            "available": self.mic["available"] and not privacy,
            "state": "privacy-blocked" if privacy else ("failed" if self.mic["failed"] else self.mic["state"]),
            "muted": self.mic["muted"] or privacy,
            "failed": self.mic["failed"],
            "privacy_blocked": privacy,
        }

    def apply_privacy(self, enabled: bool) -> None:
        self.privacy_mode = enabled
        if enabled:
            self.camera["state"] = "off"
            self.camera["initializing"] = False
            self.mic["state"] = "off"
            self.tracking["state"] = "PRIVACY_BLOCKED"
            if self.video["state"] not in {"ENDED", "DECLINED", "FAILED"}:
                self.video["state"] = "PRIVACY_BLOCKED"
            self.motor.apply("ROTATE_STOP", privacy=True)

    def set_privacy_switch(self, pressed: bool) -> None:
        self.privacy_switch = PRIVACY_SWITCH_ON if pressed else PRIVACY_SWITCH_OFF
        if pressed:
            self.apply_privacy(True)

    def physical_stop(self) -> None:
        self.motor.stop(reason="physical")
        self.queue.cancel_pending("physical_stop")
        self.audit.write("physical_stop", device_id=self.identity.device_id, command="ROTATE_STOP")


_EMULATOR: HomeHubEmulator | None = None


def get_emulator() -> HomeHubEmulator:
    global _EMULATOR
    if _EMULATOR is None:
        _EMULATOR = HomeHubEmulator()
    return _EMULATOR


def reset_emulator() -> HomeHubEmulator:
    global _EMULATOR
    _EMULATOR = HomeHubEmulator()
    return _EMULATOR
