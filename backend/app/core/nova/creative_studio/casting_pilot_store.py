"""Persist the sandbox Casting pilot. Campaigns stay unpublished and mail is not sent."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .casting_access import CastingAccessDenied
from .casting_db_models import NovaCastingApplication, NovaCastingCampaign, NovaCastingOrganization
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
    NovaCastingInvite,
    NovaCastingJourneyAudit,
    NovaCastingMockAttempt,
    NovaCastingMockMedia,
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
        "tenant_id": tenant_id,
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
        "tenant_id": tenant_id,
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
        "tenant_id": tenant_id,
        "role": "applicant",
        "verified": True,
    }
    return actor, application, campaign


def _applicant_actor(db: Session, user_id: str, tenant_id: str, organization_id: str) -> dict:
    _guard()
    _account(db, user_id, tenant_id)
    org = _org(db, organization_id, tenant_id)
    if org.verification_status != "VERIFIED":
        raise CastingAccessDenied("Application unavailable")
    if applicant_from_verified_session(session_user_id=user_id) is None:
        raise CastingAccessDenied("Application unavailable")
    return {
        "user_id": user_id,
        "organization_id": organization_id,
        "tenant_id": tenant_id,
        "role": "applicant",
        "verified": True,
    }


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
        invites = db.query(NovaCastingInvite).filter(NovaCastingInvite.organization_id == organization_id).all()
        attempts = db.query(NovaCastingMockAttempt).filter(NovaCastingMockAttempt.organization_id == organization_id).all()
        media_rows = db.query(NovaCastingMockMedia).filter(NovaCastingMockMedia.organization_id == organization_id).all()
        journey_rows = db.query(NovaCastingJourneyAudit).filter(NovaCastingJourneyAudit.organization_id == organization_id).all()
        organization = db.query(NovaCastingOrganization).filter(NovaCastingOrganization.id == organization_id).one_or_none()
        campaigns = db.query(NovaCastingCampaign).filter(NovaCastingCampaign.owner_id == organization_id).all()
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
            "mock_outcome": "",
            "mock_receipt": "",
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
    tenant_id = organization.nova_tenant_id if organization is not None else ""
    directory.tenant_id = tenant_id
    for row in campaigns:
        directory.note_campaign(
            organization_id=organization_id,
            tenant_id=tenant_id,
            campaign_id=row.id,
            status=row.status,
        )
    for row in invites:
        directory.invites[row.id] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "tenant_id": row.tenant_id,
            "campaign_id": row.campaign_id,
            "role_id": row.role_id,
            "token": row.token,
            "expires_at": row.expires_at,
            "status": row.status,
            "applicant_id": row.applicant_id,
            "application_id": row.application_id,
            "created_at": row.created_at,
            "redeemed_at": row.redeemed_at or "",
            "published": False,
        }
    for row in attempts:
        directory.mock_attempts[row.id] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "message_id": row.message_id,
            "attempt_number": row.attempt_number,
            "outcome": row.outcome,
            "mock_receipt": row.mock_receipt,
            "failure_reason": row.failure_reason,
            "provider": row.provider,
            "created_at": row.created_at,
        }
        message = directory.messages.get(row.message_id)
        if message is not None and row.attempt_number >= int(message.get("mock_attempt_number") or 0):
            message["mock_outcome"] = row.outcome
            message["mock_receipt"] = row.mock_receipt
            message["mock_attempt_number"] = row.attempt_number
    for row in media_rows:
        directory.mock_media[row.id] = {
            "id": row.id,
            "organization_id": row.organization_id,
            "application_id": row.application_id,
            "applicant_id": row.applicant_id,
            "mime_type": row.mime_type,
            "byte_size": row.byte_size,
            "scan_status": row.scan_status,
            "scan_reason": row.scan_reason,
            "public_url": "",
            "created_at": row.created_at,
        }
    directory.journey_audit = [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "organization_id": row.organization_id,
            "action": row.action,
            "object_id": row.object_id,
            "occurred_at": row.occurred_at,
        }
        for row in journey_rows
    ]
    return directory


def _lock_organization(db: Session, organization_id: str) -> None:
    """Serialize pilot writers on the organization before the snapshot is read."""
    try:
        locked = (
            db.query(NovaCastingOrganization)
            .filter(NovaCastingOrganization.id == organization_id)
            .with_for_update()
            .one_or_none()
        )
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if locked is None:
        raise CastingAccessDenied("Application unavailable")


def _capture(directory: PilotDirectory) -> dict:
    """Copy the loaded snapshot so persist can write this request's diff."""
    return {
        "roles": copy.deepcopy(directory.roles),
        "intakes": copy.deepcopy(directory.intakes),
        "rubrics": {row["id"]: copy.deepcopy(row) for row in directory.rubrics},
        "messages": copy.deepcopy(directory.messages),
        "suppressions": {row["id"]: copy.deepcopy(row) for row in directory.suppressions.values()},
        "schedules": {row["id"]: copy.deepcopy(row) for row in directory.schedules.values()},
        "audit": {item["id"] for item in directory.audit},
        "invites": copy.deepcopy(directory.invites),
        "mock_attempts": copy.deepcopy(directory.mock_attempts),
        "mock_media": copy.deepcopy(directory.mock_media),
        "journey_audit": {item["id"] for item in directory.journey_audit},
    }


def _copy_columns(target, source) -> None:
    for attr in source.__mapper__.column_attrs:
        if attr.columns[0].primary_key:
            continue
        value = getattr(source, attr.key)
        if getattr(target, attr.key) != value:
            setattr(target, attr.key, value)


def _delete_absent(db: Session, model, organization_id: str, before: dict, after: dict) -> bool:
    gone = [
        row_id for row_id, row in before.items()
        if row.get("organization_id") == organization_id and row_id not in after
    ]
    if not gone:
        return False
    existing = {
        row.id: row
        for row in db.query(model).filter(model.organization_id == organization_id)
    }
    deleted = False
    for row_id in gone:
        current = existing.get(row_id)
        if current is None:
            continue
        db.delete(current)
        deleted = True
    return deleted


def _upsert(db: Session, model, organization_id: str, before: dict, after: dict, build) -> None:
    pending = [
        row for row in after.values()
        if row.get("organization_id") == organization_id and before.get(row["id"]) != row
    ]
    if not pending:
        return
    existing = {
        row.id: row
        for row in db.query(model).filter(model.organization_id == organization_id)
    }
    for row in pending:
        current = existing.get(row["id"])
        fresh = build(row)
        if current is None:
            if row["id"] not in before:
                db.add(fresh)
            continue
        if row["id"] not in before:
            continue
        _copy_columns(current, fresh)


def _persist(db: Session, organization_id: str, directory: PilotDirectory, before: dict) -> None:
    try:
        roles = directory.roles
        intakes = directory.intakes
        rubrics = {row["id"]: row for row in directory.rubrics}
        messages = directory.messages
        suppressions = {row["id"]: row for row in directory.suppressions.values()}
        schedules = {row["id"]: row for row in directory.schedules.values()}
        invites = directory.invites
        attempts = directory.mock_attempts
        media = directory.mock_media
        deleted = False
        deleted |= _delete_absent(db, NovaCastingMockMedia, organization_id, before["mock_media"], media)
        deleted |= _delete_absent(db, NovaCastingMockAttempt, organization_id, before["mock_attempts"], attempts)
        deleted |= _delete_absent(db, NovaCastingInvite, organization_id, before["invites"], invites)
        deleted |= _delete_absent(db, NovaCastingRubric, organization_id, before["rubrics"], rubrics)
        deleted |= _delete_absent(db, NovaCastingSchedule, organization_id, before["schedules"], schedules)
        deleted |= _delete_absent(db, NovaCastingPilotMessage, organization_id, before["messages"], messages)
        deleted |= _delete_absent(db, NovaCastingSuppression, organization_id, before["suppressions"], suppressions)
        deleted |= _delete_absent(db, NovaCastingIntake, organization_id, before["intakes"], intakes)
        deleted |= _delete_absent(db, NovaCastingRole, organization_id, before["roles"], roles)
        if deleted:
            db.flush()
        _replace_roles(db, organization_id, before["roles"], roles)
        _replace_intakes(db, organization_id, before["intakes"], intakes)
        _replace_messages(db, organization_id, before["messages"], messages)
        _replace_suppressions(db, organization_id, before["suppressions"], suppressions)
        _replace_schedules(db, organization_id, before["schedules"], schedules)
        _replace_invites(db, organization_id, before["invites"], invites)
        _replace_attempts(db, organization_id, before["mock_attempts"], attempts)
        _replace_mock_media(db, organization_id, before["mock_media"], media)
        _replace_rubrics(db, organization_id, before["rubrics"], rubrics)
        for item in directory.audit:
            if item["id"] in before["audit"] or item["organization_id"] != organization_id:
                continue
            db.add(NovaCastingPilotAudit(
                id=item["id"], actor_id=item["actor_id"], organization_id=organization_id,
                action=item["action"], object_id=item["object_id"], occurred_at=item["occurred_at"],
            ))
        for item in directory.journey_audit:
            if item["id"] in before["journey_audit"] or item["organization_id"] != organization_id:
                continue
            db.add(NovaCastingJourneyAudit(
                id=item["id"], actor_id=item["actor_id"], organization_id=organization_id,
                action=item["action"], object_id=item["object_id"], occurred_at=item["occurred_at"],
            ))
        db.flush()
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc


def _replace_roles(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingRole:
        return NovaCastingRole(
            id=row["id"], organization_id=organization_id, campaign_id=row["campaign_id"],
            title=row["title"], requirements=row["requirements"], deadline=row["deadline"],
            questions_json=json.dumps(row["questions"], separators=(",", ":")),
            minimum_age=row["minimum_age"], created_at=row["created_at"],
        )

    _upsert(db, NovaCastingRole, organization_id, before, rows, build)


def _replace_intakes(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingIntake:
        return NovaCastingIntake(
            id=row["id"], organization_id=organization_id, campaign_id=row["campaign_id"],
            role_id=row["role_id"], applicant_id=row["applicant_id"],
            display_name=row["display_name"], contact_email=row["contact_email"],
            video_url=row["video_url"], answers_json=json.dumps(row["answers"], separators=(",", ":")),
            age_years=row["age_years"], consent_version=row["consent_version"],
            retention_days=row["retention_days"], consent_expires_at=row["consent_expires_at"],
            consent_revoked_at=row["consent_revoked_at"] or "", receipt=row["receipt"],
            status=row["status"], stage=row["stage"], shortlisted=bool(row["shortlisted"]),
            minimized=bool(row["minimized"]), created_at=row["created_at"], updated_at=row["updated_at"],
        )

    _upsert(db, NovaCastingIntake, organization_id, before, rows, build)


def _replace_rubrics(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingRubric:
        return NovaCastingRubric(
            id=row["id"], organization_id=organization_id, application_id=row["application_id"],
            reviewer_id=row["reviewer_id"], criterion=row["criterion"], score=row["score"],
            comment=row["comment"], updated_at=row["updated_at"],
        )

    _upsert(db, NovaCastingRubric, organization_id, before, rows, build)


def _replace_messages(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingPilotMessage:
        return NovaCastingPilotMessage(
            id=row["id"], organization_id=organization_id, application_id=row["application_id"],
            kind=row["kind"], channel=row["channel"], body=row["body"], status=row["status"],
            idempotency_key=row["idempotency_key"], attempt_count=row["attempt_count"],
            approved_by=row["approved_by"], delivery_state="not_sent",
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    _upsert(db, NovaCastingPilotMessage, organization_id, before, rows, build)


def _replace_suppressions(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingSuppression:
        return NovaCastingSuppression(
            id=row["id"], organization_id=organization_id, contact_email=row["contact_email"],
            reason=row["reason"], created_at=row["created_at"],
        )

    _upsert(db, NovaCastingSuppression, organization_id, before, rows, build)


def _replace_schedules(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingSchedule:
        return NovaCastingSchedule(
            id=row["id"], organization_id=organization_id, campaign_id=row["campaign_id"],
            role_id=row["role_id"], timezone_name=row["timezone"], starts_at=row["starts_at"],
            ends_at=row["ends_at"], location_label=row["location_label"],
            document_url=row["document_url"], updated_at=row["updated_at"],
        )

    _upsert(db, NovaCastingSchedule, organization_id, before, rows, build)


def _replace_invites(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingInvite:
        return NovaCastingInvite(
            id=row["id"], organization_id=organization_id, tenant_id=row["tenant_id"],
            campaign_id=row["campaign_id"], role_id=row["role_id"], token=row["token"],
            expires_at=row["expires_at"], status=row["status"], applicant_id=row["applicant_id"],
            application_id=row["application_id"], created_at=row["created_at"],
            redeemed_at=row["redeemed_at"],
        )

    _upsert(db, NovaCastingInvite, organization_id, before, rows, build)


def _replace_attempts(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingMockAttempt:
        return NovaCastingMockAttempt(
            id=row["id"], organization_id=organization_id, message_id=row["message_id"],
            attempt_number=row["attempt_number"], outcome=row["outcome"],
            mock_receipt=row["mock_receipt"], failure_reason=row["failure_reason"],
            provider="disposable-mock", created_at=row["created_at"],
        )

    _upsert(db, NovaCastingMockAttempt, organization_id, before, rows, build)


def _replace_mock_media(db: Session, organization_id: str, before: dict, rows: dict) -> None:
    def build(row: dict) -> NovaCastingMockMedia:
        return NovaCastingMockMedia(
            id=row["id"], organization_id=organization_id, application_id=row["application_id"],
            applicant_id=row["applicant_id"], mime_type=row["mime_type"], byte_size=row["byte_size"],
            scan_status=row["scan_status"], scan_reason=row["scan_reason"], public_url="",
            created_at=row["created_at"],
        )

    _upsert(db, NovaCastingMockMedia, organization_id, before, rows, build)


def _bind_redeemed_application(db: Session, organization_id: str, user_id: str, result: dict) -> dict:
    if result.get("status") != "redeemed" or not result.get("application_id"):
        return result
    campaign_id = result["campaign_id"]
    wanted = result["application_id"]
    try:
        existing = db.query(NovaCastingApplication).filter(
            NovaCastingApplication.owner_id == organization_id,
            NovaCastingApplication.campaign_id == campaign_id,
            NovaCastingApplication.applicant_id == user_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if existing is not None:
        if existing.id != wanted:
            invite = db.query(NovaCastingInvite).filter(
                NovaCastingInvite.organization_id == organization_id,
                NovaCastingInvite.application_id == wanted,
            ).one_or_none()
            if invite is not None:
                invite.application_id = existing.id
            result = dict(result)
            result["application_id"] = existing.id
        return result
    db.add(NovaCastingApplication(
        id=wanted, owner_id=organization_id, campaign_id=campaign_id,
        applicant_id=user_id, status="DRAFT", created_at=_now().isoformat(),
    ))
    try:
        db.flush()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    return result


def _run(db: Session, organization_id: str, actor: dict, method: str, *args, **kwargs):
    _lock_organization(db, organization_id)
    try:
        directory = _load(db, organization_id)
    except CastingAccessDenied:
        raise
    directory.now = _now()
    before = _capture(directory)
    try:
        result = getattr(directory, method)(actor, *args, **kwargs)
    except PilotDenied as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    except PilotRejected:
        raise
    if directory.changed:
        _persist(db, organization_id, directory, before)
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
        actor = {
            "user_id": user_id,
            "organization_id": organization_id,
            "tenant_id": tenant_id,
            "role": "applicant",
            "verified": True,
        }
    return _run(db, organization_id, actor, "call_sheet", role_id)


def export_csv(*, db: Session, user_id: str, tenant_id: str, organization_id: str, include_contact: bool) -> str:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "export_csv", include_contact=include_contact)


def list_audit(*, db: Session, user_id: str, tenant_id: str, organization_id: str, limit: int, offset: int) -> dict:
    actor = _review_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "list_audit", limit, offset)


def snapshot(*, db: Session, user_id: str, tenant_id: str, organization_id: str, campaign_id: str) -> dict:
    """Return the persisted sandbox copy for this caller. No message is sent."""
    _guard()
    try:
        actor = _review_actor(db, user_id, tenant_id, organization_id)
    except CastingAccessDenied:
        _account(db, user_id, tenant_id)
        _org(db, organization_id, tenant_id)
        try:
            owned = db.query(NovaCastingApplication).filter(
                NovaCastingApplication.owner_id == organization_id,
                NovaCastingApplication.applicant_id == user_id,
            ).first()
        except SQLAlchemyError as exc:
            raise CastingAccessDenied("Application unavailable") from exc
        if owned is None:
            raise CastingAccessDenied("Application unavailable")
        actor = {
            "user_id": user_id,
            "organization_id": organization_id,
            "tenant_id": tenant_id,
            "role": "applicant",
            "verified": True,
        }
    return _run(db, organization_id, actor, "snapshot", campaign_id)


def seed_harborlight(*, db: Session, user_id: str, tenant_id: str, organization_id: str, campaign_id: str) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    campaign = _campaign_row(db, organization_id, campaign_id)
    if campaign.status != "DRAFT":
        raise CastingAccessDenied("Campaign unavailable")
    return _run(db, organization_id, actor, "seed_harborlight", campaign_id)


def issue_invite(*, db: Session, user_id: str, tenant_id: str, organization_id: str, campaign_id: str, payload: dict) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    campaign = _campaign_row(db, organization_id, campaign_id)
    if campaign.status != "DRAFT":
        raise PilotRejected("Campaign cannot be published")
    return _run(db, organization_id, actor, "issue_invite", campaign_id, payload)


def redeem_invite(*, db: Session, user_id: str, tenant_id: str, organization_id: str, token: str) -> dict:
    actor = _applicant_actor(db, user_id, tenant_id, organization_id)
    result = _run(db, organization_id, actor, "redeem_invite", token)
    return _bind_redeemed_application(db, organization_id, user_id, result)


def dispatch_mock(*, db: Session, user_id: str, tenant_id: str, organization_id: str, message_id: str, fail: bool = False) -> dict:
    actor = _organizer_actor(db, user_id, tenant_id, organization_id)
    return _run(db, organization_id, actor, "dispatch_mock", message_id, fail=fail)


def record_mock_media(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str, meta: dict, data: bytes,
) -> dict:
    actor, _application, _campaign = _applicant_context(db, user_id, tenant_id, organization_id, application_id)
    result = _run(db, organization_id, actor, "record_mock_media", application_id, meta)
    if meta.get("store_bytes") and result.get("scan_status") == "CLEAN":
        from .casting_mock_uploads import hold
        hold(result["id"], data)
    return result


def wipe_mock_holding(*, db: Session, user_id: str, tenant_id: str, organization_id: str) -> dict:
    """Clear disposable mock metadata and this process's bytes. Nothing is published."""
    _organizer_actor(db, user_id, tenant_id, organization_id)
    _lock_organization(db, organization_id)
    directory = _load(db, organization_id)
    before = _capture(directory)
    removed = sum(1 for row in directory.mock_media.values() if row.get("organization_id") == organization_id)
    directory.mock_media = {
        key: row for key, row in directory.mock_media.items()
        if row.get("organization_id") != organization_id
    }
    _persist(db, organization_id, directory, before)
    from .casting_mock_uploads import wipe
    wipe()
    return {
        "wiped": removed,
        "bytes_released": False,
        "public_url": "",
        "media_uploads_enabled": False,
    }


def list_mock_media(*, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str) -> dict:
    _guard()
    try:
        actor = _review_actor(db, user_id, tenant_id, organization_id)
    except CastingAccessDenied:
        actor, _application, _campaign = _applicant_context(db, user_id, tenant_id, organization_id, application_id)
    return _run(db, organization_id, actor, "list_mock_media", application_id)
