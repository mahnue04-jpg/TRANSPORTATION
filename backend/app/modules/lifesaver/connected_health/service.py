"""Connected-health and home-test coordination. Simulation and storage only."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.helpers import now
from app.modules.lifesaver.audit import write_audit
from app.modules.lifesaver.connected_health import ecosystem
from app.modules.lifesaver.connected_health.constants import (
    CONNECTED_DEVICE_TYPES,
    CONNECTED_HEALTH_DISCLAIMER,
    CONNECTION_METHODS,
    CONSENT_CIRCLE_HEALTH,
    CONSENT_CONNECTED_DEVICES,
    CONSENT_HOME_TESTS,
    CONSENT_PROVIDER_SHARE,
    CONSENT_RESULT_DOCS,
    DATA_QUALITY,
    DEVICE_SIM_BANNER,
    HOME_TEST_CATEGORIES,
    KIT_COORDINATION_BANNER,
    KIT_FORWARD,
    KIT_STATUSES,
    KIT_TERMINAL,
    NO_DIAGNOSIS_BANNER,
    NO_EMERGENCY_BANNER,
    PERM_VIEW_CONNECTED,
    PERM_VIEW_KITS,
    PERM_VIEW_RESULTS,
    READING_KINDS,
    RESULT_SOURCES,
    UNSUPPORTED_DEVICE_TYPES,
)
from app.modules.lifesaver.connected_health.hub_display import cards_from_rows, publish
from app.modules.lifesaver.connected_health.models import (
    LifesaverConnectedDevice,
    LifesaverConnectedReading,
    LifesaverHomeTestKit,
    LifesaverResultDocument,
)
from app.modules.lifesaver.security import require_consent, require_subject_access
from app.modules.lifesaver.service import get_or_create_profile


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _last4(value: str | None) -> str | None:
    digits = "".join(ch for ch in (value or "") if ch.isalnum())
    if not digits:
        return None
    return digits[-4:].upper()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _subject(db: Session, ctx: UserContext, member_profile_id: str | None, permission: str, action: str, resource: str):
    actor = get_or_create_profile(db, ctx)
    return actor, require_subject_access(
        db, ctx, actor, member_profile_id, permission, action=action, resource_type=resource
    )


def _audit(db: Session, ctx: UserContext, profile, action: str, resource_type: str, resource_id: str | None, **meta: Any) -> None:
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome="allowed",
        metadata=meta,
    )


def serialize_device(row: LifesaverConnectedDevice) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "profile_id": row.profile_id,
        "device_type": row.device_type,
        "manufacturer": row.manufacturer,
        "model": row.model,
        "device_alias": row.device_alias,
        "connection_method": row.connection_method,
        "integration_status": row.integration_status,
        "approval_status": row.approval_status,
        "serial_last4": row.serial_last4,
        "paired_at": _iso(row.paired_at),
        "last_seen_at": _iso(row.last_seen_at),
        "battery": row.battery_percent,
        "data_source": row.data_source,
        "data_quality": row.data_quality,
        "simulated": True,
        "real_connection": False,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "banner": DEVICE_SIM_BANNER,
        "disclaimer": CONNECTED_HEALTH_DISCLAIMER,
        "emergency_services_contacted": False,
    }


def serialize_reading(row: LifesaverConnectedReading) -> dict[str, Any]:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "reading_kind": row.reading_kind,
        "value_primary": row.value_primary,
        "value_secondary": row.value_secondary,
        "unit": row.unit,
        "data_quality": row.data_quality,
        "review_status": row.review_status,
        "human_review_required": row.human_review_required,
        "emergency_services_contacted": False,
        "diagnosis_generated": False,
        "simulated": True,
        "recorded_at": _iso(row.recorded_at),
        "banner": DEVICE_SIM_BANNER,
        "review_copy": NO_DIAGNOSIS_BANNER if row.human_review_required else None,
    }


def serialize_kit(row: LifesaverHomeTestKit) -> dict[str, Any]:
    return {
        "id": row.id,
        "test_category": row.test_category,
        "manufacturer_or_lab": row.manufacturer_or_lab,
        "kit_id_last4": row.kit_id_last4,
        "expires_at": _iso(row.expires_at),
        "status": row.status,
        "collected_at": _iso(row.collected_at),
        "shipping_status": row.shipping_status,
        "result_document_id": row.result_document_id,
        "ordering_source": row.ordering_source,
        "provider_share_status": row.provider_share_status,
        "circle_share_status": row.circle_share_status,
        "notes": row.notes,
        "simulated": True,
        "diagnosis_generated": False,
        "emergency_services_contacted": False,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "banner": KIT_COORDINATION_BANNER,
    }


def serialize_result(row: LifesaverResultDocument) -> dict[str, Any]:
    return {
        "id": row.id,
        "kit_id": row.kit_id,
        "source": row.source,
        "received_at": _iso(row.received_at),
        "document_reference": row.document_reference,
        "review_status": row.review_status,
        "provider_review_requested": row.provider_review_requested,
        "user_acknowledged": row.user_acknowledged,
        "provider_share_status": row.provider_share_status,
        "circle_share_status": row.circle_share_status,
        "informational_note": row.informational_note,
        "simulated": True,
        "diagnosis_generated": False,
        "emergency_services_contacted": False,
        "created_at": _iso(row.created_at),
        "banner": CONNECTED_HEALTH_DISCLAIMER,
    }


def _refresh_hub(db: Session, profile) -> None:
    devices = [
        serialize_device(row)
        for row in db.query(LifesaverConnectedDevice)
        .filter(
            LifesaverConnectedDevice.organization_id == profile.organization_id,
            LifesaverConnectedDevice.profile_id == profile.id,
        )
        .order_by(LifesaverConnectedDevice.created_at.desc())
        .limit(6)
    ]
    kits = [
        serialize_kit(row)
        for row in db.query(LifesaverHomeTestKit)
        .filter(
            LifesaverHomeTestKit.organization_id == profile.organization_id,
            LifesaverHomeTestKit.profile_id == profile.id,
        )
        .order_by(LifesaverHomeTestKit.updated_at.desc())
        .limit(6)
    ]
    results = [
        serialize_result(row)
        for row in db.query(LifesaverResultDocument)
        .filter(
            LifesaverResultDocument.organization_id == profile.organization_id,
            LifesaverResultDocument.profile_id == profile.id,
        )
        .order_by(LifesaverResultDocument.created_at.desc())
        .limit(4)
    ]
    publish(cards_from_rows(devices=devices, kits=kits, results=results))


def meta() -> dict[str, Any]:
    return {
        "disclaimer": CONNECTED_HEALTH_DISCLAIMER,
        "device_banner": DEVICE_SIM_BANNER,
        "kit_banner": KIT_COORDINATION_BANNER,
        "no_diagnosis": NO_DIAGNOSIS_BANNER,
        "no_emergency": NO_EMERGENCY_BANNER,
        "device_types": sorted(CONNECTED_DEVICE_TYPES),
        "test_categories": sorted(HOME_TEST_CATEGORIES),
        "kit_statuses": list(KIT_STATUSES),
        "real_device_connections": False,
        "real_lab_processing": False,
        "emergency_services_contacted": False,
        "ecosystem": ecosystem.snapshot(),
    }


def list_devices(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor, subject = _subject(db, ctx, member_profile_id, PERM_VIEW_CONNECTED, "cdev.list", "connected_device")
    require_consent(db, ctx, subject, CONSENT_CONNECTED_DEVICES, action="cdev.list", resource_type="connected_device")
    rows = (
        db.query(LifesaverConnectedDevice)
        .filter(
            LifesaverConnectedDevice.organization_id == actor.organization_id,
            LifesaverConnectedDevice.profile_id == subject.id,
        )
        .order_by(LifesaverConnectedDevice.created_at.desc())
        .all()
    )
    return [serialize_device(row) for row in rows]


def create_device(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    actor, subject = _subject(db, ctx, payload.member_profile_id, PERM_VIEW_CONNECTED, "cdev.create", "connected_device")
    require_consent(db, ctx, subject, CONSENT_CONNECTED_DEVICES, action="cdev.create", resource_type="connected_device")
    if payload.client_request_id:
        existing = (
            db.query(LifesaverConnectedDevice)
            .filter(
                LifesaverConnectedDevice.organization_id == actor.organization_id,
                LifesaverConnectedDevice.profile_id == subject.id,
                LifesaverConnectedDevice.client_request_id == payload.client_request_id,
            )
            .first()
        )
        if existing:
            return serialize_device(existing)
    device_type = (payload.device_type or "").strip()
    unsupported = device_type in UNSUPPORTED_DEVICE_TYPES or device_type not in CONNECTED_DEVICE_TYPES
    method = payload.connection_method or "simulated"
    if method not in CONNECTION_METHODS:
        raise HTTPException(status_code=422, detail="Unsupported connection method.")
    if method != "simulated":
        method = "simulated"
    row = LifesaverConnectedDevice(
        organization_id=actor.organization_id,
        profile_id=subject.id,
        device_type=device_type if device_type else "future_approved_health_sensor",
        manufacturer=(payload.manufacturer or "unspecified")[:80],
        model=(payload.model or "simulated")[:80],
        device_alias=(payload.device_alias or "Simulated device")[:80],
        connection_method=method,
        integration_status="UNSUPPORTED" if unsupported else "SIMULATED",
        approval_status="unsupported" if unsupported else "approved_simulated",
        serial_last4=_last4(payload.serial_last4),
        battery_percent=payload.battery_percent,
        data_source="simulated",
        data_quality="unknown",
        simulated=True,
        real_connection=False,
        client_request_id=payload.client_request_id,
    )
    db.add(row)
    _audit(db, ctx, subject, "cdev.create", "connected_device", None, device_type=row.device_type, simulated=True)
    db.commit()
    db.refresh(row)
    _refresh_hub(db, subject)
    return serialize_device(row)


def _device(db: Session, ctx: UserContext, device_id: str, member_profile_id: str | None):
    actor, subject = _subject(db, ctx, member_profile_id, PERM_VIEW_CONNECTED, "cdev.get", "connected_device")
    require_consent(db, ctx, subject, CONSENT_CONNECTED_DEVICES, action="cdev.get", resource_type="connected_device")
    row = (
        db.query(LifesaverConnectedDevice)
        .filter(
            LifesaverConnectedDevice.id == device_id,
            LifesaverConnectedDevice.organization_id == actor.organization_id,
            LifesaverConnectedDevice.profile_id == subject.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Connected device was not found.")
    return actor, subject, row


def pair_device(db: Session, ctx: UserContext, device_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _device(db, ctx, device_id, member_profile_id)
    if row.approval_status == "unsupported" or row.integration_status == "UNSUPPORTED":
        raise HTTPException(status_code=409, detail="Unsupported device cannot be paired.")
    if row.integration_status == "REVOKED":
        raise HTTPException(status_code=409, detail="Revoked device cannot be paired.")
    row.integration_status = "CONNECTED"
    row.approval_status = "approved_simulated"
    row.paired_at = now()
    row.last_seen_at = now()
    row.data_quality = "good"
    row.updated_at = now()
    row.simulated = True
    row.real_connection = False
    _audit(db, ctx, subject, "cdev.pair", "connected_device", row.id, status="CONNECTED")
    db.commit()
    db.refresh(row)
    _refresh_hub(db, subject)
    return serialize_device(row)


def mark_device_offline(db: Session, ctx: UserContext, device_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _device(db, ctx, device_id, member_profile_id)
    row.integration_status = "OFFLINE"
    row.data_quality = "stale"
    row.updated_at = now()
    _audit(db, ctx, subject, "cdev.offline", "connected_device", row.id, status="OFFLINE")
    db.commit()
    db.refresh(row)
    _refresh_hub(db, subject)
    return serialize_device(row)


def revoke_device(db: Session, ctx: UserContext, device_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _device(db, ctx, device_id, member_profile_id)
    row.integration_status = "REVOKED"
    row.approval_status = "revoked"
    row.updated_at = now()
    _audit(db, ctx, subject, "cdev.revoke", "connected_device", row.id, status="REVOKED")
    db.commit()
    db.refresh(row)
    _refresh_hub(db, subject)
    return serialize_device(row)


def add_reading(db: Session, ctx: UserContext, device_id: str, payload) -> dict[str, Any]:
    _actor, subject, device = _device(db, ctx, device_id, payload.member_profile_id)
    kind = (payload.reading_kind or "").strip()
    if kind not in READING_KINDS:
        raise HTTPException(status_code=422, detail="Unsupported reading kind.")
    quality = payload.data_quality or "unknown"
    if quality not in DATA_QUALITY:
        quality = "unknown"
    review = "NEEDS_HUMAN_REVIEW" if payload.flag_for_review else "none"
    row = LifesaverConnectedReading(
        organization_id=device.organization_id,
        profile_id=subject.id,
        device_id=device.id,
        reading_kind=kind,
        value_primary=payload.value_primary,
        value_secondary=payload.value_secondary,
        unit=payload.unit,
        data_quality=quality,
        review_status=review,
        human_review_required=bool(payload.flag_for_review),
        emergency_services_contacted=False,
        diagnosis_generated=False,
        simulated=True,
        recorded_at=now(),
    )
    device.last_seen_at = now()
    device.updated_at = now()
    db.add(row)
    _audit(
        db,
        ctx,
        subject,
        "cdev.reading",
        "connected_reading",
        None,
        device_id=device.id,
        reading_kind=kind,
        review_status=review,
    )
    db.commit()
    db.refresh(row)
    return serialize_reading(row)


def list_readings(db: Session, ctx: UserContext, device_id: str, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    _actor, _subject, device = _device(db, ctx, device_id, member_profile_id)
    rows = (
        db.query(LifesaverConnectedReading)
        .filter(LifesaverConnectedReading.device_id == device.id)
        .order_by(LifesaverConnectedReading.recorded_at.desc())
        .all()
    )
    return [serialize_reading(row) for row in rows]


def _expire_if_needed(row: LifesaverHomeTestKit) -> bool:
    expires = _aware(row.expires_at)
    if expires and row.status not in KIT_TERMINAL | {"RESULT_AVAILABLE", "RESULT_PENDING", "PROVIDER_SHARED"}:
        current = now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if expires < current:
            row.status = "EXPIRED"
            row.updated_at = now()
            return True
    return False


def list_kits(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor, subject = _subject(db, ctx, member_profile_id, PERM_VIEW_KITS, "kit.list", "home_test_kit")
    require_consent(db, ctx, subject, CONSENT_HOME_TESTS, action="kit.list", resource_type="home_test_kit")
    rows = (
        db.query(LifesaverHomeTestKit)
        .filter(
            LifesaverHomeTestKit.organization_id == actor.organization_id,
            LifesaverHomeTestKit.profile_id == subject.id,
        )
        .order_by(LifesaverHomeTestKit.created_at.desc())
        .all()
    )
    changed = False
    for row in rows:
        changed = _expire_if_needed(row) or changed
    if changed:
        db.commit()
    return [serialize_kit(row) for row in rows]


def create_kit(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    actor, subject = _subject(db, ctx, payload.member_profile_id, PERM_VIEW_KITS, "kit.create", "home_test_kit")
    require_consent(db, ctx, subject, CONSENT_HOME_TESTS, action="kit.create", resource_type="home_test_kit")
    if payload.client_request_id:
        existing = (
            db.query(LifesaverHomeTestKit)
            .filter(
                LifesaverHomeTestKit.organization_id == actor.organization_id,
                LifesaverHomeTestKit.profile_id == subject.id,
                LifesaverHomeTestKit.client_request_id == payload.client_request_id,
            )
            .first()
        )
        if existing:
            return serialize_kit(existing)
    category = (payload.test_category or "").strip()
    if category not in HOME_TEST_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unsupported home-test category.")
    row = LifesaverHomeTestKit(
        organization_id=actor.organization_id,
        profile_id=subject.id,
        test_category=category,
        manufacturer_or_lab=(payload.manufacturer_or_lab or "unspecified")[:80],
        kit_id_last4=_last4(payload.kit_id_last4),
        expires_at=_aware(payload.expires_at),
        status="ORDERED",
        notes=(payload.notes or None),
        client_request_id=payload.client_request_id,
        simulated=True,
        diagnosis_generated=False,
        emergency_services_contacted=False,
    )
    _expire_if_needed(row)
    db.add(row)
    _audit(db, ctx, subject, "kit.create", "home_test_kit", None, test_category=category, status=row.status)
    db.commit()
    db.refresh(row)
    _refresh_hub(db, subject)
    return serialize_kit(row)


def _kit(db: Session, ctx: UserContext, kit_id: str, member_profile_id: str | None):
    actor, subject = _subject(db, ctx, member_profile_id, PERM_VIEW_KITS, "kit.get", "home_test_kit")
    require_consent(db, ctx, subject, CONSENT_HOME_TESTS, action="kit.get", resource_type="home_test_kit")
    row = (
        db.query(LifesaverHomeTestKit)
        .filter(
            LifesaverHomeTestKit.id == kit_id,
            LifesaverHomeTestKit.organization_id == actor.organization_id,
            LifesaverHomeTestKit.profile_id == subject.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Home-test kit was not found.")
    _expire_if_needed(row)
    return actor, subject, row


def transition_kit(db: Session, ctx: UserContext, kit_id: str, payload) -> dict[str, Any]:
    _actor, subject, row = _kit(db, ctx, kit_id, payload.member_profile_id)
    if row.status == "EXPIRED":
        raise HTTPException(status_code=409, detail="Expired kit cannot advance.")
    if row.status in KIT_TERMINAL and payload.status not in {None, row.status}:
        raise HTTPException(status_code=409, detail="Terminal kit status cannot advance.")
    requested = (payload.status or "").strip() or KIT_FORWARD.get(row.status)
    if requested == "CANCELLED":
        row.status = "CANCELLED"
    elif requested == "EXPIRED":
        row.status = "EXPIRED"
    elif requested not in KIT_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown kit status.")
    elif requested != row.status and KIT_FORWARD.get(row.status) != requested:
        raise HTTPException(status_code=409, detail="Kit status must advance one step at a time.")
    else:
        row.status = requested
    if row.status == "COLLECTED":
        row.collected_at = now()
    if row.status in {"PICKUP_REQUESTED", "SHIPPED", "LAB_RECEIVED"}:
        row.shipping_status = row.status.lower()
    row.updated_at = now()
    row.diagnosis_generated = False
    row.emergency_services_contacted = False
    _audit(db, ctx, subject, "kit.transition", "home_test_kit", row.id, status=row.status)
    db.commit()
    db.refresh(row)
    _refresh_hub(db, subject)
    return serialize_kit(row)


def expire_kit(db: Session, ctx: UserContext, kit_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _kit(db, ctx, kit_id, member_profile_id)
    row.status = "EXPIRED"
    row.updated_at = now()
    _audit(db, ctx, subject, "kit.expire", "home_test_kit", row.id, status="EXPIRED")
    db.commit()
    db.refresh(row)
    return serialize_kit(row)


def list_results(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor, subject = _subject(db, ctx, member_profile_id, PERM_VIEW_RESULTS, "result.list", "result_document")
    require_consent(db, ctx, subject, CONSENT_RESULT_DOCS, action="result.list", resource_type="result_document")
    rows = (
        db.query(LifesaverResultDocument)
        .filter(
            LifesaverResultDocument.organization_id == actor.organization_id,
            LifesaverResultDocument.profile_id == subject.id,
        )
        .order_by(LifesaverResultDocument.created_at.desc())
        .all()
    )
    return [serialize_result(row) for row in rows]


def create_result(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    actor, subject = _subject(db, ctx, payload.member_profile_id, PERM_VIEW_RESULTS, "result.create", "result_document")
    require_consent(db, ctx, subject, CONSENT_RESULT_DOCS, action="result.create", resource_type="result_document")
    source = payload.source if payload.source in RESULT_SOURCES else "user_uploaded"
    review = "NEEDS_HUMAN_REVIEW" if payload.flag_for_review else "RECEIVED"
    kit_id = payload.kit_id
    if kit_id:
        kit = (
            db.query(LifesaverHomeTestKit)
            .filter(
                LifesaverHomeTestKit.id == kit_id,
                LifesaverHomeTestKit.organization_id == actor.organization_id,
                LifesaverHomeTestKit.profile_id == subject.id,
            )
            .first()
        )
        if kit is None:
            raise HTTPException(status_code=404, detail="Home-test kit was not found.")
    row = LifesaverResultDocument(
        organization_id=actor.organization_id,
        profile_id=subject.id,
        kit_id=kit_id,
        source=source,
        document_reference=(payload.document_reference or "ref-redacted")[:80],
        review_status=review,
        informational_note="Informational coordination record only. Not a diagnosis.",
        simulated=True,
        diagnosis_generated=False,
        emergency_services_contacted=False,
    )
    db.add(row)
    if kit_id:
        kit = db.query(LifesaverHomeTestKit).filter(LifesaverHomeTestKit.id == kit_id).first()
        if kit:
            kit.result_document_id = row.id
            if kit.status in {"LAB_RECEIVED", "RESULT_PENDING", "SHIPPED"}:
                kit.status = "RESULT_AVAILABLE"
            kit.updated_at = now()
    _audit(db, ctx, subject, "result.create", "result_document", None, source=source, review_status=review)
    db.commit()
    db.refresh(row)
    _refresh_hub(db, subject)
    return serialize_result(row)


def _result(db: Session, ctx: UserContext, result_id: str, member_profile_id: str | None):
    actor, subject = _subject(db, ctx, member_profile_id, PERM_VIEW_RESULTS, "result.get", "result_document")
    require_consent(db, ctx, subject, CONSENT_RESULT_DOCS, action="result.get", resource_type="result_document")
    row = (
        db.query(LifesaverResultDocument)
        .filter(
            LifesaverResultDocument.id == result_id,
            LifesaverResultDocument.organization_id == actor.organization_id,
            LifesaverResultDocument.profile_id == subject.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Result document was not found.")
    return actor, subject, row


def acknowledge_result(db: Session, ctx: UserContext, result_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _result(db, ctx, result_id, member_profile_id)
    row.user_acknowledged = True
    if row.review_status == "NEEDS_HUMAN_REVIEW":
        row.review_status = "ACKNOWLEDGED"
    row.updated_at = now()
    row.emergency_services_contacted = False
    row.diagnosis_generated = False
    _audit(db, ctx, subject, "result.acknowledge", "result_document", row.id, review_status=row.review_status)
    db.commit()
    db.refresh(row)
    return serialize_result(row)


def share_result_provider(db: Session, ctx: UserContext, result_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _result(db, ctx, result_id, member_profile_id)
    require_consent(db, ctx, subject, CONSENT_PROVIDER_SHARE, action="result.provider_share", resource_type="result_document")
    row.provider_share_status = "shared_simulated"
    row.provider_review_requested = True
    row.review_status = "PROVIDER_REVIEW_REQUESTED"
    row.updated_at = now()
    _audit(db, ctx, subject, "result.provider_share", "result_document", row.id, share="provider_simulated")
    db.commit()
    db.refresh(row)
    return serialize_result(row)


def share_result_circle(db: Session, ctx: UserContext, result_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _result(db, ctx, result_id, member_profile_id)
    require_consent(db, ctx, subject, CONSENT_CIRCLE_HEALTH, action="result.circle_share", resource_type="result_document")
    row.circle_share_status = "shared_simulated"
    if row.review_status not in {"PROVIDER_REVIEW_REQUESTED", "NEEDS_HUMAN_REVIEW"}:
        row.review_status = "SHARED_CIRCLE"
    row.updated_at = now()
    _audit(db, ctx, subject, "result.circle_share", "result_document", row.id, share="circle_simulated")
    db.commit()
    db.refresh(row)
    return serialize_result(row)


def share_kit_provider(db: Session, ctx: UserContext, kit_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _kit(db, ctx, kit_id, member_profile_id)
    require_consent(db, ctx, subject, CONSENT_PROVIDER_SHARE, action="kit.provider_share", resource_type="home_test_kit")
    row.provider_share_status = "shared_simulated"
    row.updated_at = now()
    _audit(db, ctx, subject, "kit.provider_share", "home_test_kit", row.id, share="provider_simulated")
    db.commit()
    db.refresh(row)
    return serialize_kit(row)


def share_kit_circle(db: Session, ctx: UserContext, kit_id: str, member_profile_id: str | None = None) -> dict[str, Any]:
    _actor, subject, row = _kit(db, ctx, kit_id, member_profile_id)
    require_consent(db, ctx, subject, CONSENT_CIRCLE_HEALTH, action="kit.circle_share", resource_type="home_test_kit")
    row.circle_share_status = "shared_simulated"
    row.updated_at = now()
    _audit(db, ctx, subject, "kit.circle_share", "home_test_kit", row.id, share="circle_simulated")
    db.commit()
    db.refresh(row)
    return serialize_kit(row)


def hub_summary(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> dict[str, Any]:
    try:
        devices = list_devices(db, ctx, member_profile_id)
    except HTTPException:
        devices = []
    try:
        kits = list_kits(db, ctx, member_profile_id)
    except HTTPException:
        kits = []
    try:
        results = list_results(db, ctx, member_profile_id)
    except HTTPException:
        results = []
    cards = cards_from_rows(devices=devices, kits=kits, results=results)
    publish(cards)
    return {
        "cards": cards,
        "banner": DEVICE_SIM_BANNER,
        "diagnoses": False,
        "emergency_services_contacted": False,
        "device_count": len(devices),
        "kit_count": len(kits),
        "result_count": len(results),
    }
