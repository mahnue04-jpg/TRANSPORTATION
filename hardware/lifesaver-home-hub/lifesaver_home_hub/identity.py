"""Prototype identity and pairing. Tokens are generated locally and never logged whole."""
from __future__ import annotations

import secrets
from typing import Any

from lifesaver_home_hub.audit import mask_secret, now_iso
from lifesaver_home_hub.version import DEVICE_TYPE, FIRMWARE_PLACEHOLDER, MODEL_PLACEHOLDER


class IdentityStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.device_id = "hub-" + secrets.token_hex(4)
        self.installation_id = "inst-" + secrets.token_hex(4)
        self.serial = "UNASSIGNED"
        self.model = MODEL_PLACEHOLDER
        self.firmware_version = FIRMWARE_PLACEHOLDER
        self.pairing_state = "UNPAIRED"
        self.device_token = ""
        self.created_at = now_iso()
        self.last_seen = None
        self.capabilities = {
            "camera": True,
            "microphone": True,
            "speaker": True,
            "rotating_base": True,
            "privacy_mode": True,
            "safety_event_input": True,
            "physical_privacy_switch": True,
            "physical_stop": True,
            "real_gpio": False,
            "real_camera_stream": False,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": DEVICE_TYPE,
            "model": self.model,
            "serial": self.serial,
            "firmware_version": self.firmware_version,
            "installation_id": self.installation_id,
            "pairing_state": self.pairing_state,
            "device_token_masked": mask_secret(self.device_token),
            "has_token": bool(self.device_token),
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "capabilities": dict(self.capabilities),
        }

    def pair(self) -> str:
        self.device_token = "proto-" + secrets.token_hex(12)
        self.pairing_state = "PAIRED"
        self.last_seen = now_iso()
        return self.device_token

    def rotate_token(self) -> str:
        if self.pairing_state not in {"PAIRED", "ONLINE", "DEGRADED"}:
            raise PermissionError("Only a paired device can rotate its token.")
        self.device_token = "proto-" + secrets.token_hex(12)
        self.last_seen = now_iso()
        return self.device_token

    def unpair(self) -> None:
        self.pairing_state = "UNPAIRED"
        self.device_token = ""

    def validate_token(self, presented: str | None) -> None:
        if self.pairing_state not in {"PAIRED", "ONLINE", "DEGRADED"}:
            raise PermissionError("Unpaired devices cannot receive commands.")
        if not self.device_token or (presented or "") != self.device_token:
            raise PermissionError("A valid paired device token is required.")
