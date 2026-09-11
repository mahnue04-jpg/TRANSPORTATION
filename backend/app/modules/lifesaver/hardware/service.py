"""Authorized simulated hardware operations. Tenant-scoped, audited, no media."""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.helpers import now, uuid4
from app.modules.lifesaver.audit import write_audit
from app.modules.lifesaver.hardware import bridge
from app.modules.lifesaver.hardware.adapters import simulated_car_hub, simulated_home_hub
from app.modules.lifesaver.hardware.camera_contract import camera_status
from app.modules.lifesaver.hardware.command_contract import (
    SAFETY_REVIEW,
    VEHICLE_FORBIDDEN,
    VIDEO_ROLES,
    normalize_command,
)
from app.modules.lifesaver.hardware.hardware_mode import hardware_mode, local_pi_enabled
from app.modules.lifesaver.hardware.motor_contract import motor_snapshot
from app.modules.lifesaver.hardware.sensor_contract import SENSOR_REVIEW_COPY, is_sensor_event, normalize_sensor_event
from app.modules.lifesaver.hardware.events import new_fall_event, serialize_event
from app.modules.lifesaver.hardware.health import build_health
from app.modules.lifesaver.hardware.models import (
    LifesaverDevice,
    LifesaverDeviceCapability,
    LifesaverDeviceCommand,
    LifesaverDeviceEvent,
    LifesaverHardwareSession,
    LifesaverSafetyEvent,
    LifesaverVideoSession,
)
from app.modules.lifesaver.hardware.network_safety import sanitize_command_metadata
from app.modules.lifesaver.hardware.registry import (
    DEVICE_CAR_HUB,
    DEVICE_HOME_HUB,
    DEVICE_STATUSES,
    DEVICE_TYPES,
    FALL_REVIEW_COPY,
    HARDWARE_COMMANDS,
    HARDWARE_DISCLAIMER,
    NO_RECORDING,
    NO_VEHICLE_CONTROL,
    STATUS_ONLINE,
    VIDEO_SESSION_STATUSES,
    capabilities_for,
    commands_for,
)
from app.modules.lifesaver.hardware.schemas import HardwareCommand, SimulatedDeviceCreate, VideoSessionCreate
from app.modules.lifesaver.integrations import notification_outbox
from app.modules.lifesaver.models import LifesaverAlert, LifesaverProfile
from app.modules.lifesaver.security import require_consent, require_subject_access

from app.modules.lifesaver import service as lifesaver_service


def _state(device: LifesaverDevice) -> dict[str, Any]:
    try:
        raw = json.loads(device.state_json or "{}")
    except Exception:
        raw = {}
    return raw if isinstance(raw, dict) else {}


def _save_state(device: LifesaverDevice, state: dict[str, Any], status: str) -> None:
    device.state_json = json.dumps(state, ensure_ascii=True)
    if status in DEVICE_STATUSES:
        device.status = status
    device.last_seen_at = now()
    device.updated_at = now()


def serialize_device(device: LifesaverDevice) -> dict[str, Any]:
    state = _state(device)
    privacy = bool(state.get("privacy_mode"))
    camera_on = bool(state.get("camera_enabled")) and not privacy
    adapter = getattr(device, "adapter_type", None) or "simulated"
    pairing = getattr(device, "pairing_state", None) or "PAIRED"
    prototype = adapter in {"local_pi", "raspberry_pi"} and local_pi_enabled()
    motor = motor_snapshot(state)
    camera = camera_status(state, privacy=privacy)
    return {
        "id": device.id,
        "device_type": device.device_type,
        "display_name": device.display_name,
        "serial_number": device.serial_number,
        "firmware_version": device.firmware_version,
        "software_version": device.software_version,
        "status": device.status,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "privacy_mode": privacy,
        "camera_enabled": camera_on,
        "camera_state": "on" if camera_on else "off",
        "microphone_enabled": bool(state.get("microphone_enabled")) and not privacy,
        "audio_state": "ready" if state.get("speaker_available", True) else "unavailable",
        "rotation_state": state.get("rotation") or "home",
        "rotation_moving": bool(state.get("rotation_moving")),
        "orientation_deg": state.get("orientation_deg", 0),
        "tracking_enabled": bool(state.get("tracking_enabled")) and not privacy,
        "obstruction": bool(state.get("obstruction")),
        "sensor_state": "privacy_blocked" if privacy else ("motion" if state.get("motion_detected") else "quiet"),
        "motion_detected": bool(state.get("motion_detected")) and not privacy,
        "battery_percent": state.get("battery_percent"),
        "temperature_c": state.get("temperature_c"),
        "power": state.get("power"),
        "display_active": state.get("display_active"),
        "network_status": state.get("network_status"),
        "safe_drive_mode": state.get("safe_drive_mode"),
        "nova_lifesaver_link": state.get("nova_lifesaver_link"),
        "capabilities": list(capabilities_for(device.device_type)),
        "allowed_commands": sorted(commands_for(device.device_type)),
        "adapter": adapter,
        "adapter_type": adapter,
        "pairing_state": pairing,
        "paired": pairing not in {"UNPAIRED", "DISCOVERED", "PENDING_PAIR"},
        "connected": device.status not in {"OFFLINE", "MAINTENANCE"} and pairing != "UNPAIRED",
        "hardware_model": getattr(device, "hardware_model", None),
        "local_ip": getattr(device, "local_ip", None),
        "local_host_label": getattr(device, "local_ip", None) or "local",
        "motor_state": motor["moving_state"],
        "requested_angle": motor["requested_angle"],
        "power_status": state.get("power") or "mains",
        "last_command": state.get("last_command"),
        "last_acknowledgement": state.get("last_acknowledgement"),
        "safety_event_status": state.get("safety_event_status") or "none",
        "camera_contract": camera,
        "hardware_mode": hardware_mode(),
        "simulation_badge": "LOCAL PROTOTYPE" if prototype else "SIMULATION",
        "external_device_connected": False,
        "vehicle_control": False,
        "disclaimer": HARDWARE_DISCLAIMER,
        "recording_disclaimer": NO_RECORDING,
        "vehicle_disclaimer": NO_VEHICLE_CONTROL if device.device_type == DEVICE_CAR_HUB else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
    }


def _owned_device(db: Session, actor: LifesaverProfile, device_id: str, *, action: str) -> LifesaverDevice:
    row = (
        db.query(LifesaverDevice)
        .filter(LifesaverDevice.id == device_id, LifesaverDevice.organization_id == actor.organization_id)
        .first()
    )
    if row is None:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            actor_profile_id=actor.id,
            action=action,
            resource_type="device",
            resource_id=device_id,
            outcome="denied",
            metadata={"reason": "unknown_or_cross_tenant"},
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Device was not found.")
    if row.profile_id and row.profile_id != actor.id:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            actor_profile_id=actor.id,
            action=action,
            resource_type="device",
            resource_id=device_id,
            outcome="denied",
            metadata={"reason": "not_owner"},
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Device was not found.")
    return row


def list_devices(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_devices", action="device.list", resource_type="device"
    )
    require_consent(db, ctx, subject, "hardware_simulation", action="device.list", resource_type="device")
    rows = (
        db.query(LifesaverDevice)
        .filter(
            LifesaverDevice.organization_id == subject.organization_id,
            LifesaverDevice.profile_id == subject.id,
        )
        .order_by(LifesaverDevice.created_at.asc())
        .all()
    )
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.list",
        resource_type="device",
        resource_id=subject.id,
        outcome="allowed",
        metadata={"count": len(rows)},
    )
    db.commit()
    return [serialize_device(row) for row in rows]


def create_simulated(db: Session, ctx: UserContext, payload: SimulatedDeviceCreate) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.create", resource_type="device")
    device_type = (payload.device_type or "").upper()
    if device_type not in DEVICE_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported device type.")
    existing = (
        db.query(LifesaverDevice)
        .filter(
            LifesaverDevice.organization_id == actor.organization_id,
            LifesaverDevice.profile_id == actor.id,
            LifesaverDevice.device_type == device_type,
        )
        .first()
    )
    if existing:
        return serialize_device(existing)
    state = simulated_home_hub.default_state() if device_type == DEVICE_HOME_HUB else simulated_car_hub.default_state()
    serial = (payload.serial_number or "").strip() or f"SIM-{device_type}-{uuid4()[:8]}"
    row = LifesaverDevice(
        organization_id=actor.organization_id,
        profile_id=actor.id,
        device_type=device_type,
        display_name=(payload.display_name or ("Home Hub" if device_type == DEVICE_HOME_HUB else "Car Hub")).strip()[:160],
        serial_number=serial[:64],
        firmware_version="sim-0.1",
        software_version="lifesaver-v2-sim",
        status=STATUS_ONLINE,
        adapter_name="simulated_home_hub" if device_type == DEVICE_HOME_HUB else "simulated_car_hub",
        adapter_type="simulated",
        pairing_state="PAIRED",
        hardware_model="simulated-home-hub" if device_type == DEVICE_HOME_HUB else "simulated-car-hub",
        local_ip="127.0.0.1",
        state_json=json.dumps(state),
        last_seen_at=now(),
        updated_at=now(),
    )
    db.add(row)
    db.flush()
    for name in capabilities_for(device_type):
        db.add(
            LifesaverDeviceCapability(
                organization_id=actor.organization_id,
                device_id=row.id,
                capability_name=name,
                present=True,
            )
        )
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.create",
        resource_type="device",
        resource_id=row.id,
        outcome="allowed",
        metadata={"device_type": device_type, "simulated": True},
    )
    db.commit()
    db.refresh(row)
    return serialize_device(row)


def get_device(db: Session, ctx: UserContext, device_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.read", resource_type="device")
    row = _owned_device(db, actor, device_id, action="device.read")
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.read",
        resource_type="device",
        resource_id=row.id,
        outcome="allowed",
        metadata={"device_type": row.device_type},
    )
    db.commit()
    return serialize_device(row)


def get_health(db: Session, ctx: UserContext, device_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.health", resource_type="device")
    row = _owned_device(db, actor, device_id, action="device.health")
    snapshot = build_health(row, _state(row))
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.health",
        resource_type="device",
        resource_id=row.id,
        outcome="allowed",
        metadata={"online": snapshot["online"], "privacy_mode": snapshot["privacy_mode"]},
    )
    db.commit()
    return snapshot


def run_command(db: Session, ctx: UserContext, device_id: str, payload: HardwareCommand) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.command", resource_type="device")
    command = normalize_command(payload.command)
    if command in VEHICLE_FORBIDDEN:
        raise HTTPException(status_code=422, detail="Vehicle-control commands are not supported.")
    if command not in HARDWARE_COMMANDS:
        raise HTTPException(status_code=422, detail="Unknown hardware command.")
    if command == "SIMULATE_FALL_EVENT":
        return simulate_fall(db, ctx, device_id)
    row = _owned_device(db, actor, device_id, action="device.command")
    if getattr(row, "pairing_state", "PAIRED") == "UNPAIRED" and command != "ROTATE_STOP":
        raise HTTPException(status_code=409, detail="Unpaired devices cannot receive commands.")
    allowed = commands_for(row.device_type)
    if command not in allowed:
        raise HTTPException(status_code=409, detail="Command is not available on this device type.")
    if payload.client_command_id:
        existing = (
            db.query(LifesaverDeviceCommand)
            .filter(
                LifesaverDeviceCommand.organization_id == actor.organization_id,
                LifesaverDeviceCommand.device_id == row.id,
                LifesaverDeviceCommand.client_command_id == payload.client_command_id,
            )
            .first()
        )
        if existing:
            return {
                "device": serialize_device(row),
                "command": command,
                "command_id": existing.id,
                "status": existing.lifecycle_status,
                "idempotent": True,
                "simulated": True,
                "external_device_contacted": False,
            }
    state = _state(row)
    extra = {}
    if payload.motion_detected is not None:
        extra["motion_detected"] = bool(payload.motion_detected)
    if payload.angle is not None:
        extra["angle"] = payload.angle
    if payload.device_token:
        extra["device_token"] = payload.device_token
    elif local_pi_enabled() and getattr(row, "pairing_token", None) and (payload.adapter_type or row.adapter_type) in {"local_pi", "raspberry_pi"}:
        extra["device_token"] = row.pairing_token
    if command == "START_VIDEO_SESSION" and state.get("privacy_mode"):
        raise HTTPException(status_code=409, detail="Privacy mode prevents automatic video start.")
    started = now()
    next_state, status, lifecycle, adapter_kind = bridge.execute(
        device=row,
        command=command,
        state=state,
        extra=extra,
        adapter_type=payload.adapter_type,
    )
    next_state["last_command"] = command
    next_state["last_acknowledgement"] = lifecycle
    _save_state(row, next_state, status)
    if getattr(row, "pairing_state", None) != "UNPAIRED":
        if status == "OFFLINE" or lifecycle == "TIMED_OUT":
            row.pairing_state = "OFFLINE"
        elif status == "DEGRADED":
            row.pairing_state = "DEGRADED"
        elif lifecycle == "COMPLETED":
            row.pairing_state = "ONLINE"
    log = LifesaverDeviceCommand(
        organization_id=actor.organization_id,
        device_id=row.id,
        profile_id=actor.id,
        actor_user_id=ctx.user_id,
        command=command,
        client_command_id=payload.client_command_id,
        outcome="accepted_simulated",
        lifecycle_status=lifecycle,
        adapter_type=adapter_kind,
        response_code="OK" if lifecycle == "COMPLETED" else lifecycle,
        error_message=None if lifecycle == "COMPLETED" else "Adapter did not complete the local command.",
        simulated=True,
        metadata_json=json.dumps(
            sanitize_command_metadata(
                {"privacy_mode": bool(next_state.get("privacy_mode")), "camera_enabled": bool(next_state.get("camera_enabled"))}
            )
        ),
        started_at=started,
        completed_at=now(),
    )
    db.add(log)
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.command",
        resource_type="device",
        resource_id=row.id,
        outcome="allowed",
        metadata={"command": command, "simulated": True, "adapter_type": adapter_kind, "lifecycle": lifecycle},
    )
    db.commit()
    db.refresh(row)
    return {
        "device": serialize_device(row),
        "command": command,
        "command_id": log.id,
        "status": lifecycle,
        "adapter_type": adapter_kind,
        "simulated": True,
        "external_device_contacted": False,
    }


def simulate_fall(db: Session, ctx: UserContext, device_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.simulate_fall", resource_type="safety")
    row = _owned_device(db, actor, device_id, action="device.simulate_fall")
    if row.device_type != DEVICE_HOME_HUB:
        raise HTTPException(status_code=409, detail="Fall simulation is available on Home Hub only.")
    event = new_fall_event(organization_id=actor.organization_id, device_id=row.id, profile_id=actor.id)
    db.add(event)
    db.flush()
    safety = LifesaverSafetyEvent(
        organization_id=actor.organization_id,
        device_id=row.id,
        profile_id=actor.id,
        event_type="SIMULATED_FALL_EVENT",
        confidence="low",
        source="simulated",
        review_status="NEEDS_REVIEW",
        escalation_state="none",
        summary=FALL_REVIEW_COPY,
        simulated=True,
        emergency_services_contacted=False,
        detected_at=now(),
    )
    db.add(safety)
    db.flush()
    alert = LifesaverAlert(
        organization_id=actor.organization_id,
        member_profile_id=actor.id,
        caregiver_profile_id=None,
        alert_type="safety_event",
        severity="attention",
        title="Possible safety event",
        message=FALL_REVIEW_COPY,
        status="open",
        requires_ack=True,
    )
    db.add(alert)
    notice = notification_outbox.queue(
        db,
        organization_id=actor.organization_id,
        profile_id=actor.id,
        recipient_profile_id=None,
        recipient_role="caregiver",
        notification_type="safety_event_review",
        channel="email",
        title="Safety event needs human review",
        reason="simulated_fall_local_only",
    )
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.simulate_fall",
        resource_type="safety",
        resource_id=event.id,
        outcome="allowed",
        metadata={"simulated": True, "emergency_services_contacted": False, "notice_id": notice.id},
    )
    db.commit()
    db.refresh(event)
    return {
        "event": serialize_event(event),
        "safety_event_id": safety.id,
        "review_status": "NEEDS_REVIEW",
        "alert_id": alert.id,
        "notification_id": notice.id,
        "notification_status": notice.status,
        "external_message_sent": False,
        "emergency_services_contacted": False,
        "needs_human_review": True,
        "label": "SIMULATION",
        "summary": FALL_REVIEW_COPY,
    }


def ingest_hardware_event(db: Session, ctx: UserContext, device_id: str, event_type: str, confidence: str | None = None) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.hardware_event", resource_type="safety")
    kind = normalize_sensor_event(event_type)
    if not is_sensor_event(kind):
        raise HTTPException(status_code=422, detail="Unsupported hardware safety-event type.")
    row = _owned_device(db, actor, device_id, action="device.hardware_event")
    if row.device_type != DEVICE_HOME_HUB:
        raise HTTPException(status_code=409, detail="Hardware safety events are available on Home Hub only.")
    event = LifesaverDeviceEvent(
        organization_id=actor.organization_id,
        device_id=row.id,
        profile_id=actor.id,
        event_type=kind,
        status="needs_human_review",
        summary=SENSOR_REVIEW_COPY,
        emergency_services_contacted=False,
        simulated=True,
        confidence=(confidence or "low")[:16],
        review_status="NEEDS_REVIEW",
        escalation_state="none",
        source="hardware_contract",
        metadata_json=json.dumps({"media_stored": False, "external_call": False, "clinical": False}),
        created_at=now(),
    )
    db.add(event)
    db.flush()
    safety = LifesaverSafetyEvent(
        organization_id=actor.organization_id,
        device_id=row.id,
        profile_id=actor.id,
        event_type=kind,
        confidence=(confidence or "low")[:16],
        source="hardware_contract",
        review_status="NEEDS_REVIEW",
        escalation_state="none",
        summary=SENSOR_REVIEW_COPY,
        simulated=True,
        emergency_services_contacted=False,
        detected_at=now(),
    )
    db.add(safety)
    state = _state(row)
    state["safety_event_status"] = "NEEDS_REVIEW"
    _save_state(row, state, row.status)
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.hardware_event",
        resource_type="safety",
        resource_id=event.id,
        outcome="allowed",
        metadata={"event_type": kind, "emergency_services_contacted": False},
    )
    db.commit()
    db.refresh(event)
    return {
        "event": serialize_event(event),
        "safety_event_id": safety.id,
        "review_status": "NEEDS_REVIEW",
        "emergency_services_contacted": False,
        "needs_human_review": True,
        "summary": SENSOR_REVIEW_COPY,
        "label": "SIMULATION" if not local_pi_enabled() else "LOCAL PROTOTYPE",
    }


def list_events(db: Session, ctx: UserContext, device_id: str) -> list[dict[str, Any]]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.events", resource_type="device")
    row = _owned_device(db, actor, device_id, action="device.events")
    events = (
        db.query(LifesaverDeviceEvent)
        .filter(
            LifesaverDeviceEvent.organization_id == actor.organization_id,
            LifesaverDeviceEvent.device_id == row.id,
        )
        .order_by(LifesaverDeviceEvent.created_at.desc())
        .limit(40)
        .all()
    )
    return [serialize_event(item) for item in events]


def acknowledge_safety(db: Session, ctx: UserContext, event_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    event = (
        db.query(LifesaverDeviceEvent)
        .filter(LifesaverDeviceEvent.id == event_id, LifesaverDeviceEvent.organization_id == actor.organization_id)
        .first()
    )
    if event is None or event.profile_id != actor.id:
        raise HTTPException(status_code=404, detail="Safety event was not found.")
    event.status = "acknowledged"
    event.review_status = "ACKNOWLEDGED"
    event.acknowledged_by = actor.id
    event.acknowledged_at = now()
    event.resolved_at = now()
    event.emergency_services_contacted = False
    safety = (
        db.query(LifesaverSafetyEvent)
        .filter(
            LifesaverSafetyEvent.organization_id == actor.organization_id,
            LifesaverSafetyEvent.device_id == event.device_id,
        )
        .order_by(LifesaverSafetyEvent.created_at.desc())
        .first()
    )
    if safety:
        safety.review_status = "ACKNOWLEDGED"
        safety.acknowledged_by = actor.id
        safety.acknowledged_at = now()
        safety.emergency_services_contacted = False
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="safety.acknowledge",
        resource_type="safety",
        resource_id=event.id,
        outcome="allowed",
        metadata={"emergency_services_contacted": False},
    )
    db.commit()
    db.refresh(event)
    return serialize_event(event)


def request_video(db: Session, ctx: UserContext, device_id: str, payload: VideoSessionCreate) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "video_session_simulation", action="video.request", resource_type="video")
    row = _owned_device(db, actor, device_id, action="video.request")
    state = _state(row)
    privacy_ok = not bool(state.get("privacy_mode"))
    role = (payload.participant_role or "user").lower()
    if role not in VIDEO_ROLES:
        role = "user"
    if state.get("privacy_mode"):
        raise HTTPException(status_code=409, detail="Privacy mode prevents automatic video start.")
    session = LifesaverVideoSession(
        organization_id=actor.organization_id,
        device_id=row.id,
        profile_id=actor.id,
        requested_by_user_id=ctx.user_id,
        status="requested",
        session_phase="RINGING_SIMULATED",
        participant_role=role,
        provider="local_simulation",
        privacy_ok=privacy_ok,
        media_stored=False,
    )
    db.add(session)
    db.flush()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="video.request",
        resource_type="video",
        resource_id=session.id,
        outcome="allowed",
        metadata={"privacy_ok": privacy_ok, "provider": "local_simulation"},
    )
    db.commit()
    db.refresh(session)
    return _serialize_video(session)


def resolve_video(db: Session, ctx: UserContext, session_id: str, *, accept: bool) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "video_session_simulation", action="video.resolve", resource_type="video")
    session = (
        db.query(LifesaverVideoSession)
        .filter(LifesaverVideoSession.id == session_id, LifesaverVideoSession.organization_id == actor.organization_id)
        .first()
    )
    if session is None or session.profile_id != actor.id:
        raise HTTPException(status_code=404, detail="Video session was not found.")
    if session.status not in VIDEO_SESSION_STATUSES or session.status != "requested":
        raise HTTPException(status_code=409, detail="Only a requested session can be accepted or declined.")
    device = _owned_device(db, actor, session.device_id, action="video.resolve")
    state = _state(device)
    if accept and (state.get("privacy_mode") or not state.get("camera_enabled")):
        raise HTTPException(status_code=409, detail="Camera must be on and privacy mode off before accepting.")
    session.status = "accepted" if accept else "declined"
    session.session_phase = "ACCEPTED" if accept else "DECLINED"
    session.privacy_ok = not bool(state.get("privacy_mode"))
    session.media_stored = False
    session.resolved_at = now()
    hardware_session = LifesaverHardwareSession(
        organization_id=actor.organization_id,
        device_id=session.device_id,
        profile_id=actor.id,
        video_session_id=session.id,
        session_phase=session.session_phase,
        participant_role=session.participant_role,
        media_stored=False,
    )
    db.add(hardware_session)
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="video.accept" if accept else "video.decline",
        resource_type="video",
        resource_id=session.id,
        outcome="allowed",
        metadata={"accepted": accept, "media_stored": False},
    )
    db.commit()
    db.refresh(session)
    return _serialize_video(session)


def list_video(db: Session, ctx: UserContext, device_id: str) -> list[dict[str, Any]]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "video_session_simulation", action="video.list", resource_type="video")
    row = _owned_device(db, actor, device_id, action="video.list")
    sessions = (
        db.query(LifesaverVideoSession)
        .filter(
            LifesaverVideoSession.organization_id == actor.organization_id,
            LifesaverVideoSession.device_id == row.id,
        )
        .order_by(LifesaverVideoSession.created_at.desc())
        .limit(20)
        .all()
    )
    return [_serialize_video(item) for item in sessions]


def _serialize_video(row: LifesaverVideoSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "status": row.status,
        "session_phase": getattr(row, "session_phase", None) or row.status.upper(),
        "participant_role": getattr(row, "participant_role", None) or "user",
        "provider": "local_simulation",
        "privacy_ok": bool(row.privacy_ok),
        "media_stored": False,
        "live_call": False,
        "disclaimer": "Local session request only. No third-party video provider is connected.",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def activate_video(db: Session, ctx: UserContext, session_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "video_session_simulation", action="video.activate", resource_type="video")
    session = (
        db.query(LifesaverVideoSession)
        .filter(LifesaverVideoSession.id == session_id, LifesaverVideoSession.organization_id == actor.organization_id)
        .first()
    )
    if session is None or session.profile_id != actor.id:
        raise HTTPException(status_code=404, detail="Video session was not found.")
    if session.status != "accepted":
        raise HTTPException(status_code=409, detail="Only an accepted session can be simulated as active.")
    device = _owned_device(db, actor, session.device_id, action="video.activate")
    state = _state(device)
    if state.get("privacy_mode") or not state.get("camera_enabled"):
        raise HTTPException(status_code=409, detail="Camera must be on and privacy mode off before simulated activation.")
    session.session_phase = "ACTIVE_SIMULATED"
    session.media_stored = False
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="video.activate",
        resource_type="video",
        resource_id=session.id,
        outcome="allowed",
        metadata={"session_phase": "ACTIVE_SIMULATED", "media_stored": False},
    )
    db.commit()
    db.refresh(session)
    return _serialize_video(session)


def end_video(db: Session, ctx: UserContext, session_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "video_session_simulation", action="video.end", resource_type="video")
    session = (
        db.query(LifesaverVideoSession)
        .filter(LifesaverVideoSession.id == session_id, LifesaverVideoSession.organization_id == actor.organization_id)
        .first()
    )
    if session is None or session.profile_id != actor.id:
        raise HTTPException(status_code=404, detail="Video session was not found.")
    session.status = "ended"
    session.session_phase = "ENDED"
    session.media_stored = False
    session.resolved_at = now()
    db.commit()
    db.refresh(session)
    return _serialize_video(session)


def list_commands(db: Session, ctx: UserContext, device_id: str) -> list[dict[str, Any]]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.commands", resource_type="device")
    row = _owned_device(db, actor, device_id, action="device.commands")
    logs = (
        db.query(LifesaverDeviceCommand)
        .filter(
            LifesaverDeviceCommand.organization_id == actor.organization_id,
            LifesaverDeviceCommand.device_id == row.id,
        )
        .order_by(LifesaverDeviceCommand.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "command_id": item.id,
            "device_id": item.device_id,
            "command_type": item.command,
            "requested_by": item.actor_user_id,
            "requested_at": item.created_at.isoformat() if item.created_at else None,
            "status": item.lifecycle_status,
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "response_code": item.response_code,
            "error_message": item.error_message,
            "adapter_type": item.adapter_type,
            "simulated": True,
        }
        for item in logs
    ]


def review_safety(db: Session, ctx: UserContext, event_id: str, review_status: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    status = (review_status or "").upper()
    if status not in SAFETY_REVIEW:
        raise HTTPException(status_code=422, detail="Unsupported safety review status.")
    event = (
        db.query(LifesaverDeviceEvent)
        .filter(LifesaverDeviceEvent.id == event_id, LifesaverDeviceEvent.organization_id == actor.organization_id)
        .first()
    )
    if event is None or event.profile_id != actor.id:
        raise HTTPException(status_code=404, detail="Safety event was not found.")
    event.review_status = status
    event.emergency_services_contacted = False
    if status in {"ACKNOWLEDGED", "FALSE_ALARM", "RESOLVED", "ESCALATION_SIMULATED"}:
        event.status = "acknowledged" if status != "RESOLVED" else "closed"
        event.acknowledged_at = now()
        event.acknowledged_by = actor.id
    if status == "RESOLVED":
        event.resolved_at = now()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="safety.review",
        resource_type="safety",
        resource_id=event.id,
        outcome="allowed",
        metadata={"review_status": status, "emergency_services_contacted": False},
    )
    db.commit()
    db.refresh(event)
    return serialize_event(event)


def open_safety_events(db: Session, *, organization_id: str, profile_id: str) -> list[LifesaverDeviceEvent]:
    return (
        db.query(LifesaverDeviceEvent)
        .filter(
            LifesaverDeviceEvent.organization_id == organization_id,
            LifesaverDeviceEvent.profile_id == profile_id,
        )
        .order_by(LifesaverDeviceEvent.created_at.desc())
        .limit(20)
        .all()
    )
