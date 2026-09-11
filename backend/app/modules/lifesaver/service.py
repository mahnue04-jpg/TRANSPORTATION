"""Lifesaver Care Cloud application services (isolated from frozen modules)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.db.models import User as PlatformUser
from app.helpers import json_dumps, json_loads_or, now
from app.modules.lifesaver.audit import write_audit
from app.modules.lifesaver.constants import (
    AI_DISCLAIMER,
    CAREGIVER_PERMISSIONS,
    CAREGIVER_PERMISSION_LABELS,
    CONSENT_LABELS,
    CONSENT_TYPES,
    CONSENT_VERSION,
    DEFAULT_ACCESSIBILITY,
    DEFAULT_CAREGIVER_PERMISSIONS,
    DEFAULT_PROFILE_ROLE,
    DEVICE_SIM_LABEL,
    NOTIFICATION_SIM_LABEL,
    PRODUCT_DISCLAIMER,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    PROFILE_ROLES,
    READING_SOURCES,
    READING_TYPES,
    READING_UNITS,
    READING_SOURCE_DISCLAIMER,
    SOS_DISCLAIMER,
    SOURCE_EXTERNAL_RESERVED,
    SOURCE_SIMULATED,
    SOURCE_SIMULATED_DEVICE,
    SOURCE_USER_ENTERED,
    TRANSPORT_COORD_DISCLAIMER,
)
from app.modules.lifesaver.coordination import (
    COORDINATION_FILTERS,
    build_coordination_cards,
    coordination_disclaimer,
    matches_filter,
    summarize_counts,
)
from app.modules.lifesaver.integrations import device_ingestion, notification_outbox, nova_adapter, transport_bridge
from app.modules.lifesaver.models import (
    LifesaverAlert,
    LifesaverAppointment,
    LifesaverCareCircleMember,
    LifesaverCareTask,
    LifesaverConsent,
    LifesaverConversation,
    LifesaverConversationMessage,
    LifesaverHandoff,
    LifesaverHealthReading,
    LifesaverJournalEntry,
    LifesaverMedication,
    LifesaverNotificationOutbox,
    LifesaverProfile,
    LifesaverReminder,
    LifesaverSosDemonstration,
    LifesaverTransportRequest,
    LifesaverWellnessCheckin,
)
from app.modules.lifesaver.security import (
    active_circle_link,
    has_consent,
    parse_permissions,
    require_consent,
    require_subject_access,
    tenant_key,
)
from app.modules.lifesaver.transport import get_or_create_connection, serialize_connection, update_connection


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _ensure_profile_consents(db: Session, profile: LifesaverProfile, actor_user_id: str) -> None:
    existing = {
        row.consent_type
        for row in db.query(LifesaverConsent).filter(LifesaverConsent.profile_id == profile.id).all()
    }
    added = False
    for consent_type in CONSENT_TYPES:
        if consent_type in existing:
            continue
        db.add(
            LifesaverConsent(
                organization_id=profile.organization_id,
                profile_id=profile.id,
                consent_type=consent_type,
                granted=False,
                version=CONSENT_VERSION,
                actor_user_id=actor_user_id,
            )
        )
        added = True
    if added:
        db.flush()


def get_or_create_profile(db: Session, ctx: UserContext) -> LifesaverProfile:
    org_id = tenant_key(ctx)
    profile = (
        db.query(LifesaverProfile)
        .filter(LifesaverProfile.organization_id == org_id, LifesaverProfile.user_id == ctx.user_id)
        .first()
    )
    if profile:
        _ensure_profile_consents(db, profile, ctx.user_id)
        return profile
    profile = LifesaverProfile(
        organization_id=org_id,
        user_id=ctx.user_id,
        display_name=ctx.email.split("@")[0],
        profile_role=DEFAULT_PROFILE_ROLE,
        accessibility_json=json_dumps(DEFAULT_ACCESSIBILITY),
    )
    db.add(profile)
    db.flush()
    for consent_type in CONSENT_TYPES:
        db.add(
            LifesaverConsent(
                organization_id=org_id,
                profile_id=profile.id,
                consent_type=consent_type,
                granted=False,
                version=CONSENT_VERSION,
                actor_user_id=ctx.user_id,
            )
        )
    db.flush()
    write_audit(
        db,
        organization_id=org_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="profile.create",
        resource_type="profile",
        resource_id=profile.id,
        outcome="allowed",
    )
    return profile


def serialize_profile(profile: LifesaverProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "organization_id": profile.organization_id,
        "display_name": profile.display_name,
        "profile_role": profile.profile_role,
        "timezone": profile.timezone,
        "accessibility": json_loads_or(profile.accessibility_json, dict(DEFAULT_ACCESSIBILITY)),
        "created_at": _iso(profile.created_at),
    }


def serialize_consent(row: LifesaverConsent) -> dict[str, Any]:
    return {
        "consent_type": row.consent_type,
        "label": CONSENT_LABELS.get(row.consent_type, row.consent_type),
        "granted": bool(row.granted),
        "version": row.version,
        "granted_at": _iso(row.granted_at),
        "revoked_at": _iso(row.revoked_at),
    }


def product_meta() -> dict[str, Any]:
    return {
        "product": PRODUCT_NAME,
        "version": PRODUCT_VERSION,
        "disclaimer": PRODUCT_DISCLAIMER,
        "sos_disclaimer": SOS_DISCLAIMER,
        "ai_disclaimer": AI_DISCLAIMER,
        "reading_disclaimer": READING_SOURCE_DISCLAIMER,
        "transport_disclaimer": TRANSPORT_COORD_DISCLAIMER,
        "notification_disclaimer": NOTIFICATION_SIM_LABEL,
        "device_disclaimer": DEVICE_SIM_LABEL,
        "hardware_disclaimer": (
            "Simulated AMICOR hub controls only. This is not a medical device, not a "
            "certified fall detector, and does not contact emergency services."
        ),
        "diagnostic_device": False,
        "emergency_response_guaranteed": False,
        "caregiver_permissions": [
            {
                "id": key,
                "label": CAREGIVER_PERMISSION_LABELS.get(key, key),
                "granted_by_default": key in DEFAULT_CAREGIVER_PERMISSIONS,
            }
            for key in CAREGIVER_PERMISSIONS
        ],
    }


def bootstrap(db: Session, ctx: UserContext) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    consents = (
        db.query(LifesaverConsent)
        .filter(LifesaverConsent.profile_id == profile.id)
        .order_by(LifesaverConsent.consent_type.asc())
        .all()
    )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="profile.read",
        resource_type="profile",
        resource_id=profile.id,
        outcome="allowed",
    )
    db.commit()
    return {
        **product_meta(),
        "profile": serialize_profile(profile),
        "consents": [serialize_consent(row) for row in consents],
        "session": {
            "user_id": ctx.user_id,
            "email": ctx.email,
            "platform_role": ctx.role,
            "organization_id": profile.organization_id,
        },
    }


def update_profile(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    if payload.display_name:
        profile.display_name = payload.display_name.strip()[:128]
    if payload.profile_role:
        if payload.profile_role not in PROFILE_ROLES:
            raise HTTPException(status_code=422, detail="Unsupported Lifesaver profile role.")
        profile.profile_role = payload.profile_role
    if payload.timezone:
        profile.timezone = payload.timezone[:64]
    profile.updated_at = now()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="profile.update",
        resource_type="profile",
        resource_id=profile.id,
        outcome="allowed",
        metadata={"profile_role": profile.profile_role},
    )
    db.commit()
    return serialize_profile(profile)


def list_consents(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    rows = (
        db.query(LifesaverConsent)
        .filter(LifesaverConsent.profile_id == profile.id)
        .order_by(LifesaverConsent.consent_type.asc())
        .all()
    )
    db.commit()
    return [serialize_consent(row) for row in rows]


def set_consent(db: Session, ctx: UserContext, consent_type: str, granted: bool) -> dict[str, Any]:
    if consent_type not in CONSENT_TYPES:
        raise HTTPException(status_code=422, detail="Unknown consent type.")
    profile = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverConsent)
        .filter(LifesaverConsent.profile_id == profile.id, LifesaverConsent.consent_type == consent_type)
        .first()
    )
    if row is None:
        row = LifesaverConsent(
            organization_id=profile.organization_id,
            profile_id=profile.id,
            consent_type=consent_type,
            version=CONSENT_VERSION,
            actor_user_id=ctx.user_id,
            granted=False,
        )
        db.add(row)
    row.granted = bool(granted)
    row.version = CONSENT_VERSION
    row.actor_user_id = ctx.user_id
    row.updated_at = now()
    if granted:
        row.granted_at = now()
        row.revoked_at = None
    else:
        row.revoked_at = now()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="consent.update",
        resource_type="consent",
        resource_id=row.id,
        outcome="allowed",
        metadata={"consent_type": consent_type, "granted": granted},
    )
    db.commit()
    return serialize_consent(row)


def update_accessibility(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    current = json_loads_or(profile.accessibility_json, dict(DEFAULT_ACCESSIBILITY))
    for key in DEFAULT_ACCESSIBILITY:
        value = getattr(payload, key, None)
        if value is not None:
            current[key] = bool(value)
    profile.accessibility_json = json_dumps(current)
    profile.updated_at = now()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="accessibility.update",
        resource_type="accessibility",
        resource_id=profile.id,
        outcome="allowed",
        metadata={"keys": sorted(current.keys())},
    )
    db.commit()
    return current


def _mark_due_reminders(db: Session, profile: LifesaverProfile) -> None:
    due_rows = (
        db.query(LifesaverReminder)
        .filter(
            LifesaverReminder.organization_id == profile.organization_id,
            LifesaverReminder.profile_id == profile.id,
            LifesaverReminder.status == "scheduled",
            LifesaverReminder.due_at <= now(),
        )
        .all()
    )
    for row in due_rows:
        row.status = "due"


def _create_reminders_for_times(
    db: Session,
    profile: LifesaverProfile,
    *,
    kind: str,
    title: str,
    source_type: str,
    source_id: str,
    times: list[str],
    days: int = 7,
) -> None:
    base = now().replace(second=0, microsecond=0)
    for offset in range(days):
        day = (base + timedelta(days=offset)).date()
        for stamp in times:
            try:
                hour_s, minute_s = stamp.split(":", 1)
                due_at = datetime(
                    day.year,
                    day.month,
                    day.day,
                    int(hour_s),
                    int(minute_s),
                    tzinfo=base.tzinfo,
                )
            except Exception:
                continue
            if due_at < now():
                continue
            db.add(
                LifesaverReminder(
                    organization_id=profile.organization_id,
                    profile_id=profile.id,
                    kind=kind,
                    title=title[:160],
                    due_at=due_at,
                    status="scheduled",
                    source_type=source_type,
                    source_id=source_id,
                )
            )


def today_view(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db,
        ctx,
        actor,
        member_profile_id,
        "view_today",
        action="today.read",
        resource_type="today",
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "care_cloud_use", action="today.read", resource_type="today")
    _mark_due_reminders(db, subject)
    reminders = (
        db.query(LifesaverReminder)
        .filter(
            LifesaverReminder.organization_id == subject.organization_id,
            LifesaverReminder.profile_id == subject.id,
            LifesaverReminder.status.in_(("scheduled", "due")),
        )
        .order_by(LifesaverReminder.due_at.asc())
        .limit(12)
        .all()
    )
    appointments = (
        db.query(LifesaverAppointment)
        .filter(
            LifesaverAppointment.organization_id == subject.organization_id,
            LifesaverAppointment.profile_id == subject.id,
            LifesaverAppointment.starts_at >= now() - timedelta(hours=1),
        )
        .order_by(LifesaverAppointment.starts_at.asc())
        .limit(8)
        .all()
    )
    tasks = (
        db.query(LifesaverCareTask)
        .filter(
            LifesaverCareTask.organization_id == subject.organization_id,
            LifesaverCareTask.member_profile_id == subject.id,
            LifesaverCareTask.status == "open",
        )
        .order_by(LifesaverCareTask.created_at.desc())
        .limit(8)
        .all()
    )
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="today.read",
        resource_type="today",
        resource_id=subject.id,
        outcome="allowed",
        metadata={"viewer_is_owner": subject.id == actor.id},
    )
    db.commit()
    return {
        "disclaimer": PRODUCT_DISCLAIMER,
        "subject_profile_id": subject.id,
        "viewer_profile_id": actor.id,
        "viewer_is_owner": subject.id == actor.id,
        "reminders": [_serialize_reminder(row) for row in reminders],
        "appointments": [_serialize_appointment(row) for row in appointments],
        "tasks": [_serialize_task(row) for row in tasks],
    }


def list_medications(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_medications", action="medication.list", resource_type="medication"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "reminders", action="medication.list", resource_type="medication")
    rows = (
        db.query(LifesaverMedication)
        .filter(
            LifesaverMedication.organization_id == subject.organization_id,
            LifesaverMedication.profile_id == subject.id,
            LifesaverMedication.active.is_(True),
        )
        .order_by(LifesaverMedication.created_at.desc())
        .all()
    )
    db.commit()
    return [_serialize_medication(row) for row in rows]


def create_medication(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "reminders", action="medication.create", resource_type="medication")
    times = [stamp.strip() for stamp in payload.schedule_times if stamp and stamp.strip()]
    row = LifesaverMedication(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        name=payload.name.strip()[:160],
        instructions=(payload.instructions or "").strip()[:512] or None,
        schedule_json=json_dumps(times),
        active=True,
    )
    db.add(row)
    db.flush()
    _create_reminders_for_times(
        db,
        profile,
        kind="medication",
        title="Medication reminder",
        source_type="medication",
        source_id=row.id,
        times=times,
    )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="medication.create",
        resource_type="medication",
        resource_id=row.id,
        outcome="allowed",
        metadata={"has_schedule": bool(times)},
    )
    db.commit()
    return _serialize_medication(row)


def deactivate_medication(db: Session, ctx: UserContext, medication_id: str) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverMedication)
        .filter(
            LifesaverMedication.id == medication_id,
            LifesaverMedication.organization_id == profile.organization_id,
            LifesaverMedication.profile_id == profile.id,
        )
        .first()
    )
    if row is None:
        write_audit(
            db,
            organization_id=profile.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=profile.id,
            action="medication.deactivate",
            resource_type="medication",
            resource_id=medication_id,
            outcome="denied",
            metadata={"reason": "not_owner"},
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Medication was not found.")
    row.active = False
    (
        db.query(LifesaverReminder)
        .filter(
            LifesaverReminder.source_type == "medication",
            LifesaverReminder.source_id == row.id,
            LifesaverReminder.status.in_(("scheduled", "due")),
        )
        .update({"status": "cancelled"}, synchronize_session=False)
    )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="medication.deactivate",
        resource_type="medication",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_medication(row)


def list_reminders(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_medications", action="reminder.list", resource_type="reminder"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "reminders", action="reminder.list", resource_type="reminder")
    _mark_due_reminders(db, subject)
    rows = (
        db.query(LifesaverReminder)
        .filter(
            LifesaverReminder.organization_id == subject.organization_id,
            LifesaverReminder.profile_id == subject.id,
        )
        .order_by(LifesaverReminder.due_at.asc())
        .limit(50)
        .all()
    )
    db.commit()
    return [_serialize_reminder(row) for row in rows]


def acknowledge_reminder(db: Session, ctx: UserContext, reminder_id: str) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverReminder)
        .filter(
            LifesaverReminder.id == reminder_id,
            LifesaverReminder.organization_id == profile.organization_id,
            LifesaverReminder.profile_id == profile.id,
        )
        .first()
    )
    if row is None:
        write_audit(
            db,
            organization_id=profile.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=profile.id,
            action="reminder.acknowledge",
            resource_type="reminder",
            resource_id=reminder_id,
            outcome="denied",
            metadata={"reason": "not_owner"},
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Reminder was not found.")
    row.status = "acknowledged"
    row.acknowledged_at = now()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="reminder.acknowledge",
        resource_type="reminder",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_reminder(row)


def list_appointments(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_appointments", action="appointment.list", resource_type="appointment"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "reminders", action="appointment.list", resource_type="appointment")
    rows = (
        db.query(LifesaverAppointment)
        .filter(
            LifesaverAppointment.organization_id == subject.organization_id,
            LifesaverAppointment.profile_id == subject.id,
        )
        .order_by(LifesaverAppointment.starts_at.desc())
        .limit(50)
        .all()
    )
    db.commit()
    return [_serialize_appointment(row) for row in rows]


def create_appointment(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "reminders", action="appointment.create", resource_type="appointment")
    row = LifesaverAppointment(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        title=payload.title.strip()[:160],
        location=(payload.location or "").strip()[:256] or None,
        starts_at=payload.starts_at,
        notes=(payload.notes or "").strip()[:512] or None,
        status="scheduled",
    )
    db.add(row)
    db.flush()
    reminder_at = payload.starts_at - timedelta(hours=1)
    if reminder_at > now():
        db.add(
            LifesaverReminder(
                organization_id=profile.organization_id,
                profile_id=profile.id,
                kind="appointment",
                title="Appointment reminder",
                due_at=reminder_at,
                status="scheduled",
                source_type="appointment",
                source_id=row.id,
            )
        )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="appointment.create",
        resource_type="appointment",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_appointment(row)


def list_wellness(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_wellness", action="wellness.list", resource_type="wellness"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "wellness_checkins", action="wellness.list", resource_type="wellness")
    rows = (
        db.query(LifesaverWellnessCheckin)
        .filter(
            LifesaverWellnessCheckin.organization_id == subject.organization_id,
            LifesaverWellnessCheckin.profile_id == subject.id,
        )
        .order_by(LifesaverWellnessCheckin.created_at.desc())
        .limit(30)
        .all()
    )
    db.commit()
    return [_serialize_wellness(row) for row in rows]


def create_wellness(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "wellness_checkins", action="wellness.create", resource_type="wellness")
    row = LifesaverWellnessCheckin(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        mood=payload.mood.strip()[:32],
        energy=payload.energy.strip()[:32],
        notes=(payload.notes or "").strip()[:512] or None,
    )
    db.add(row)
    db.flush()
    if payload.notify_caregivers and has_consent(db, profile.id, "caregiver_sharing"):
        _notify_circle(
            db,
            member=profile,
            alert_type="wellness_shared",
            severity="info",
            title="Wellness check-in shared",
            message="A wellness check-in was shared with Care Circle.",
        )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="wellness.create",
        resource_type="wellness",
        resource_id=row.id,
        outcome="allowed",
        metadata={"notify_caregivers": bool(payload.notify_caregivers)},
    )
    db.commit()
    return _serialize_wellness(row)


def list_journal(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_journal", action="journal.list", resource_type="journal"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "journal", action="journal.list", resource_type="journal")
    rows = (
        db.query(LifesaverJournalEntry)
        .filter(
            LifesaverJournalEntry.organization_id == subject.organization_id,
            LifesaverJournalEntry.profile_id == subject.id,
        )
        .order_by(LifesaverJournalEntry.created_at.desc())
        .limit(30)
        .all()
    )
    db.commit()
    return [_serialize_journal(row) for row in rows]


def create_journal(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "journal", action="journal.create", resource_type="journal")
    row = LifesaverJournalEntry(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        body=payload.body.strip()[:4000],
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="journal.create",
        resource_type="journal",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_journal(row)


def list_readings(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_readings", action="reading.list", resource_type="reading"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "health_readings", action="reading.list", resource_type="reading")
    rows = (
        db.query(LifesaverHealthReading)
        .filter(
            LifesaverHealthReading.organization_id == subject.organization_id,
            LifesaverHealthReading.profile_id == subject.id,
        )
        .order_by(LifesaverHealthReading.recorded_at.desc())
        .limit(50)
        .all()
    )
    db.commit()
    return [_serialize_reading(row) for row in rows]


def create_reading(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "health_readings", action="reading.create", resource_type="reading")
    if payload.reading_type not in READING_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported reading type.")
    if payload.source == SOURCE_EXTERNAL_RESERVED:
        raise HTTPException(status_code=409, detail="EXTERNAL_DEVICE_RESERVED cannot ingest real data in Phase 2.")
    if payload.source == SOURCE_SIMULATED_DEVICE:
        raise HTTPException(status_code=422, detail="Use the simulated-device ingest surface.")
    if payload.source not in {SOURCE_USER_ENTERED, SOURCE_SIMULATED} or payload.source not in READING_SOURCES:
        raise HTTPException(status_code=422, detail="Readings must be user_entered or simulated.")
    if payload.reading_type == "blood_pressure" and payload.value_secondary is None:
        raise HTTPException(status_code=422, detail="Blood pressure requires a diastolic value.")
    row = LifesaverHealthReading(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        reading_type=payload.reading_type,
        value_primary=float(payload.value_primary),
        value_secondary=None if payload.value_secondary is None else float(payload.value_secondary),
        unit=READING_UNITS[payload.reading_type],
        source=payload.source,
        note=(payload.note or "").strip()[:256] or None,
        device_alias=None,
        ingestion_status="accepted",
        recorded_at=now(),
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="reading.create",
        resource_type="reading",
        resource_id=row.id,
        outcome="allowed",
        metadata={"reading_type": payload.reading_type, "source": payload.source},
    )
    db.commit()
    return _serialize_reading(row)


def get_transport(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_transport", action="transport.read", resource_type="transport"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "transport_status", action="transport.read", resource_type="transport")
    connection = get_or_create_connection(db, organization_id=subject.organization_id, profile_id=subject.id)
    db.commit()
    return serialize_connection(connection)


def set_transport(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "transport_status", action="transport.update", resource_type="transport")
    if not payload.confirm:
        raise HTTPException(status_code=422, detail="Confirm this transportation status change.")
    connection = get_or_create_connection(db, organization_id=profile.organization_id, profile_id=profile.id)
    try:
        update_connection(db, connection, payload.status)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unsupported transportation status.") from None
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="transport.update",
        resource_type="transport",
        resource_id=connection.id,
        outcome="allowed",
        metadata={"status": payload.status},
    )
    db.commit()
    return serialize_connection(connection)


def start_sos(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "sos_demonstration", action="sos.start", resource_type="sos")
    row = LifesaverSosDemonstration(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        status="draft",
        note=(payload.note or "").strip()[:256] or None,
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="sos.start",
        resource_type="sos",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_sos(row)


def confirm_sos(db: Session, ctx: UserContext, sos_id: str, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    if not payload.confirm or not payload.understood_not_emergency:
        raise HTTPException(
            status_code=422,
            detail="Human confirmation is required, including that this is not an emergency service.",
        )
    row = (
        db.query(LifesaverSosDemonstration)
        .filter(
            LifesaverSosDemonstration.id == sos_id,
            LifesaverSosDemonstration.organization_id == profile.organization_id,
            LifesaverSosDemonstration.profile_id == profile.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="SOS demonstration was not found.")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="SOS demonstration is no longer awaiting confirmation.")
    row.status = "confirmed"
    row.confirmed_by_user_id = ctx.user_id
    row.confirmed_at = now()
    _notify_circle(
        db,
        member=profile,
        alert_type="sos_demonstration",
        severity="urgent_demo",
        title="SOS demonstration confirmed",
        message="A demonstration SOS was confirmed. This did not contact emergency services.",
    )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="sos.confirm",
        resource_type="sos",
        resource_id=row.id,
        outcome="allowed",
        metadata={"emergency_services_contacted": False},
    )
    db.commit()
    return _serialize_sos(row)


def acknowledge_sos(db: Session, ctx: UserContext, sos_id: str) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverSosDemonstration)
        .filter(
            LifesaverSosDemonstration.id == sos_id,
            LifesaverSosDemonstration.organization_id == actor.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="SOS demonstration was not found.")
    if row.profile_id != actor.id:
        require_subject_access(
            db, ctx, actor, row.profile_id, "acknowledge_alerts", action="sos.acknowledge", resource_type="sos"
        )
    row.status = "acknowledged"
    row.acknowledged_by_user_id = ctx.user_id
    row.acknowledged_at = now()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="sos.acknowledge",
        resource_type="sos",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_sos(row)


def list_sos(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    rows = (
        db.query(LifesaverSosDemonstration)
        .filter(
            LifesaverSosDemonstration.organization_id == profile.organization_id,
            LifesaverSosDemonstration.profile_id == profile.id,
        )
        .order_by(LifesaverSosDemonstration.created_at.desc())
        .limit(20)
        .all()
    )
    db.commit()
    return [_serialize_sos(row) for row in rows]


def list_circle(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    rows = (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.organization_id == profile.organization_id,
            LifesaverCareCircleMember.member_profile_id == profile.id,
        )
        .all()
    )
    db.commit()
    return [_serialize_circle(db, row) for row in rows]


def list_caring_for(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    rows = (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.organization_id == profile.organization_id,
            LifesaverCareCircleMember.caregiver_profile_id == profile.id,
            LifesaverCareCircleMember.status == "active",
        )
        .all()
    )
    db.commit()
    return [_serialize_circle(db, row) for row in rows]


def invite_caregiver(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    member = get_or_create_profile(db, ctx)
    require_consent(db, ctx, member, "caregiver_sharing", action="circle.invite", resource_type="care_circle")
    email = payload.caregiver_email.strip().lower()
    user = (
        db.query(PlatformUser)
        .filter(
            PlatformUser.email == email,
            PlatformUser.is_active.is_(True),
        )
        .first()
    )
    caregiver_ctx = None
    if user is not None and user.id != ctx.user_id:
        caregiver_ctx = UserContext(
            user_id=user.id,
            email=user.email,
            role=user.role,
            organization_id=user.organization_id,
            organization_name=user.organization_name,
        )
    if caregiver_ctx is None or tenant_key(caregiver_ctx) != member.organization_id:
        write_audit(
            db,
            organization_id=member.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=member.id,
            action="circle.invite",
            resource_type="care_circle",
            resource_id=None,
            outcome="denied",
            metadata={"reason": "caregiver_not_in_organization"},
        )
        db.commit()
        raise HTTPException(status_code=404, detail="No active account in your organization matches that invite.")
    caregiver = get_or_create_profile(db, caregiver_ctx)
    existing = (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.member_profile_id == member.id,
            LifesaverCareCircleMember.caregiver_profile_id == caregiver.id,
        )
        .first()
    )
    permissions = [item for item in payload.permissions if item in CAREGIVER_PERMISSIONS]
    if not permissions:
        permissions = list(DEFAULT_CAREGIVER_PERMISSIONS)
    if existing:
        existing.status = "active"
        existing.revoked_at = None
        existing.permissions_json = json_dumps(permissions)
        row = existing
    else:
        row = LifesaverCareCircleMember(
            organization_id=member.organization_id,
            member_profile_id=member.id,
            caregiver_profile_id=caregiver.id,
            caregiver_user_id=user.id,
            status="active",
            permissions_json=json_dumps(permissions),
            invited_by_user_id=ctx.user_id,
        )
        db.add(row)
        db.flush()
    caregiver.profile_role = "caregiver"
    db.add(
        LifesaverAlert(
            organization_id=member.organization_id,
            member_profile_id=member.id,
            caregiver_profile_id=caregiver.id,
            alert_type="caregiver_invite",
            severity="info",
            title="Care Circle access granted",
            message="You were added to a Care Circle with the permissions the member selected.",
            status="open",
            requires_ack=True,
        )
    )
    write_audit(
        db,
        organization_id=member.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=member.id,
        action="circle.invite",
        resource_type="care_circle",
        resource_id=row.id,
        outcome="allowed",
        metadata={"permissions": permissions},
    )
    db.commit()
    return _serialize_circle(db, row)


def update_circle_permissions(db: Session, ctx: UserContext, link_id: str, permissions: list[str]) -> dict[str, Any]:
    member = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.id == link_id,
            LifesaverCareCircleMember.organization_id == member.organization_id,
            LifesaverCareCircleMember.member_profile_id == member.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Care Circle relationship was not found.")
    clean = [item for item in permissions if item in CAREGIVER_PERMISSIONS]
    row.permissions_json = json_dumps(clean)
    write_audit(
        db,
        organization_id=member.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=member.id,
        action="circle.permissions",
        resource_type="care_circle",
        resource_id=row.id,
        outcome="allowed",
        metadata={"permissions": clean},
    )
    db.commit()
    return _serialize_circle(db, row)


def revoke_circle(db: Session, ctx: UserContext, link_id: str) -> dict[str, Any]:
    member = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.id == link_id,
            LifesaverCareCircleMember.organization_id == member.organization_id,
            LifesaverCareCircleMember.member_profile_id == member.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Care Circle relationship was not found.")
    row.status = "revoked"
    row.revoked_at = now()
    write_audit(
        db,
        organization_id=member.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=member.id,
        action="circle.revoke",
        resource_type="care_circle",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_circle(db, row)


def list_alerts(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    rows = (
        db.query(LifesaverAlert)
        .filter(
            LifesaverAlert.organization_id == profile.organization_id,
            ((LifesaverAlert.caregiver_profile_id == profile.id) | (LifesaverAlert.member_profile_id == profile.id)),
        )
        .order_by(LifesaverAlert.created_at.desc())
        .limit(40)
        .all()
    )
    db.commit()
    return [_serialize_alert(row) for row in rows]


def acknowledge_alert(db: Session, ctx: UserContext, alert_id: str) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverAlert)
        .filter(
            LifesaverAlert.id == alert_id,
            LifesaverAlert.organization_id == actor.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Alert was not found.")
    allowed = row.member_profile_id == actor.id or row.caregiver_profile_id == actor.id
    if row.caregiver_profile_id == actor.id:
        link = active_circle_link(
            db,
            organization_id=actor.organization_id,
            member_profile_id=row.member_profile_id,
            caregiver_profile_id=actor.id,
        )
        allowed = bool(link and "acknowledge_alerts" in parse_permissions(link.permissions_json))
    if not allowed:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action="alert.acknowledge",
            resource_type="alert",
            resource_id=alert_id,
            outcome="denied",
            metadata={"reason": "not_authorized"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="You cannot acknowledge this alert.")
    row.status = "acknowledged"
    row.acknowledged_by_user_id = ctx.user_id
    row.acknowledged_at = now()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="alert.acknowledge",
        resource_type="alert",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_alert(row)


def list_tasks(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "manage_tasks", action="task.list", resource_type="task"
    )
    rows = (
        db.query(LifesaverCareTask)
        .filter(
            LifesaverCareTask.organization_id == subject.organization_id,
            LifesaverCareTask.member_profile_id == subject.id,
        )
        .order_by(LifesaverCareTask.created_at.desc())
        .limit(40)
        .all()
    )
    db.commit()
    return [_serialize_task(row) for row in rows]


def create_task(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, payload.member_profile_id, "manage_tasks", action="task.create", resource_type="task"
    )
    if subject.id == actor.id and payload.member_profile_id:
        pass
    row = LifesaverCareTask(
        organization_id=actor.organization_id,
        member_profile_id=subject.id,
        assigned_caregiver_id=payload.assigned_caregiver_id,
        title=payload.title.strip()[:160],
        due_at=payload.due_at,
        status="open",
        created_by_user_id=ctx.user_id,
    )
    db.add(row)
    db.flush()
    if payload.assigned_caregiver_id:
        db.add(
            LifesaverAlert(
                organization_id=actor.organization_id,
                member_profile_id=subject.id,
                caregiver_profile_id=payload.assigned_caregiver_id,
                alert_type="task_assigned",
                severity="info",
                title="Care task assigned",
                message="A shared care task was assigned.",
                status="open",
                requires_ack=True,
            )
        )
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="task.create",
        resource_type="task",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_task(row)


def complete_task(db: Session, ctx: UserContext, task_id: str) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverCareTask)
        .filter(
            LifesaverCareTask.id == task_id,
            LifesaverCareTask.organization_id == actor.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Care task was not found.")
    require_subject_access(
        db, ctx, actor, row.member_profile_id, "manage_tasks", action="task.complete", resource_type="task"
    )
    row.status = "completed"
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="task.complete",
        resource_type="task",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_task(row)


def create_handoff(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, payload.member_profile_id, "handoff", action="handoff.create", resource_type="handoff"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "caregiver_sharing", action="handoff.create", resource_type="handoff")
    if payload.from_caregiver_id == payload.to_caregiver_id:
        raise HTTPException(status_code=422, detail="Handoff must target a different caregiver.")
    for caregiver_id in (payload.from_caregiver_id, payload.to_caregiver_id):
        link = active_circle_link(
            db,
            organization_id=actor.organization_id,
            member_profile_id=subject.id,
            caregiver_profile_id=caregiver_id,
        )
        if link is None:
            raise HTTPException(status_code=403, detail="Both caregivers must already be in the Care Circle.")
    row = LifesaverHandoff(
        organization_id=actor.organization_id,
        member_profile_id=subject.id,
        from_caregiver_id=payload.from_caregiver_id,
        to_caregiver_id=payload.to_caregiver_id,
        status="pending",
        note=(payload.note or "").strip()[:256] or None,
        created_by_user_id=ctx.user_id,
    )
    db.add(row)
    db.flush()
    db.add(
        LifesaverAlert(
            organization_id=actor.organization_id,
            member_profile_id=subject.id,
            caregiver_profile_id=payload.to_caregiver_id,
            alert_type="handoff",
            severity="attention",
            title="Care handoff requested",
            message="A Care Circle handoff is waiting for acknowledgment.",
            status="open",
            requires_ack=True,
        )
    )
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="handoff.create",
        resource_type="handoff",
        resource_id=row.id,
        outcome="allowed",
    )
    db.commit()
    return _serialize_handoff(row)


def resolve_handoff(db: Session, ctx: UserContext, handoff_id: str, accept: bool) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    row = (
        db.query(LifesaverHandoff)
        .filter(
            LifesaverHandoff.id == handoff_id,
            LifesaverHandoff.organization_id == actor.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Handoff was not found.")
    if row.to_caregiver_id != actor.id:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action="handoff.resolve",
            resource_type="handoff",
            resource_id=handoff_id,
            outcome="denied",
            metadata={"reason": "not_target_caregiver"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="Only the receiving caregiver can resolve this handoff.")
    row.status = "accepted" if accept else "declined"
    row.resolved_at = now()
    write_audit(
        db,
        organization_id=actor.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=actor.id,
        action="handoff.resolve",
        resource_type="handoff",
        resource_id=row.id,
        outcome="allowed",
        metadata={"accepted": accept},
    )
    db.commit()
    return _serialize_handoff(row)


def list_handoffs(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    rows = (
        db.query(LifesaverHandoff)
        .filter(
            LifesaverHandoff.organization_id == profile.organization_id,
            (
                (LifesaverHandoff.member_profile_id == profile.id)
                | (LifesaverHandoff.from_caregiver_id == profile.id)
                | (LifesaverHandoff.to_caregiver_id == profile.id)
            ),
        )
        .order_by(LifesaverHandoff.created_at.desc())
        .limit(30)
        .all()
    )
    db.commit()
    return [_serialize_handoff(row) for row in rows]


def converse(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "ai_conversation", action="ai.converse", resource_type="conversation")
    conversation = None
    if payload.conversation_id:
        conversation = (
            db.query(LifesaverConversation)
            .filter(
                LifesaverConversation.id == payload.conversation_id,
                LifesaverConversation.organization_id == profile.organization_id,
                LifesaverConversation.profile_id == profile.id,
            )
            .first()
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation was not found.")
    else:
        conversation = LifesaverConversation(
            organization_id=profile.organization_id,
            profile_id=profile.id,
        )
        db.add(conversation)
        db.flush()
    reminder_count = (
        db.query(LifesaverReminder)
        .filter(
            LifesaverReminder.profile_id == profile.id,
            LifesaverReminder.status.in_(("scheduled", "due")),
        )
        .count()
    )
    consent_count = (
        db.query(LifesaverConsent)
        .filter(LifesaverConsent.profile_id == profile.id, LifesaverConsent.granted.is_(True))
        .count()
    )
    appointment_count = (
        db.query(LifesaverAppointment)
        .filter(LifesaverAppointment.profile_id == profile.id, LifesaverAppointment.status == "scheduled")
        .count()
    )
    task_count = (
        db.query(LifesaverCareTask)
        .filter(LifesaverCareTask.member_profile_id == profile.id, LifesaverCareTask.status == "open")
        .count()
    )
    pending_handoffs = (
        db.query(LifesaverHandoff)
        .filter(LifesaverHandoff.member_profile_id == profile.id, LifesaverHandoff.status == "pending")
        .count()
    )
    open_alerts = (
        db.query(LifesaverAlert)
        .filter(LifesaverAlert.member_profile_id == profile.id, LifesaverAlert.status == "open")
        .count()
    )
    transport_open = (
        db.query(LifesaverTransportRequest)
        .filter(
            LifesaverTransportRequest.profile_id == profile.id,
            LifesaverTransportRequest.status.in_(("requested", "needs_review", "ready_for_handoff")),
        )
        .count()
    )
    counts = peek_coordination_counts(db, ctx, profile.id)
    result = nova_adapter.ask(
        payload.message,
        context={
            "reminder_count": reminder_count,
            "consent_granted": consent_count,
            "appointment_count": appointment_count,
            "task_count": task_count,
            "pending_handoffs": pending_handoffs,
            "open_alerts": open_alerts,
            "transport_open": transport_open,
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "needs_review": counts["needs_review"],
        },
    )
    db.add(
        LifesaverConversationMessage(
            organization_id=profile.organization_id,
            conversation_id=conversation.id,
            profile_id=profile.id,
            role="user",
            content=payload.message.strip()[:2000],
        )
    )
    assistant = LifesaverConversationMessage(
        organization_id=profile.organization_id,
        conversation_id=conversation.id,
        profile_id=profile.id,
        role="assistant",
        content=result["reply"],
    )
    db.add(assistant)
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="ai.converse",
        resource_type="conversation",
        resource_id=conversation.id,
        outcome="allowed",
        metadata={"mode": result["mode"]},
    )
    db.commit()
    return {
        "conversation_id": conversation.id,
        "reply": result["reply"],
        "mode": result["mode"],
        "disclaimer": result["disclaimer"],
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def coordination_view(
    db: Session,
    ctx: UserContext,
    member_profile_id: str | None = None,
    selected_filter: str = "all",
    *,
    record_audit: bool = True,
) -> dict[str, Any]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db,
        ctx,
        actor,
        member_profile_id,
        "view_today",
        action="care_coordination.view",
        resource_type="coordination",
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "care_cloud_use", action="care_coordination.view", resource_type="coordination")
    _mark_due_reminders(db, subject)
    owner = subject.id == actor.id
    can_view_readings = owner or _caregiver_has(db, actor, subject, "view_readings")
    can_view_appointments = owner or _caregiver_has(db, actor, subject, "view_appointments")
    can_view_meds = owner or _caregiver_has(db, actor, subject, "view_medications")
    can_view_wellness = owner or _caregiver_has(db, actor, subject, "view_wellness")
    can_view_journal = owner or _caregiver_has(db, actor, subject, "view_journal")
    can_view_transport = owner or _caregiver_has(db, actor, subject, "view_transport")
    can_manage_tasks = owner or _caregiver_has(db, actor, subject, "manage_tasks")
    can_handoff = owner or _caregiver_has(db, actor, subject, "handoff")
    can_alerts = owner or _caregiver_has(db, actor, subject, "receive_alerts")

    appointments = (
        db.query(LifesaverAppointment)
        .filter(
            LifesaverAppointment.organization_id == subject.organization_id,
            LifesaverAppointment.profile_id == subject.id,
        )
        .order_by(LifesaverAppointment.starts_at.asc())
        .limit(20)
        .all()
        if can_view_appointments
        else []
    )
    reminders = (
        db.query(LifesaverReminder)
        .filter(
            LifesaverReminder.organization_id == subject.organization_id,
            LifesaverReminder.profile_id == subject.id,
        )
        .order_by(LifesaverReminder.due_at.asc())
        .limit(30)
        .all()
        if can_view_meds
        else []
    )
    tasks = (
        db.query(LifesaverCareTask)
        .filter(
            LifesaverCareTask.organization_id == subject.organization_id,
            LifesaverCareTask.member_profile_id == subject.id,
        )
        .order_by(LifesaverCareTask.created_at.desc())
        .limit(20)
        .all()
        if can_manage_tasks or owner
        else []
    )
    handoffs = (
        db.query(LifesaverHandoff)
        .filter(
            LifesaverHandoff.organization_id == subject.organization_id,
            LifesaverHandoff.member_profile_id == subject.id,
        )
        .order_by(LifesaverHandoff.created_at.desc())
        .limit(20)
        .all()
        if can_handoff or owner
        else []
    )
    alerts = (
        db.query(LifesaverAlert)
        .filter(
            LifesaverAlert.organization_id == subject.organization_id,
            LifesaverAlert.member_profile_id == subject.id,
        )
        .order_by(LifesaverAlert.created_at.desc())
        .limit(20)
        .all()
        if can_alerts or owner
        else []
    )
    transport_requests = (
        transport_bridge.list_requests(db, organization_id=subject.organization_id, profile_id=subject.id)
        if can_view_transport
        else []
    )
    circle = (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.organization_id == subject.organization_id,
            LifesaverCareCircleMember.member_profile_id == subject.id,
        )
        .all()
    )
    wellness = (
        db.query(LifesaverWellnessCheckin)
        .filter(
            LifesaverWellnessCheckin.organization_id == subject.organization_id,
            LifesaverWellnessCheckin.profile_id == subject.id,
        )
        .order_by(LifesaverWellnessCheckin.created_at.desc())
        .first()
        if can_view_wellness
        else None
    )
    journal_q = (
        db.query(LifesaverJournalEntry)
        .filter(
            LifesaverJournalEntry.organization_id == subject.organization_id,
            LifesaverJournalEntry.profile_id == subject.id,
        )
        .order_by(LifesaverJournalEntry.created_at.desc())
        if can_view_journal
        else None
    )
    journal_count = journal_q.count() if journal_q is not None else 0
    latest_journal = journal_q.first() if journal_q is not None else None
    readings = (
        db.query(LifesaverHealthReading)
        .filter(
            LifesaverHealthReading.organization_id == subject.organization_id,
            LifesaverHealthReading.profile_id == subject.id,
        )
        .order_by(LifesaverHealthReading.recorded_at.desc())
        .limit(20)
        .all()
        if can_view_readings
        else []
    )
    reading_summaries = (
        [{"reading_type": row.reading_type, "source": row.source} for row in readings] if can_view_readings else []
    )
    sos_rows = (
        db.query(LifesaverSosDemonstration)
        .filter(
            LifesaverSosDemonstration.organization_id == subject.organization_id,
            LifesaverSosDemonstration.profile_id == subject.id,
        )
        .order_by(LifesaverSosDemonstration.created_at.desc())
        .limit(5)
        .all()
    )
    consents = (
        db.query(LifesaverConsent)
        .filter(LifesaverConsent.profile_id == subject.id)
        .order_by(LifesaverConsent.consent_type.asc())
        .all()
        if owner
        else []
    )
    notices = (
        db.query(LifesaverNotificationOutbox)
        .filter(
            LifesaverNotificationOutbox.organization_id == subject.organization_id,
            LifesaverNotificationOutbox.profile_id == subject.id,
        )
        .all()
        if owner
        else []
    )
    notification_status: dict[str, int] = {}
    for notice in notices:
        notification_status[notice.status] = notification_status.get(notice.status, 0) + 1
    simulated_count = sum(1 for row in readings if row.source == SOURCE_SIMULATED_DEVICE)
    user_count = sum(1 for row in readings if row.source == SOURCE_USER_ENTERED)
    device_status = {
        "status": "simulated_only" if simulated_count else "none",
        "label": (
            f"{simulated_count} simulated-device reading(s), {user_count} user-entered. "
            "No real medical device is connected."
        ),
        "external_device_connected": False,
    }
    from app.modules.lifesaver.hardware.service import open_safety_events

    safety_events = open_safety_events(
        db,
        organization_id=subject.organization_id,
        profile_id=subject.id,
    )
    cards = build_coordination_cards(
        appointments=appointments,
        reminders=reminders,
        tasks=tasks,
        handoffs=handoffs,
        alerts=alerts,
        transport_requests=transport_requests,
        circle_members=circle,
        journal_count=journal_count,
        latest_journal_at=latest_journal.created_at if latest_journal else None,
        wellness=wellness,
        reading_summaries=reading_summaries,
        sos_rows=sos_rows,
        consents=[serialize_consent(row) for row in consents],
        notification_status=notification_status,
        device_status=device_status,
        can_view_readings=can_view_readings,
        safety_events=safety_events,
    )
    selected = (selected_filter or "all").lower()
    if selected not in COORDINATION_FILTERS:
        selected = "all"
    visible = [card for card in cards if matches_filter(card, selected)]
    if record_audit:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action="care_coordination.view",
            resource_type="coordination",
            resource_id=subject.id,
            outcome="allowed",
            metadata={"filter": selected, "card_count": len(visible), "viewer_is_owner": owner},
        )
        db.commit()
    payload = {
        "disclaimer": coordination_disclaimer(),
        "subject_profile_id": subject.id,
        "viewer_profile_id": actor.id,
        "viewer_is_owner": owner,
        "filter": selected,
        "filters": list(COORDINATION_FILTERS),
        "counts": summarize_counts(visible),
        "cards": visible,
        "values_included": False,
        "journal_body_included": False,
    }
    journal_body = latest_journal.body if latest_journal is not None else ""
    if journal_body and len(journal_body) >= 8 and journal_body in json.dumps(payload):
        raise HTTPException(status_code=500, detail="Coordination summary refused to include journal body.")
    return payload


def peek_coordination_counts(
    db: Session,
    ctx: UserContext,
    member_profile_id: str | None = None,
) -> dict[str, int]:
    """Return the same HIGH/MEDIUM/LOW/review counts shown on Care Coordination."""
    empty = {"high": 0, "medium": 0, "low": 0, "needs_review": 0}
    try:
        data = coordination_view(db, ctx, member_profile_id, "all", record_audit=False)
    except HTTPException:
        return empty
    counts = data.get("counts") or {}
    return {
        "high": int(counts.get("high") or 0),
        "medium": int(counts.get("medium") or 0),
        "low": int(counts.get("low") or 0),
        "needs_review": int(counts.get("needs_review") or 0),
    }


def _caregiver_has(db: Session, actor: LifesaverProfile, subject: LifesaverProfile, permission: str) -> bool:
    link = active_circle_link(
        db,
        organization_id=actor.organization_id,
        member_profile_id=subject.id,
        caregiver_profile_id=actor.id,
    )
    return bool(link and permission in parse_permissions(link.permissions_json))


def _may_share_reading_value(db: Session, member: LifesaverProfile, caregiver_profile_id: str | None) -> bool:
    if not caregiver_profile_id:
        return False
    if not has_consent(db, member.id, "health_readings"):
        return False
    if not has_consent(db, member.id, "caregiver_sharing"):
        return False
    link = active_circle_link(
        db,
        organization_id=member.organization_id,
        member_profile_id=member.id,
        caregiver_profile_id=caregiver_profile_id,
    )
    return bool(link and "view_readings" in parse_permissions(link.permissions_json))


def _redact_notification_copy(
    *,
    title: str,
    reason: str | None,
    journal_body: str | None,
    reading_value: str | None,
    allow_reading_value: bool,
) -> tuple[str, str | None]:
    clean_title = (title or "").replace(journal_body or "", "").strip()[:160] or "Care coordination update"
    clean_reason = (reason or "").replace(journal_body or "", "").strip()
    if reading_value and not allow_reading_value:
        clean_title = clean_title.replace(str(reading_value), "[redacted]")
        clean_reason = clean_reason.replace(str(reading_value), "[redacted]")
    if journal_body:
        clean_title = clean_title.replace(journal_body, "[redacted]")
        clean_reason = clean_reason.replace(journal_body, "[redacted]")
    return clean_title[:160], (clean_reason[:256] or None)


def orchestrate(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "ai_conversation", action="nova_adapter.ask", resource_type="conversation")
    reminder_count = (
        db.query(LifesaverReminder)
        .filter(LifesaverReminder.profile_id == profile.id, LifesaverReminder.status.in_(("scheduled", "due")))
        .count()
    )
    appointment_count = (
        db.query(LifesaverAppointment)
        .filter(LifesaverAppointment.profile_id == profile.id)
        .count()
    )
    task_count = (
        db.query(LifesaverCareTask)
        .filter(LifesaverCareTask.member_profile_id == profile.id, LifesaverCareTask.status == "open")
        .count()
    )
    pending_handoffs = (
        db.query(LifesaverHandoff)
        .filter(LifesaverHandoff.member_profile_id == profile.id, LifesaverHandoff.status == "pending")
        .count()
    )
    open_alerts = (
        db.query(LifesaverAlert)
        .filter(LifesaverAlert.member_profile_id == profile.id, LifesaverAlert.status == "open")
        .count()
    )
    transport_open = (
        db.query(LifesaverTransportRequest)
        .filter(
            LifesaverTransportRequest.profile_id == profile.id,
            LifesaverTransportRequest.status.in_(("requested", "needs_review", "ready_for_handoff")),
        )
        .count()
    )
    counts = peek_coordination_counts(db, ctx, profile.id)
    result = nova_adapter.ask(
        payload.message,
        context={
            "reminder_count": reminder_count,
            "appointment_count": appointment_count,
            "task_count": task_count,
            "pending_handoffs": pending_handoffs,
            "open_alerts": open_alerts,
            "transport_open": transport_open,
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "needs_review": counts["needs_review"],
            "consent_granted": db.query(LifesaverConsent)
            .filter(LifesaverConsent.profile_id == profile.id, LifesaverConsent.granted.is_(True))
            .count(),
        },
    )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="nova_adapter.ask",
        resource_type="conversation",
        resource_id=profile.id,
        outcome="allowed",
        metadata={"mode": result.get("mode"), "uses_nova_engine": False, "writes_nova_tables": False},
    )
    db.commit()
    return {
        "reply": result["reply"],
        "mode": result["mode"],
        "disclaimer": result.get("disclaimer") or AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def list_transport_requests(db: Session, ctx: UserContext, member_profile_id: str | None = None) -> list[dict[str, Any]]:
    actor = get_or_create_profile(db, ctx)
    subject = require_subject_access(
        db, ctx, actor, member_profile_id, "view_transport", action="transport.request.list", resource_type="transport"
    )
    if subject.id == actor.id:
        require_consent(db, ctx, subject, "transport_status", action="transport.request.list", resource_type="transport")
    rows = transport_bridge.list_requests(db, organization_id=subject.organization_id, profile_id=subject.id)
    db.commit()
    return [transport_bridge.serialize_request(row) for row in rows]


def create_transport_request(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "transport_status", action="transport.request.create", resource_type="transport")
    row = transport_bridge.create_request(
        db,
        organization_id=profile.organization_id,
        profile_id=profile.id,
        created_by_user_id=ctx.user_id,
        appointment_id=payload.appointment_id,
        pickup_at=payload.pickup_at,
        pickup_label=payload.pickup_label,
        destination_label=payload.destination_label,
        accessibility_needs=payload.accessibility_needs,
        mobility_note=payload.mobility_note,
        companion_needed=payload.companion_needed,
    )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="transport.request.create",
        resource_type="transport",
        resource_id=row.id,
        outcome="allowed",
        metadata={"status": row.status, "creates_health_isf_ride": False},
    )
    db.commit()
    return transport_bridge.serialize_request(row)


def confirm_transport_request(db: Session, ctx: UserContext, request_id: str, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "transport_status", action="transport.request.confirm", resource_type="transport")
    row = transport_bridge.get_owned(
        db, organization_id=profile.organization_id, profile_id=profile.id, request_id=request_id
    )
    transport_bridge.confirm_ready(db, row, user_id=ctx.user_id, confirm=bool(payload.confirm))
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="transport.request.confirm",
        resource_type="transport",
        resource_id=row.id,
        outcome="allowed",
        metadata={"status": row.status},
    )
    db.commit()
    return transport_bridge.serialize_request(row)


def simulated_transport_handoff(db: Session, ctx: UserContext, request_id: str) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "transport_status", action="transport.handoff.simulated", resource_type="transport")
    row = transport_bridge.get_owned(
        db, organization_id=profile.organization_id, profile_id=profile.id, request_id=request_id
    )
    transport_bridge.simulated_handoff(db, row)
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="transport.handoff.simulated",
        resource_type="transport",
        resource_id=row.id,
        outcome="allowed",
        metadata={"status": row.status, "creates_health_isf_ride": False, "simulated": True},
    )
    db.commit()
    return transport_bridge.serialize_request(row)


def cancel_transport_request(db: Session, ctx: UserContext, request_id: str) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "transport_status", action="transport.request.cancel", resource_type="transport")
    row = transport_bridge.get_owned(
        db, organization_id=profile.organization_id, profile_id=profile.id, request_id=request_id
    )
    transport_bridge.cancel_request(db, row)
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="transport.request.cancel",
        resource_type="transport",
        resource_id=row.id,
        outcome="allowed",
        metadata={"status": row.status},
    )
    db.commit()
    return transport_bridge.serialize_request(row)


def list_notifications(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "caregiver_notifications", action="notification.list", resource_type="notification")
    rows = notification_outbox.list_notices(
        db, organization_id=profile.organization_id, profile_ids=[profile.id]
    )
    db.commit()
    return [notification_outbox.serialize_notice(row) for row in rows]


def queue_notification(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "caregiver_notifications", action="notification.queue", resource_type="notification")
    if payload.recipient_profile_id:
        link = active_circle_link(
            db,
            organization_id=profile.organization_id,
            member_profile_id=profile.id,
            caregiver_profile_id=payload.recipient_profile_id,
        )
        if link is None:
            raise HTTPException(status_code=403, detail="Recipient must already be an active Care Circle member.")
    allow_reading = _may_share_reading_value(db, profile, payload.recipient_profile_id)
    title, reason = _redact_notification_copy(
        title=payload.title,
        reason=payload.reason,
        journal_body=payload.journal_body,
        reading_value=payload.reading_value,
        allow_reading_value=allow_reading,
    )
    row = notification_outbox.queue(
        db,
        organization_id=profile.organization_id,
        profile_id=profile.id,
        recipient_profile_id=payload.recipient_profile_id,
        recipient_role=payload.recipient_role,
        notification_type=payload.notification_type,
        channel=payload.channel,
        title=title,
        reason=reason,
        redacted=True,
    )
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="notification.queue",
        resource_type="notification",
        resource_id=row.id,
        outcome="allowed",
        metadata={"channel": row.channel, "notification_type": row.notification_type, "external_message_sent": False},
    )
    db.commit()
    return notification_outbox.serialize_notice(row)


def _owned_notice(db: Session, ctx: UserContext, notice_id: str) -> tuple[LifesaverProfile, LifesaverNotificationOutbox]:
    profile = get_or_create_profile(db, ctx)
    row = notification_outbox.get_notice(db, organization_id=profile.organization_id, notice_id=notice_id)
    if row.profile_id != profile.id and row.recipient_profile_id != profile.id:
        write_audit(
            db,
            organization_id=profile.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=profile.id,
            action="notification.view",
            resource_type="notification",
            resource_id=notice_id,
            outcome="denied",
            metadata={"reason": "not_owner_or_recipient"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="You cannot view this notification.")
    return profile, row


def simulate_notification(db: Session, ctx: UserContext, notice_id: str, *, succeed: bool) -> dict[str, Any]:
    profile, row = _owned_notice(db, ctx, notice_id)
    if row.profile_id != profile.id:
        raise HTTPException(status_code=403, detail="Only the member who queued this notice can simulate delivery.")
    require_consent(db, ctx, profile, "caregiver_notifications", action="notification.simulated_deliver", resource_type="notification")
    notification_outbox.simulate(db, row, succeed=succeed)
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="notification.simulated_deliver" if succeed else "notification.simulated_fail",
        resource_type="notification",
        resource_id=row.id,
        outcome="allowed",
        metadata={"status": row.status, "external_message_sent": False},
    )
    db.commit()
    return notification_outbox.serialize_notice(row)


def suppress_notification(db: Session, ctx: UserContext, notice_id: str) -> dict[str, Any]:
    profile, row = _owned_notice(db, ctx, notice_id)
    if row.profile_id != profile.id:
        raise HTTPException(status_code=403, detail="Only the member who queued this notice can suppress it.")
    require_consent(db, ctx, profile, "caregiver_notifications", action="notification.suppress", resource_type="notification")
    notification_outbox.suppress(db, row)
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="notification.suppress",
        resource_type="notification",
        resource_id=row.id,
        outcome="allowed",
        metadata={"status": row.status, "external_message_sent": False},
    )
    db.commit()
    return notification_outbox.serialize_notice(row)


def retry_notification(db: Session, ctx: UserContext, notice_id: str) -> dict[str, Any]:
    profile, row = _owned_notice(db, ctx, notice_id)
    if row.profile_id != profile.id:
        raise HTTPException(status_code=403, detail="Only the member who queued this notice can retry it.")
    require_consent(db, ctx, profile, "caregiver_notifications", action="notification.retry", resource_type="notification")
    notification_outbox.retry(db, row)
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="notification.queue",
        resource_type="notification",
        resource_id=row.id,
        outcome="allowed",
        metadata={"status": row.status, "retry": True, "external_message_sent": False},
    )
    db.commit()
    return notification_outbox.serialize_notice(row)


def create_simulated_device_reading(db: Session, ctx: UserContext, payload) -> dict[str, Any]:
    profile = get_or_create_profile(db, ctx)
    require_consent(db, ctx, profile, "health_readings", action="device.simulated_ingest", resource_type="reading")
    require_consent(db, ctx, profile, "simulated_device_ingest", action="device.simulated_ingest", resource_type="reading")
    if payload.source == SOURCE_EXTERNAL_RESERVED:
        device_ingestion.FutureDeviceProvider().ingest()
    ingest = device_ingestion.validate_ingest(
        reading_type=payload.reading_type,
        source=payload.source,
        recorded_at=payload.recorded_at,
        device_alias=payload.device_alias,
    )
    if ingest["reading_type"] == "blood_pressure" and payload.value_secondary is None:
        raise HTTPException(status_code=422, detail="Blood pressure requires a diastolic value.")
    row = LifesaverHealthReading(
        organization_id=profile.organization_id,
        profile_id=profile.id,
        reading_type=ingest["reading_type"],
        value_primary=float(payload.value_primary),
        value_secondary=None if payload.value_secondary is None else float(payload.value_secondary),
        unit=ingest["unit"],
        source=SOURCE_SIMULATED_DEVICE,
        note=DEVICE_SIM_LABEL,
        device_alias=ingest["device_alias"],
        ingestion_status=ingest["ingestion_status"],
        recorded_at=ingest["recorded_at"],
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action="device.simulated_ingest",
        resource_type="reading",
        resource_id=row.id,
        outcome="allowed",
        metadata={"reading_type": row.reading_type, "source": SOURCE_SIMULATED_DEVICE, "device_sourced": False},
    )
    db.commit()
    return _serialize_reading(row)


def list_audit(db: Session, ctx: UserContext) -> list[dict[str, Any]]:
    profile = get_or_create_profile(db, ctx)
    from app.modules.lifesaver.models import LifesaverAuditEvent

    rows = (
        db.query(LifesaverAuditEvent)
        .filter(
            LifesaverAuditEvent.organization_id == profile.organization_id,
            LifesaverAuditEvent.actor_user_id == ctx.user_id,
        )
        .order_by(LifesaverAuditEvent.created_at.desc())
        .limit(50)
        .all()
    )
    db.commit()
    return [
        {
            "id": row.id,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "outcome": row.outcome,
            "metadata": json_loads_or(row.metadata_json, {}),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _notify_circle(
    db: Session,
    *,
    member: LifesaverProfile,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
) -> None:
    links = (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.organization_id == member.organization_id,
            LifesaverCareCircleMember.member_profile_id == member.id,
            LifesaverCareCircleMember.status == "active",
        )
        .all()
    )
    for link in links:
        if "receive_alerts" not in parse_permissions(link.permissions_json):
            continue
        db.add(
            LifesaverAlert(
                organization_id=member.organization_id,
                member_profile_id=member.id,
                caregiver_profile_id=link.caregiver_profile_id,
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                status="open",
                requires_ack=True,
            )
        )


def _serialize_medication(row: LifesaverMedication) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "instructions": row.instructions,
        "schedule_times": json_loads_or(row.schedule_json, []),
        "active": row.active,
        "clinical_advice": False,
        "created_at": _iso(row.created_at),
    }


def _serialize_reminder(row: LifesaverReminder) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "due_at": _iso(row.due_at),
        "status": row.status,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "acknowledged_at": _iso(row.acknowledged_at),
    }


def _serialize_appointment(row: LifesaverAppointment) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "location": row.location,
        "starts_at": _iso(row.starts_at),
        "notes": row.notes,
        "status": row.status,
    }


def _serialize_wellness(row: LifesaverWellnessCheckin) -> dict[str, Any]:
    return {
        "id": row.id,
        "mood": row.mood,
        "energy": row.energy,
        "notes": row.notes,
        "created_at": _iso(row.created_at),
        "clinical_interpretation": False,
    }


def _serialize_journal(row: LifesaverJournalEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "body": row.body,
        "created_at": _iso(row.created_at),
    }


def _serialize_reading(row: LifesaverHealthReading) -> dict[str, Any]:
    flags = device_ingestion.serialize_reading_flags(row.source)
    return {
        "id": row.id,
        "reading_type": row.reading_type,
        "value_primary": row.value_primary,
        "value_secondary": row.value_secondary,
        "unit": row.unit,
        "source": row.source,
        "device_sourced": False,
        "device_alias": row.device_alias,
        "ingestion_status": row.ingestion_status,
        "simulated_device": flags["simulated_device"],
        "user_entered": flags["user_entered"],
        "label": flags["label"] or (DEVICE_SIM_LABEL if row.source == SOURCE_SIMULATED_DEVICE else None),
        "note": row.note,
        "recorded_at": _iso(row.recorded_at),
        "disclaimer": DEVICE_SIM_LABEL if row.source == SOURCE_SIMULATED_DEVICE else READING_SOURCE_DISCLAIMER,
    }


def _serialize_sos(row: LifesaverSosDemonstration) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "note": row.note,
        "disclaimer": SOS_DISCLAIMER,
        "emergency_services_contacted": False,
        "created_at": _iso(row.created_at),
        "confirmed_at": _iso(row.confirmed_at),
        "acknowledged_at": _iso(row.acknowledged_at),
    }


def _serialize_circle(db: Session, row: LifesaverCareCircleMember) -> dict[str, Any]:
    caregiver = db.query(LifesaverProfile).filter(LifesaverProfile.id == row.caregiver_profile_id).first()
    member = db.query(LifesaverProfile).filter(LifesaverProfile.id == row.member_profile_id).first()
    return {
        "id": row.id,
        "member_profile_id": row.member_profile_id,
        "member_display_name": member.display_name if member else None,
        "caregiver_profile_id": row.caregiver_profile_id,
        "caregiver_display_name": caregiver.display_name if caregiver else None,
        "status": row.status,
        "permissions": sorted(parse_permissions(row.permissions_json)),
        "created_at": _iso(row.created_at),
        "revoked_at": _iso(row.revoked_at),
    }


def _serialize_alert(row: LifesaverAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "alert_type": row.alert_type,
        "severity": row.severity,
        "title": row.title,
        "message": row.message,
        "status": row.status,
        "requires_ack": row.requires_ack,
        "member_profile_id": row.member_profile_id,
        "caregiver_profile_id": row.caregiver_profile_id,
        "created_at": _iso(row.created_at),
        "acknowledged_at": _iso(row.acknowledged_at),
    }


def _serialize_task(row: LifesaverCareTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "member_profile_id": row.member_profile_id,
        "assigned_caregiver_id": row.assigned_caregiver_id,
        "title": row.title,
        "due_at": _iso(row.due_at),
        "status": row.status,
        "created_at": _iso(row.created_at),
    }


def _serialize_handoff(row: LifesaverHandoff) -> dict[str, Any]:
    return {
        "id": row.id,
        "member_profile_id": row.member_profile_id,
        "from_caregiver_id": row.from_caregiver_id,
        "to_caregiver_id": row.to_caregiver_id,
        "status": row.status,
        "note": row.note,
        "created_at": _iso(row.created_at),
        "resolved_at": _iso(row.resolved_at),
    }
