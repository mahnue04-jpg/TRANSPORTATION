"""Per-peer Snap call session. No sockets, cameras, or browser objects.

`simulated=True` is only for the in-process loopback test. A browser session
that reaches `connected` is still `browser-webrtc-unverified`: this object
cannot see a second device.
"""
from __future__ import annotations

HUMAN_TWO_DEVICE_CHECKS = (
    "Use two physical devices on two networks, each signed in as a different account in the same organization.",
    "Accept the contact and open one direct conversation.",
    "Place an audio call and confirm each person hears the other person, not only their own sidetone.",
    "Place a video call and confirm each person sees the other person's camera.",
    "Decline an invite, hang up an active call, and reconnect after a network change.",
    "Deny the microphone and camera and confirm the browser capture indicator turns off and does not return by itself.",
    "Expect strict NATs, some mobile carriers, and many international paths to fail because no TURN relay is configured.",
    "Keep the public website card on Coming Soon until this checklist passes and the owner approves a release.",
)

_TERMINAL = {"declined", "ended", "failed"}
_MEDIA_STATES = {"connecting", "reconnecting", "connected"}


class CallSession:
    def __init__(self, role: str, *, simulated: bool = False):
        if role not in {"caller", "callee"}:
            raise ValueError("role")
        self.role = role
        self.simulated = bool(simulated)
        self.state = "idle"
        self.accepted = False
        self.media_granted = False
        self.media_denied = False
        self.local_desc: str | None = None
        self.remote_desc: str | None = None
        self.local_ice = 0
        self.remote_ice = 0
        self.media_path = "none"
        self.error: str | None = None
        self.devices_used = 0
        self.rtp_packets = 0
        self.two_independent_devices = False

    def evidence(self) -> dict:
        label = "simulated" if self.simulated else "browser-unverified"
        return {
            "label": label,
            "simulated": self.simulated,
            "state": self.state,
            "role": self.role,
            "media_path": self.media_path,
            "media_granted": self.media_granted,
            "media_denied": self.media_denied,
            "two_independent_devices": False,
            "devices_used": 0,
            "rtp_packets": 0,
            "turn_purchased": False,
            "error": self.error,
        }

    def apply(self, event: str) -> dict:
        name = (event or "").strip()
        state = self.state
        if name in {"hangup", "end"} and state not in _TERMINAL:
            self.state = "ended"
            self.error = None
            return self.evidence()
        if name == "timeout" and state not in _TERMINAL:
            self.state = "failed"
            self.error = "network_timeout"
            self.media_path = "none"
            return self.evidence()
        if name == "ice_failed" and state in _MEDIA_STATES:
            self.state = "failed"
            self.error = "ice_failed"
            self.media_path = "none"
            return self.evidence()
        if state == "idle" and name == "invite_out" and self.role == "caller":
            self.state = "ringing_out"
            self.accepted = True
            return self.evidence()
        if state == "idle" and name == "invite_in" and self.role == "callee":
            self.state = "ringing_in"
            return self.evidence()
        if state == "ringing_in" and name == "accept" and self.role == "callee":
            self.accepted = True
            return self.evidence()
        if state == "ringing_in" and name == "decline":
            self.state = "declined"
            self.error = None
            return self.evidence()
        if state in {"ringing_out", "connecting"} and name == "remote_decline":
            self.state = "declined"
            self.media_path = "none"
            return self.evidence()
        if name == "media_denied" and self.accepted and state in {"ringing_out", "ringing_in", "connecting", "reconnecting"}:
            self.media_granted = False
            self.media_denied = True
            self.state = "permission_denied"
            self.media_path = "none"
            self.error = "permission_denied"
            return self.evidence()
        if name == "media_granted" and self.accepted and state in {"ringing_out", "ringing_in", "permission_denied", "reconnecting"}:
            self.media_denied = False
            self.media_granted = True
            self.error = None
            if state != "reconnecting":
                self.state = "connecting"
            return self.evidence()
        if name in {"local_offer", "remote_offer", "local_answer", "remote_answer", "local_ice", "remote_ice"}:
            self._on_signal(name)
            return self.evidence()
        if name == "reconnect" and state in {"connecting", "connected"}:
            self.state = "reconnecting"
            self.remote_desc = None
            self.local_ice = 0
            self.remote_ice = 0
            self.media_path = "none"
            self.error = None
            return self.evidence()
        raise ValueError(f"illegal:{state}:{name}")

    def _on_signal(self, event: str) -> None:
        if self.state not in _MEDIA_STATES or not self.media_granted or self.media_denied:
            raise ValueError(f"illegal:{self.state}:{event}")
        if event == "local_offer":
            self.local_desc = "offer"
        elif event == "remote_offer":
            self.remote_desc = "offer"
        elif event == "local_answer":
            if self.remote_desc != "offer":
                raise ValueError("illegal:answer-without-offer")
            self.local_desc = "answer"
        elif event == "remote_answer":
            if self.local_desc != "offer":
                raise ValueError("illegal:answer-without-offer")
            self.remote_desc = "answer"
        elif event == "local_ice":
            if self.local_desc not in {"offer", "answer"}:
                raise ValueError("illegal:ice-without-description")
            self.local_ice += 1
        elif event == "remote_ice":
            if self.remote_desc not in {"offer", "answer"}:
                raise ValueError("illegal:ice-without-description")
            self.remote_ice += 1
        self._maybe_ready()

    def _maybe_ready(self) -> None:
        if {self.local_desc, self.remote_desc} != {"offer", "answer"}:
            return
        if self.local_ice < 1 or self.remote_ice < 1:
            return
        self.state = "connected"
        self.error = None
        if self.simulated:
            self.media_path = "simulated-loopback"
        else:
            self.media_path = "browser-webrtc-unverified"
