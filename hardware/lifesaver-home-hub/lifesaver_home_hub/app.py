"""Local Home Hub agent HTTP API. Private LAN / in-process only."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from lifesaver_home_hub.dispatcher import apply_fault, dispatch, normalize
from lifesaver_home_hub.emulator import VIDEO_STATES, get_emulator, reset_emulator
from lifesaver_home_hub.selftest import run_self_test
from lifesaver_home_hub.version import AGENT_NAME, AGENT_VERSION, PROTOCOL_VERSION

router = APIRouter(prefix="/home-hub-agent", tags=["lifesaver-home-hub-agent"])


class CommandIn(BaseModel):
    command: str
    angle: float | None = None
    client_command_id: str | None = Field(default=None, max_length=64)
    device_token: str | None = None


class EventIn(BaseModel):
    event_type: str
    confidence: str | None = "low"


class ReviewIn(BaseModel):
    review_status: str


class FaultIn(BaseModel):
    kind: str


class VideoIn(BaseModel):
    action: str


class WizardStepIn(BaseModel):
    step: int | None = 1


def _hub():
    return get_emulator()


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


@router.get("/health")
def health():
    hub = _hub()
    return _ok({
        "agent": AGENT_NAME,
        "version": AGENT_VERSION,
        "protocol": PROTOCOL_VERSION,
        "status": hub.device_state,
        "simulated": True,
        "real_camera_streaming": False,
        "emergency_services_contacted": False,
    })


@router.get("/status")
def status():
    return _ok(_hub().digital_twin())


@router.get("/capabilities")
def capabilities():
    return _ok(_hub().identity.snapshot()["capabilities"])


@router.get("/twin")
def twin():
    return _ok(_hub().digital_twin())


@router.post("/pair")
def pair():
    hub = _hub()
    token = hub.identity.pair()
    hub.audit.write("pair", device_id=hub.identity.device_id)
    snap = hub.identity.snapshot()
    snap["device_token"] = token
    return _ok(snap)


@router.post("/token/rotate")
def rotate_token(x_device_token: str | None = Header(default=None, alias="X-Device-Token")):
    hub = _hub()
    try:
        hub.identity.validate_token(x_device_token)
        token = hub.identity.rotate_token()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    snap = hub.identity.snapshot()
    snap["device_token"] = token
    return _ok(snap)


@router.post("/unpair")
def unpair():
    hub = _hub()
    hub.identity.unpair()
    return _ok(hub.identity.snapshot())


@router.post("/commands")
def commands(payload: CommandIn, x_device_token: str | None = Header(default=None, alias="X-Device-Token")):
    hub = _hub()
    token = payload.device_token or x_device_token
    try:
        result = dispatch(
            hub,
            payload.command,
            {"angle": payload.angle} if payload.angle is not None else {},
            client_command_id=payload.client_command_id,
            token=token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _ok(result)


@router.get("/commands/{command_id}")
def get_command(command_id: str):
    row = _hub().queue.get(command_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Command was not found.")
    return _ok(row)


@router.post("/events")
def post_event(payload: EventIn):
    hub = _hub()
    event = hub.safety.emit(payload.event_type, device_id=hub.identity.device_id, confidence=payload.confidence or "low")
    hub.safety_event_status = "NEEDS_REVIEW"
    return _ok(event)


@router.get("/events/recent")
def recent_events():
    return _ok(_hub().safety.recent())


@router.post("/events/{event_id}/review")
def review_event(event_id: str, payload: ReviewIn):
    try:
        return _ok(_hub().safety.review(event_id, payload.review_status))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/self-test")
def self_test():
    return _ok(run_self_test(_hub()))


@router.post("/faults")
def faults(payload: FaultIn):
    hub = _hub()
    if not hub.config.debug_controls:
        raise HTTPException(status_code=403, detail="Emulator debug controls are disabled.")
    return _ok(apply_fault(hub, payload.kind))


@router.post("/privacy-switch")
def privacy_switch(payload: dict[str, Any]):
    hub = _hub()
    hub.set_privacy_switch(bool(payload.get("pressed")))
    return _ok(hub.digital_twin())


@router.post("/physical-stop")
def physical_stop():
    hub = _hub()
    hub.physical_stop()
    return _ok(hub.digital_twin())


@router.post("/heartbeat")
def heartbeat():
    return _ok(_hub().heartbeat.beat(latency_ms=_hub().network["latency_ms"]))


@router.post("/heartbeat/miss")
def heartbeat_miss():
    return _ok(_hub().heartbeat.miss())


@router.post("/video")
def video(payload: VideoIn):
    hub = _hub()
    action = (payload.action or "").upper()
    if hub.effective_privacy() and action in {"REQUEST", "ACCEPT", "START"}:
        hub.video["state"] = "PRIVACY_BLOCKED"
        raise HTTPException(status_code=409, detail="Privacy mode prevents a video session.")
    if action == "REQUEST":
        hub.video = {"state": "RINGING", "session_id": "vid-sim"}
    elif action == "ACCEPT":
        if not hub.camera["available"] or hub.camera["failed"]:
            hub.video["state"] = "FAILED"
            raise HTTPException(status_code=409, detail="Camera is unavailable.")
        hub.video["state"] = "CAMERA_STARTING"
        hub.video["state"] = "ACTIVE_SIMULATED"
    elif action == "DECLINE":
        hub.video["state"] = "DECLINED"
    elif action == "END":
        hub.video["state"] = "ENDED"
    elif action == "FAIL":
        hub.video["state"] = "FAILED"
    elif action == "NETWORK_LOSS":
        hub.video["state"] = "FAILED"
    else:
        raise HTTPException(status_code=422, detail="Unsupported video action.")
    if hub.video["state"] not in VIDEO_STATES:
        hub.video["state"] = "FAILED"
    return _ok(hub.video)


@router.get("/wizard")
def wizard_state():
    hub = _hub()
    return _ok({
        "steps": [
            "welcome",
            "detect",
            "identity",
            "pair",
            "token",
            "connectivity",
            "camera",
            "microphone",
            "speaker",
            "motor_stop",
            "rotation",
            "privacy",
            "safety",
            "finish",
        ],
        "twin": hub.digital_twin(),
        "real_hardware": False,
    })


@router.post("/wizard/step")
def wizard_step(payload: WizardStepIn):
    hub = _hub()
    step = int(payload.step or 1)
    if step == 4 and hub.identity.pairing_state == "UNPAIRED":
        token = hub.identity.pair()
        result = {"step": step, "device_token": token, "identity": hub.identity.snapshot()}
        return _ok(result)
    if step == 7:
        dispatch(hub, "CAMERA_ENABLE", token=hub.identity.device_token)
        dispatch(hub, "CAMERA_DISABLE", token=hub.identity.device_token)
    if step == 8:
        dispatch(hub, "MIC_ENABLE", token=hub.identity.device_token)
        dispatch(hub, "MIC_DISABLE", token=hub.identity.device_token)
    if step == 9:
        dispatch(hub, "AUDIO_TEST", token=hub.identity.device_token)
    if step == 10:
        dispatch(hub, "ROTATE_STOP", token=hub.identity.device_token)
    if step == 11:
        dispatch(hub, "ROTATE_RIGHT", token=hub.identity.device_token)
        dispatch(hub, "ROTATE_STOP", token=hub.identity.device_token)
    if step == 12:
        dispatch(hub, "PRIVACY_ENABLE", token=hub.identity.device_token)
        dispatch(hub, "PRIVACY_DISABLE", token=hub.identity.device_token)
    if step == 13:
        event = hub.safety.emit("POSSIBLE_FALL", device_id=hub.identity.device_id)
        hub.safety_event_status = "NEEDS_REVIEW"
        return _ok({"step": step, "event": event})
    return _ok({"step": step, "twin": hub.digital_twin()})


@router.post("/calibrate")
def calibrate():
    hub = _hub()
    token = hub.identity.device_token
    dispatch(hub, "ROTATE_STOP", token=token)
    hub.motor.apply("ROTATE_HOME")
    left = hub.motor.min_angle
    right = min(hub.motor.max_angle, 45)
    hub.motor.apply("ROTATE_TO_ANGLE", angle=left)
    hub.motor.apply("ROTATE_TO_ANGLE", angle=right)
    hub.motor.apply("ROTATE_HOME")
    hub.motor.home_calibrated = True
    return _ok({"calibrated": True, "motor": hub.motor.snapshot()})


@router.post("/reset")
def reset():
    return _ok(reset_emulator().digital_twin())


@router.get("/car-hub-contract")
def car_hub_contract():
    return _ok({
        "device_type": "CAR_HUB",
        "allowed": ["display", "microphone", "speaker", "gps_placeholder", "network", "device_health", "nova_lifesaver_link", "passenger_safety_info", "trip_context", "sos_ui_simulation"],
        "rejected": ["steering", "throttle", "braking", "ignition", "door_lock", "autonomous_driving"],
        "simulation_badge": "SIMULATION",
        "vehicle_control": False,
    })
