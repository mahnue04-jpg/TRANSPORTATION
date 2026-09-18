"""Explicit human pairing. Unknown devices are never auto-trusted."""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.helpers import now, uuid4
from app.modules.lifesaver.audit import write_audit
from app.modules.lifesaver.hardware.adapters import simulated_car_hub, simulated_home_hub
from app.modules.lifesaver.hardware.models import LifesaverDevice, LifesaverDeviceCapability, LifesaverDevicePairing
from app.modules.lifesaver.hardware.network_safety import reject_public_device_host
from app.modules.lifesaver.hardware.prototype_config import prototype_for
from app.modules.lifesaver.hardware.registry import (
    DEVICE_CAR_HUB,
    DEVICE_HOME_HUB,
    DEVICE_TYPES,
    STATUS_ONLINE,
    capabilities_for,
)
from app.modules.lifesaver.hardware.schemas import DiscoverRequest, PairConfirm
from app.modules.lifesaver.models import LifesaverProfile
from app.modules.lifesaver.security import require_consent

from app.modules.lifesaver import service as lifesaver_service


def serialize_pairing(row: LifesaverDevicePairing) -> dict[str, Any]:
    try:
        caps = json.loads(row.capabilities_json or "{}")
    except Exception:
        caps = {}
    if not isinstance(caps, dict):
        caps = {}
    discovery = {
        "device_id": row.device_id,
        "device_type": row.device_type,
        "hardware_model": row.hardware_model,
        "firmware_version": "proto-0.2",
        "local_ip": row.local_ip,
        "connection_state": row.pairing_state,
        "battery_level": 98 if row.device_type == DEVICE_HOME_HUB else None,
        "temperature": 31.2 if row.device_type == DEVICE_HOME_HUB else None,
        "camera_present": bool(caps.get("camera_present")),
        "microphone_present": bool(caps.get("microphone_present")),
        "speaker_present": bool(caps.get("speaker_present")),
        "rotation_supported": bool(caps.get("rotation_supported")),
        "fall_sensor_supported": bool(caps.get("fall_sensor_supported")),
        "video_supported": bool(caps.get("video_supported")),
        "last_seen_at": row.updated_at.isoformat() if row.updated_at else None,
        "capabilities": [name for name, present in caps.items() if present],
    }
    return {
        "id": row.id,
        "device_id": row.device_id,
        "device_type": row.device_type,
        "hardware_model": row.hardware_model,
        "serial_number": row.serial_number,
        "local_ip": row.local_ip,
        "pairing_state": row.pairing_state,
        "confirmed": bool(row.confirmed),
        "capabilities": caps,
        "discovery": discovery,
        "auto_trusted": False,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def discover(db: Session, ctx: UserContext, payload: DiscoverRequest) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.discover", resource_type="pairing")
    device_type = (payload.device_type or "").upper()
    if device_type not in DEVICE_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported device type.")
    host = reject_public_device_host(payload.local_ip or "127.0.0.1")
    proto = prototype_for(device_type)
    row = LifesaverDevicePairing(
        organization_id=actor.organization_id,
        profile_id=actor.id,
        device_type=device_type,
        hardware_model=(payload.hardware_model or proto.get("profile") or "prototype")[:64],
        serial_number=(payload.serial_number or f"DISC-{device_type}-{uuid4()[:8]}")[:64],
        local_ip=host,
        pairing_state="DISCOVERED",
        confirmed=False,
        pairing_token=f"pair-{uuid4()}",
        capabilities_json=json.dumps(
            {
                "camera_present": device_type == DEVICE_HOME_HUB,
                "microphone_present": True,
                "speaker_present": True,
                "rotation_supported": device_type == DEVICE_HOME_HUB,
                "fall_sensor_supported": device_type == DEVICE_HOME_HUB,
                "video_supported": device_type == DEVICE_HOME_HUB,
            }
        ),
        updated_at=now(),
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.discover",
        resource_type="pairing",
        resource_id=row.id,
        outcome="allowed",
        metadata={"device_type": device_type, "auto_trusted": False},
    )
    db.commit()
    db.refresh(row)
    return serialize_pairing(row)


def request_pair(db: Session, ctx: UserContext, pairing_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.pair_request", resource_type="pairing")
    row = _owned_pairing(db, actor, pairing_id)
    if row.pairing_state == "UNPAIRED":
        raise HTTPException(status_code=409, detail="Unpaired records cannot be reused.")
    row.pairing_state = "PENDING_PAIR"
    row.confirmed = False
    row.updated_at = now()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.pair_request",
        resource_type="pairing",
        resource_id=row.id,
        outcome="allowed",
        metadata={"pairing_state": "PENDING_PAIR"},
    )
    db.commit()
    db.refresh(row)
    return serialize_pairing(row)


def confirm_pair(db: Session, ctx: UserContext, pairing_id: str, payload: PairConfirm) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.pair_confirm", resource_type="pairing")
    row = _owned_pairing(db, actor, pairing_id)
    if row.pairing_state not in {"DISCOVERED", "PENDING_PAIR"}:
        raise HTTPException(status_code=409, detail="Only a discovered or pending device can be paired.")
    if not payload.confirm:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action="device.pair_confirm",
            resource_type="pairing",
            resource_id=row.id,
            outcome="denied",
            metadata={"reason": "human_confirmation_required"},
        )
        db.commit()
        raise HTTPException(status_code=422, detail="Explicit human confirmation is required to pair.")
    adapter = (payload.adapter_type or "simulated").lower()
    if adapter not in {"simulated", "local_lan", "raspberry_pi", "local_pi"}:
        adapter = "simulated"
    state = simulated_home_hub.default_state() if row.device_type == DEVICE_HOME_HUB else simulated_car_hub.default_state()
    device = LifesaverDevice(
        organization_id=actor.organization_id,
        profile_id=actor.id,
        device_type=row.device_type,
        display_name="Home Hub" if row.device_type == DEVICE_HOME_HUB else "Car Hub",
        serial_number=row.serial_number,
        firmware_version="proto-0.2",
        software_version="lifesaver-v2-bridge",
        status=STATUS_ONLINE,
        adapter_name=adapter,
        adapter_type=adapter,
        pairing_state="ONLINE",
        hardware_model=row.hardware_model,
        local_ip=row.local_ip,
        pairing_token=row.pairing_token,
        state_json=json.dumps(state),
        last_seen_at=now(),
        updated_at=now(),
    )
    db.add(device)
    db.flush()
    for name in capabilities_for(row.device_type):
        db.add(
            LifesaverDeviceCapability(
                organization_id=actor.organization_id,
                device_id=device.id,
                capability_name=name,
                present=True,
            )
        )
    row.device_id = device.id
    row.pairing_state = "PAIRED"
    row.confirmed = True
    row.updated_at = now()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.pair_confirm",
        resource_type="pairing",
        resource_id=row.id,
        outcome="allowed",
        metadata={"device_id": device.id, "adapter_type": adapter},
    )
    db.commit()
    db.refresh(row)
    payload = serialize_pairing(row)
    if adapter == "local_pi":
        payload["device_token"] = row.pairing_token
    return payload


def unpair(db: Session, ctx: UserContext, pairing_id: str) -> dict[str, Any]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.unpair", resource_type="pairing")
    row = _owned_pairing(db, actor, pairing_id)
    row.pairing_state = "UNPAIRED"
    row.confirmed = False
    row.updated_at = now()
    if row.device_id:
        device = (
            db.query(LifesaverDevice)
            .filter(LifesaverDevice.id == row.device_id, LifesaverDevice.organization_id == actor.organization_id)
            .first()
        )
        if device:
            device.pairing_state = "UNPAIRED"
            device.status = "OFFLINE"
            device.updated_at = now()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="device.unpair",
        resource_type="pairing",
        resource_id=row.id,
        outcome="allowed",
        metadata={"unpaired": True},
    )
    db.commit()
    db.refresh(row)
    return serialize_pairing(row)


def list_pairings(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    require_consent(db, ctx, actor, "hardware_simulation", action="device.pair_list", resource_type="pairing")
    rows = (
        db.query(LifesaverDevicePairing)
        .filter(
            LifesaverDevicePairing.organization_id == actor.organization_id,
            LifesaverDevicePairing.profile_id == actor.id,
        )
        .order_by(LifesaverDevicePairing.created_at.desc())
        .limit(20)
        .all()
    )
    return [serialize_pairing(row) for row in rows]


def reject_unknown(db: Session, ctx: UserContext, pairing_id: str) -> None:
    actor = lifesaver_service.get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverDevicePairing)
        .filter(LifesaverDevicePairing.id == pairing_id, LifesaverDevicePairing.organization_id == actor.organization_id)
        .first()
    )
    if row is None:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action="device.unknown",
            resource_type="pairing",
            resource_id=pairing_id,
            outcome="denied",
            metadata={"reason": "unknown_device"},
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Unknown device was rejected.")


def _owned_pairing(db: Session, actor: LifesaverProfile, pairing_id: str) -> LifesaverDevicePairing:
    row = (
        db.query(LifesaverDevicePairing)
        .filter(
            LifesaverDevicePairing.id == pairing_id,
            LifesaverDevicePairing.organization_id == actor.organization_id,
            LifesaverDevicePairing.profile_id == actor.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Pairing record was not found.")
    return row
