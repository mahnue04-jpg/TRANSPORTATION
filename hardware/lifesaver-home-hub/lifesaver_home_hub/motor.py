"""Rotating-base state machine. STOP has highest priority. No GPIO."""
from __future__ import annotations

from typing import Any

IDLE = "IDLE"
MOVING_LEFT = "MOVING_LEFT"
MOVING_RIGHT = "MOVING_RIGHT"
MOVING_TO_ANGLE = "MOVING_TO_ANGLE"
HOMING = "HOMING"
STOPPING = "STOPPING"
STOPPED = "STOPPED"
OBSTRUCTED = "OBSTRUCTED"
CALIBRATION_REQUIRED = "CALIBRATION_REQUIRED"
FAULT = "FAULT"
TERMINAL_STOP = frozenset({STOPPED, IDLE, OBSTRUCTED, FAULT, CALIBRATION_REQUIRED})


class MotorController:
    def __init__(self, *, min_angle: int = 0, max_angle: int = 350) -> None:
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.reset()

    def reset(self) -> None:
        self.state = IDLE
        self.current_angle = 0.0
        self.requested_angle = 0.0
        self.speed_profile = "normal"
        self.obstruction = False
        self.timeout_sec = 3
        self.home_calibrated = True
        self.pending_cancelled = False
        self.physical_stop = False
        self.fault_reason = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "motor_state": self.state,
            "current_angle": self.current_angle,
            "requested_angle": self.requested_angle,
            "speed_profile": self.speed_profile,
            "obstruction": self.obstruction,
            "timeout_sec": self.timeout_sec,
            "home_calibrated": self.home_calibrated,
            "physical_stop": self.physical_stop,
            "fault_reason": self.fault_reason,
            "infinite_rotation": False,
            "real_motor": False,
        }

    def clamp(self, angle: float) -> float:
        return max(self.min_angle, min(self.max_angle, float(angle)))

    def stop(self, *, reason: str = "software") -> dict[str, Any]:
        self.state = STOPPED
        self.obstruction = reason == "obstruction"
        self.pending_cancelled = True
        self.timeout_sec = 0
        if reason == "physical":
            self.physical_stop = True
        return self.snapshot()

    def apply(self, command: str, *, angle: float | None = None, privacy: bool = False, tracking: bool = False) -> dict[str, Any]:
        if self.physical_stop and command not in {"ROTATE_STOP", "STOP_MOTOR", "CLEAR_PHYSICAL_STOP"}:
            self.state = STOPPED
            return self.snapshot()
        if command in {"ROTATE_STOP", "STOP_MOTOR"}:
            return self.stop(reason="software")
        if command == "CLEAR_PHYSICAL_STOP":
            self.physical_stop = False
            self.state = IDLE
            return self.snapshot()
        if privacy and command in {"ROTATE_LEFT", "ROTATE_RIGHT", "ROTATE_TO_ANGLE"}:
            self.state = STOPPED
            return self.snapshot()
        if self.obstruction and command not in {"ROTATE_HOME", "CALIBRATE_HOME"}:
            self.state = OBSTRUCTED
            return self.snapshot()
        if command == "ROTATE_LEFT":
            self.requested_angle = self.clamp(self.current_angle - 15)
            self.current_angle = self.requested_angle
            self.state = MOVING_LEFT
            self.timeout_sec = 3
        elif command == "ROTATE_RIGHT":
            self.requested_angle = self.clamp(self.current_angle + 15)
            self.current_angle = self.requested_angle
            self.state = MOVING_RIGHT
            self.timeout_sec = 3
        elif command == "ROTATE_TO_ANGLE":
            if angle is None:
                raise ValueError("ROTATE_TO_ANGLE requires an angle.")
            if float(angle) < self.min_angle or float(angle) > self.max_angle:
                raise ValueError("Requested angle is outside the calibrated range.")
            self.requested_angle = self.clamp(angle)
            self.current_angle = self.requested_angle
            self.state = HOMING if self.requested_angle == 0 else MOVING_TO_ANGLE
            self.timeout_sec = 3
        elif command == "ROTATE_HOME":
            self.requested_angle = 0
            self.current_angle = 0
            self.state = HOMING
            self.timeout_sec = 3
            self.home_calibrated = True
        elif command == "MOTOR_OBSTRUCTION":
            return self.stop(reason="obstruction")
        elif command == "MOTOR_TIMEOUT":
            self.state = FAULT
            self.fault_reason = "timeout"
            self.timeout_sec = 0
        elif command == "MOTOR_FAULT":
            self.state = FAULT
            self.fault_reason = "motor_fault"
        elif command == "CALIBRATION_REQUIRED":
            self.state = CALIBRATION_REQUIRED
            self.home_calibrated = False
        elif command == "NETWORK_LOSS":
            if self.state not in TERMINAL_STOP:
                self.stop(reason="network_loss")
        tracking
        return self.snapshot()
