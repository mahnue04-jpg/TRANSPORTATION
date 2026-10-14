"""Persist the sandbox Casting pilot. Campaigns stay unpublished and mail is not sent."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .casting_access import CastingAccessDenied
from .casting_db_writes import (
    _account,
    _application_row,
    _campaign_row,
    _guard,
    _member,
    _org,
)
from .casting_identity import applicant_from_verified_session
from .casting_pilot import PilotDenied, PilotDirectory, PilotRejected
from .casting_pilot_models import (
    NovaCastingIntake,
    NovaCastingPilotAudit,
    NovaCastingPilotMessage,
    NovaCastingRole,
    NovaCastingRubric,
    NovaCastingSchedule,
    NovaCastingSuppression,
)
from .casting_policy import may_manage_campaign, may_review_application


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _organizer_actor(db: Session, user_id: str, tenant_id: str, organization_id: str) -> dict:
    _guard()
    actor = _member(db, user_id, tenant_id, organization_id)
    if not may_manage_campaign(actor, organization_id=organization_id):
        raise CastingAccessDenied("Campaign unavailable")
    return {
        "user_id": user_id,
        "organization_id": organization_id,
        "role": "organizer",
        "verified": True,
    }


def _review_actor(db: Session, user_id: str, tenant_id: str, organization_id: str) -> dict:
    _guard()
    actor = _member(db, user_id, tenant_id, organization_id)
    if not may_review_application(actor, organization_id=organization_id):
        raise CastingAccessDenied("Application unavailable")
    role = "organizer" if may_manage_campaign(actor, organization_id=organization_id) else "reviewer"
    return {
        "user_id": user_id,
        "organization_id": organization_id,
        "role": role,
        "verified": True,
    }


def _applicant_context(db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str):
    _guard()
    _account(db, user_id, tenant_id)
    org = _org(db, organization_id, tenant_id)
    if org.verification_status != "VERIFIED":
        raise CastingAccessDenied("Application unavailable")
    if applicant_from_verified_session(session_user_id=user_id) is None:
        raise CastingAccessDenied("Application unavailable")
    application = _application_row(db, organization_id, application_id)
    if application.applicant_id != user_id:
        raise CastingAccessDenied("Application unavailable")
    campaign = _campaign_row(db, organization_id, application.campaign_id)
    if campaign.status != "DRAFT":
        raise CastingAccessDenied("Application unavailable")
    actor = {
        "user_id": user_id,
        "organization_id": organization_id,
        "role": "applicant",
        "verified": True,
    }
    return actor, application, campaign


def _load(db: Session, organization_id: str) -> PilotDirectory:
    directory = PilotDirectory(_now())
    try:
        roles = db.query(NovaCastingRole).filter(NovaCastingRole.organization_id == organization_id).all()
        intakes = db.query(NovaCastingIntake).filter(NovaCastingIntake.organization_id == organization_id).all()
        rubrics = db.query(NovaCastingRubric).filter(NovaCastingRubric.organization_id == organization_id).all()
        messages = db.query(NovaCastingPilotMessage).filter(NovaCastingPilotMessage.organization_id == organization_id).all()
        suppressions = db.query(NovaCastingSuppression).filter(NovaCastingSuppression.organization_id == organization_id).all()
        schedules = db.query(NovaCastingSchedule).filter(NovaCastingSchedule.organization_id == organization_id).all()
        audit_rows = db.query(NovaCastingPilotAudit).filter(NovaCastingPilotAudit.organization_id == organization_id).all()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    for row in roles:
        directory.roles[row.id] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "campaign_id": row.campaign_id,
            "title": row.title,
            "requirements": row.requirements,
            "deadline": row.deadline,
            "minimum_age": row.minimum_age,
            "questions": json.loads(row.questions_json or "[]"),
            "created_at": row.created_at,
            "published": False,
        }
    for row in intakes:
        directory.intakes[row.id] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "campaign_id": row.campaign_id,
            "role_id": row.role_id,
            "applicant_id": row.applicant_id,
            "display_name": row.display_name,
            "contact_email": row.contact_email,
            "video_url": row.video_url,
            "answers": json.loads(row.answers_json or "{}"),
            "age_years": row.age_years,
            "consent_version": row.consent_version,
            "retention_notice": "",
            "retention_days": row.retention_days,
            "consent_expires_at": row.consent_expires_at,
            "consent_revoked_at": row.consent_revoked_at or "",
            "receipt": row.receipt,
            "status": row.status,
            "stage": row.stage,
            "shortlisted": bool(row.shortlisted),
            "minimized": bool(row.minimized),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "published": False,
        }
    directory.rubrics = [
        {
            "id": row.id,
            "organization_id": row.organization_id,
            "application_id": row.application_id,
            "reviewer_id": row.reviewer_id,
            "criterion": row.criterion,
            "score": row.score,
            "comment": row.comment,
            "updated_at": row.updated_at,
            "automatic_cast": False,
        }
        for row in rubrics
    ]
    for row in messages:
        directory.messages[row.id] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "application_id": row.application_id,
            "kind": row.kind,
            "channel": row.channel,
            "body": row.body,
            "status": row.status,
            "idempotency_key": row.idempotency_key,
            "attempt_count": row.attempt_count,
            "approved_by": row.approved_by,
            "delivery_state": "not_sent",
            "external_delivery": False,
            "delivered": False,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    for row in suppressions:
        directory.suppressions[(row.organization_id, row.contact_email)] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "contact_email": row.contact_email,
            "reason": row.reason,
            "created_at": row.created_at,
        }
    for row in schedules:
        directory.schedules[row.role_id] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "campaign_id": row.campaign_id,
            "role_id": row.role_id,
            "timezone": row.timezone_name,
            "starts_at": row.starts_at,
            "ends_at": row.ends_at,
            "location_label": row.location_label,
            "document_url": row.document_url,
            "updated_at": row.updated_at,
            "published": False,
        }
    directory.audit = [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "organization_id": row.organization_id,
            "action": row.action,
            "object_id": row.object_id,
            "occurred_at": row.occurred_at,
        }
        for row in audit_rows
    ]
    return directory


def _persist(db: Session, organization_id: str, directory: PilotDirectory, known_audit: set[str]) -> None:
    try:
        db.query(NovaCastingRubric).filter(NovaCastingRubric.organization_id == organization_id).delete(synchronize_session=False)
        db.query(NovaCastingIntake).filter(NovaCastingIntake.organization_id == organization_id).delete(synchronize_session=False)
        db.query(NovaCastingSchedule).filter(NovaCastingSchedule.organization_id == organization_id).delete(synchronize_session=False)
        db.query(NovaCastingRole).filter(NovaCastingRole.organization_id == organization_id).delete(synchronize_session=False)
        db.query(NovaCastingPilotMessage).filter(NovaCastingPilotMessage.organization_id == organization_id).delete(synchronize_session=False)
        db.query(NovaCastingSuppression).filter(NovaCastingSuppression.organization_id == organization_id).delete(synchronize_session=False)
        db.flush()
        _replace_roles(db, organization_id, directory)
        _replace_intakes(db, organization_id, directory)
        _replace_rubrics(db, organization_id, directory)
        _replace_messages(db, organization_id, directory)
        _replace_suppressions(db, organization_id, directory)
        _replace_schedules(db, organization_id, directory)
        for item in directory.audit:
            if item["id"] in known_audit or item["organization_id"] != organization_id:
                continue
            db.add(NovaCastingPilotAudit(
                id=item["id"], actor_id=item["actor_id"], organization_id=organization_id,
                action=item["action"], object_id=item["object_id"], occurred_at=item["occurred_at"],
            ))
        db.flush()
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc


def _replace_roles(db: Session, organization_id: str, directory: PilotDirectory) -> None:
    for row in directory.roles.values():
        if row["organization_id"] != organization_id:
            continue
        db.add(NovaCastingRole(
            id=row["id"], organization_id=organization_id, campaign_id=row["campaign_id"],
            title=row["title"], requirements=row["requirements"], deadline=row["deadline"],
            questions_json=json.dumps(row["questions"], separators=(",", ":")),
            minimum_age=row["minimum_age"], created_at=row["created_at"],
        ))


def _replace_intakes(db: Session, organization_id: str, directory: PilotDirectory) -> None:
    for row in directory.intakes.values():
        if row["organization_id"] != organization_id:
            continue
        db.add(NovaCastingIntake(
            id=row["id"], organization_id=organization_id, campaign_id=row["campaign_id"],
            role_id=row["role_id"], applicant_id=row["applicant_id"],
            display_name=row["display_name"], contact_email=row["contact_email"],
            video_url=row["video_url"], answers_json=json.dumps(row["answers"], separators=(",", ":")),
            age_years=row["age_years"], consent_version=row["consent_version"],
            retention_days=row["retention_days"], consent_expires_at=row["consent_expires_at"],
            consent_revoked_at=row["consent_revoked_at"] or "", receipt=row["receipt"],
            status=row["status"], stage=row["stage"], shortlisted=bool(row["shortlisted"]),
            minimized=bool(row["minimized"]), created_at=row["created_at"], updated_at=row["updated_at"],
        ))


def _replace_rubrics(db: Session, organization_id: str, directory: PilotDirectory) -> None:
    for row in directory.rubrics:
        if row["organization_id"] != organization_id:
            continue
        db.add(NovaCastingRubric(
            id=row["id"], organization_id=organization_id, application_id=row["application_id"],
            reviewer_id=row["reviewer_id"], criterion=row["criterion"], score=row["score"],
            comment=row["comment"], updated_at=row["updated_at"],
        ))


def _replace_messages(db: Session, organization_id: str, directory: PilotDirectory) -> None:
    for row in directory.messages.values():
        if row["organization_id"] != organization_id:
            continue
        db.add(NovaCastingPilotMessage(
            id=row["id"], organization_id=organization_id, application_id=row["application_id"],
            kind=row["kind"], channel=row["channel"], body=row["body"], status=row["status"],
            idempotency_key=row["idempotency_key"], attempt_count=row["attempt_count"],
            approved_by=row["approved_by"], delivery_state="not_sent",
            created_at=row["created_at"], updated_at=row["updated_at"],
        ))


def _replace_suppressions(db: Session, organization_id: str, directory: PilotDirectory) -> None:
    for row in directory.suppressions.values():
        if row["organization_id"] != organization_id:
            continue
        db.add(NovaCastingSuppression(
            id=row["id"], organization_id=organization_id, contact_email=row["contact_email"],
            reason=row["reason"], created_at=row["created_at"],
        ))


def _replace_schedules(db: Session, organization_id: str, directory: PilotDirectory) -> None:
    for row in directory.schedules.values():
        if row["organization_id"] != organization_id:
            continue
        db.add(NovaCastingSchedule(
            id=row["id"], organization_id=organization_id, campaign_id=row["campaign_id"],
            role_id=row["role_id"], timezone_name=row["timezone"], starts_at=row["starts_at"],
            ends_at=row["ends_at"], location_label=row["location_label"],
            document_url=row["document_url"], updated_at=row["updated_at"],
        ))


def _run(db: Session, organization_id: str, actor: dict, method: str, *args, **kwargs):
    try:
        directory = _load(db, organization_id)
    except CastingAccessDenied:
        raise
    directory.now = _now()
    known = {item["id"] for item in directory.audit}
    try:
        result = getattr(directory, method)(actor, *args, **kwargs)
    except PilotDenied as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    except PilotRejected:
        raise
    if directory.changed:
        _persist(db, organization_id, directory, known)
    return result


def create_role(*, db: Session, user_id: str, tenant_id: str, organization_id: str, campaign_id: str, payload: dict) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    _campaign_row(db, organization_id, campaign_id)
    return _run(db, organization_id, actor, "create_role", campaign_id, payload)


def list_roles(*, db: Session, user_id: str, tenant_id: str, organization_id: str, campaign_id: str, limit: int, offset: int) -> dict:
    actor = _review_actor(db, user_id, tenant_id, organization_id)
    _campaign_row(db, organization_id, campaign_id)
    return _run(db, organization_id, actor, "list_roles", campaign_id, limit, offset)


def save_intake(*, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str, payload: dict) -> dict:
    actor, application, _campaign = _applicant_context(db, user_id, tenant_id, organization_id, application_id)
    return _run(
        db, organization_id, actor, "save_intake",
        application_id=application_id, campaign_id=application.campaign_id, payload=payload,
    )


def submit_intake(*, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str) -> dict:
    actor, _application, _campaign = _applicant_context(db, user_id, tenant_id, organization_id, application_id)
    return _run(db, organization_id, actor, "submit_intake", application_id)


def revoke_intake(*, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str) -> dict:
    actor, _application, _campaign = _applicant_context(db, user_id, tenant_id, organization_id, application_id)
    return _run(db, organization_id, actor, "revoke_intake", application_id)


def minimize_intake(*, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str) -> dict:
    _guard()
    try:
        actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    except CastingAccessDenied:
        actor, _application, _campaign = _applicant_context(db, user_id, tenant_id, organization_id, application_id)
    return _run(db, organization_id, actor, "minimize_intake", application_id)


def review_queue(*, db: Session, user_id: str, tenant_id: str, organization_id: str, query: str, status: str,
                 shortlisted: str, limit: int, offset: int) -> dict:
    actor = _review_actor(db, user_id, tenant_id, organization_id)
    return _run(
        db, organization_id, actor, "queue",
        query=query, status=status, shortlisted=shortlisted, limit=limit, offset=offset,
    )


def set_review(*, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str, payload: dict) -> dict:
    actor = _review_actor(db, user_id, tenant_id, organization_id)
    return _run(
        db, organization_id, actor, "set_review", application_id,
        stage=payload.get("stage"), shortlisted=payload.get("shortlisted"),
    )


def add_rubric(*, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str, payload: dict) -> dict:
    actor = _review_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "add_rubric", application_id, payload)


def draft_message(*, db: Session, user_id: str, tenant_id: str, organization_id: str, payload: dict,
                  sms_configured: bool = False, whatsapp_configured: bool = False) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    return _run(
        db, organization_id, actor, "draft_message", payload,
        sms_configured=sms_configured, whatsapp_configured=whatsapp_configured,
    )


def approve_message(*, db: Session, user_id: str, tenant_id: str, organization_id: str, message_id: str) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "approve_message", message_id)


def retry_message(*, db: Session, user_id: str, tenant_id: str, organization_id: str, message_id: str) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "retry_message", message_id)


def suppress(*, db: Session, user_id: str, tenant_id: str, organization_id: str, payload: dict) -> dict:
    _guard()
    try:
        actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    except CastingAccessDenied:
        _account(db, user_id, tenant_id)
        _org(db, organization_id, tenant_id)
        actor = {"user_id": user_id, "organization_id": organization_id, "role": "applicant", "verified": True}
    return _run(db, organization_id, actor, "suppress", payload)


def save_schedule(*, db: Session, user_id: str, tenant_id: str, organization_id: str, campaign_id: str, payload: dict) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    _campaign_row(db, organization_id, campaign_id)
    return _run(db, organization_id, actor, "save_schedule", campaign_id, payload)


def call_sheet(*, db: Session, user_id: str, tenant_id: str, organization_id: str, role_id: str) -> dict:
    _guard()
    try:
        actor = _review_actor(db, user_id, tenant_id, organization_id)
    except CastingAccessDenied:
        _account(db, user_id, tenant_id)
        _org(db, organization_id, tenant_id)
        actor = {"user_id": user_id, "organization_id": organization_id, "role": "applicant", "verified": True}
    return _run(db, organization_id, actor, "call_sheet", role_id)


def export_csv(*, db: Session, user_id: str, tenant_id: str, organization_id: str, include_contact: bool) -> str:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "export_csv", include_contact=include_contact)


def list_audit(*, db: Session, user_id: str, tenant_id: str, organization_id: str, limit: int, offset: int) -> dict:
    actor = _review_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "list_audit", limit, offset)


def seed_harborlight(*, db: Session, user_id: str, tenant_id: str, organization_id: str, campaign_id: str) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    campaign = _campaign_row(db, organization_id, campaign_id)
    if campaign.status != "DRAFT":
        raise CastingAccessDenied("Campaign unavailable")
    return _run(db, organization_id, actor, "seed_harborlight", campaign_id)
