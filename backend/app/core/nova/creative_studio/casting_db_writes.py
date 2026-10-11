"""Disposable sandbox writes for Nova Casting.

Imported only after the production-locked flag passes. Campaigns stay unpublished.
No email, SMS, signed URL, or file bytes are accepted or sent.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import User as NovaUser

from .casting_access import CastingAccessDenied, CastingRequestRejected, submit_application
from .casting_audit import casting_audit_event
from .casting_db_models import (
    NovaCastingApplication,
    NovaCastingAuditEvent,
    NovaCastingCampaign,
    NovaCastingConsentEvent,
    NovaCastingMedia,
    NovaCastingOrganization,
    NovaCastingReview,
)
from .casting_db_reads import _active_account, _membership_lookup, _organization_in_tenant
from .casting_flags import casting_sandbox_writes_enabled
from .casting_identity import applicant_from_verified_session
from .casting_intake_schema import validate_draft_campaign, validate_sandbox_application
from .casting_media_access import read_media_metadata
from .casting_membership import verified_casting_member
from .casting_policy import may_manage_campaign, may_review_application, may_upload_audition
from .casting_responses import (
    applicant_application_view,
    campaign_public_view,
    media_status_view,
    organizer_application_view,
)
from .casting_upload_rules import ALLOWED_MIME_TYPES, MAX_VIDEO_BYTES
from .casting_workflow_policy import ApplicationState, may_schedule_callback, may_transition_application

_REVIEW_STAGES = frozenset({"New", "In review", "Callback", "Closed"})
_PAGE_LIMIT = 50


def _guard() -> None:
    if not casting_sandbox_writes_enabled():
        raise CastingAccessDenied("Application unavailable")


def _new_id() -> str:
    return uuid4().hex


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _flush(db: Session) -> None:
    try:
        db.flush()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc


def _bounds(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or isinstance(offset, bool):
        raise CastingRequestRejected("Request rejected")
    if not isinstance(limit, int) or not isinstance(offset, int):
        raise CastingRequestRejected("Request rejected")
    if limit < 1 or limit > _PAGE_LIMIT or offset < 0 or offset > 10000:
        raise CastingRequestRejected("Request rejected")
    return limit, offset


def _account(db: Session, user_id: str, tenant_id: str) -> NovaUser:
    try:
        account = _active_account(db, user_id, tenant_id)
    except (LookupError, ConnectionError, TimeoutError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if account is None:
        raise CastingAccessDenied("Application unavailable")
    return account


def _org(db: Session, organization_id: str, tenant_id: str) -> NovaCastingOrganization:
    try:
        if not _organization_in_tenant(db, organization_id, tenant_id):
            raise CastingAccessDenied("Application unavailable")
        org = db.query(NovaCastingOrganization).filter(
            NovaCastingOrganization.id == organization_id,
            NovaCastingOrganization.nova_tenant_id == tenant_id,
        ).one()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    return org


def _member(db: Session, user_id: str, tenant_id: str, organization_id: str):
    _account(db, user_id, tenant_id)
    _org(db, organization_id, tenant_id)
    try:
        actor = verified_casting_member(
            session_user_id=user_id,
            organization_id=organization_id,
            session_tenant_id=tenant_id,
            lookup=_membership_lookup(db, tenant_id),
        )
    except (LookupError, ConnectionError, TimeoutError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if actor is None:
        raise CastingAccessDenied("Application unavailable")
    return actor


def _campaign_row(db: Session, organization_id: str, campaign_id: str) -> NovaCastingCampaign:
    try:
        row = db.query(NovaCastingCampaign).filter(
            NovaCastingCampaign.id == campaign_id,
            NovaCastingCampaign.owner_id == organization_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Campaign unavailable") from exc
    if row is None:
        raise CastingAccessDenied("Campaign unavailable")
    return row


def _application_row(db: Session, organization_id: str, application_id: str) -> NovaCastingApplication:
    try:
        row = db.query(NovaCastingApplication).filter(
            NovaCastingApplication.id == application_id,
            NovaCastingApplication.owner_id == organization_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if row is None:
        raise CastingAccessDenied("Application unavailable")
    return row


def _campaign_dict(row: NovaCastingCampaign) -> dict:
    return dict(
        id=row.id, owner_id=row.owner_id, title=row.title, category=row.category,
        status=row.status, created_at=row.created_at, minimum_age=row.minimum_age,
    )


def _application_dict(row: NovaCastingApplication) -> dict:
    return dict(
        id=row.id, campaign_id=row.campaign_id, owner_id=row.owner_id,
        applicant_id=row.applicant_id, status=row.status, created_at=row.created_at,
    )


def _audit(db: Session, *, actor_id: str, organization_id: str, action: str, object_id: str) -> None:
    try:
        event = casting_audit_event(
            actor_id=actor_id, organization_id=organization_id,
            action=action, object_id=object_id,
        )
        db.add(NovaCastingAuditEvent(id=_new_id(), **event))
        db.flush()
    except (SQLAlchemyError, ValueError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc


def _page(items: list, limit: int, offset: int) -> dict:
    return {"items": items, "limit": limit, "offset": offset}


def create_draft_campaign(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str, payload: dict,
) -> dict:
    _guard()
    actor = _member(db, user_id, tenant_id, organization_id)
    if not may_manage_campaign(actor, organization_id=organization_id):
        raise CastingAccessDenied("Campaign unavailable")
    decision = validate_draft_campaign(payload)
    if not decision.accepted:
        raise CastingRequestRejected(decision.reason)
    if payload.get("status", "DRAFT") != "DRAFT":
        raise CastingRequestRejected("Request rejected")
    row = NovaCastingCampaign(
        id=_new_id(), owner_id=organization_id, title=str(payload["title"]).strip(),
        category=payload["category"], status="DRAFT",
        minimum_age=int(payload.get("minimum_age", 18)), created_at=_now(),
    )
    db.add(row)
    _flush(db)
    _audit(db, actor_id=user_id, organization_id=organization_id, action="campaign.created", object_id=row.id)
    return campaign_public_view(_campaign_dict(row))


def update_draft_campaign(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    campaign_id: str, payload: dict,
) -> dict:
    _guard()
    actor = _member(db, user_id, tenant_id, organization_id)
    if not may_manage_campaign(actor, organization_id=organization_id):
        raise CastingAccessDenied("Campaign unavailable")
    decision = validate_draft_campaign(payload)
    if not decision.accepted:
        raise CastingRequestRejected(decision.reason)
    row = _campaign_row(db, organization_id, campaign_id)
    if row.status != "DRAFT":
        raise CastingAccessDenied("Campaign unavailable")
    row.title = str(payload["title"]).strip()
    row.category = str(payload["category"])
    row.minimum_age = int(payload.get("minimum_age", 18))
    row.status = str(payload.get("status", "DRAFT"))
    _flush(db)
    return campaign_public_view(_campaign_dict(row))


def list_draft_campaigns(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    limit: int = 20, offset: int = 0,
) -> dict:
    _guard()
    limit, offset = _bounds(limit, offset)
    actor = _member(db, user_id, tenant_id, organization_id)
    if not may_review_application(actor, organization_id=organization_id):
        raise CastingAccessDenied("Campaign unavailable")
    try:
        rows = (
            db.query(NovaCastingCampaign)
            .filter(NovaCastingCampaign.owner_id == organization_id)
            .order_by(NovaCastingCampaign.created_at, NovaCastingCampaign.id)
            .offset(offset).limit(limit).all()
        )
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Campaign unavailable") from exc
    return _page([campaign_public_view(_campaign_dict(row)) for row in rows], limit, offset)


def _record_consent(
    db: Session, *, application: NovaCastingApplication, user_id: str, age_years: int, version: str,
) -> None:
    db.add(NovaCastingConsentEvent(
        id=_new_id(), owner_id=application.owner_id, application_id=application.id,
        applicant_id=user_id, consent_version=version.strip(),
        minimum_age_attested=age_years, accepted=True, created_at=_now(),
    ))
    application.consent_version = version.strip()
    _flush(db)


def save_test_application(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    campaign_id: str, payload: dict,
) -> dict:
    _guard()
    _account(db, user_id, tenant_id)
    org = _org(db, organization_id, tenant_id)
    if org.verification_status != "VERIFIED":
        raise CastingAccessDenied("Application unavailable")
    campaign = _campaign_row(db, organization_id, campaign_id)
    if campaign.status != "DRAFT":
        raise CastingAccessDenied("Application unavailable")
    actor = applicant_from_verified_session(session_user_id=user_id)
    if actor is None:
        raise CastingAccessDenied("Application unavailable")
    decision = validate_sandbox_application(payload, minimum_age=campaign.minimum_age)
    if not decision.accepted:
        raise CastingRequestRejected(decision.reason)
    try:
        existing = db.query(NovaCastingApplication).filter(
            NovaCastingApplication.campaign_id == campaign_id,
            NovaCastingApplication.applicant_id == user_id,
            NovaCastingApplication.owner_id == organization_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if existing is not None:
        if existing.status == "DRAFT":
            _record_consent(
                db, application=existing, user_id=user_id,
                age_years=int(payload["age_years"]), version=str(payload["consent_version"]),
            )
        return applicant_application_view(_application_dict(existing))
    row = NovaCastingApplication(
        id=_new_id(), owner_id=organization_id, campaign_id=campaign_id,
        applicant_id=user_id, status="DRAFT", created_at=_now(),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            _record_consent(
                db, application=row, user_id=user_id,
                age_years=int(payload["age_years"]), version=str(payload["consent_version"]),
            )
    except IntegrityError:
        existing = db.query(NovaCastingApplication).filter(
            NovaCastingApplication.campaign_id == campaign_id,
            NovaCastingApplication.applicant_id == user_id,
        ).one()
        return applicant_application_view(_application_dict(existing))
    return applicant_application_view(_application_dict(row))


def _consent_recorded(db: Session, application: NovaCastingApplication, minimum_age: int) -> bool:
    try:
        rows = db.query(NovaCastingConsentEvent).filter(
            NovaCastingConsentEvent.application_id == application.id,
            NovaCastingConsentEvent.owner_id == application.owner_id,
            NovaCastingConsentEvent.applicant_id == application.applicant_id,
        ).all()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    return any(
        (row.accepted is True or row.accepted == 1)
        and row.minimum_age_attested >= minimum_age
        and bool(row.consent_version)
        for row in rows
    )


def submit_test_application(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str,
) -> dict:
    _guard()
    _account(db, user_id, tenant_id)
    application = _application_row(db, organization_id, application_id)
    if application.applicant_id != user_id:
        raise CastingAccessDenied("Application unavailable")
    campaign = _campaign_row(db, organization_id, application.campaign_id)
    if campaign.status != "DRAFT":
        raise CastingAccessDenied("Application unavailable")
    actor = applicant_from_verified_session(session_user_id=user_id)
    allowed = submit_application(
        actor=actor, application=_application_dict(application),
        campaign=_campaign_dict(campaign),
        consent_recorded=_consent_recorded(db, application, campaign.minimum_age),
        sandbox_intake=True,
    )
    if not allowed:
        raise CastingRequestRejected("Consent required")
    application.status = ApplicationState.SUBMITTED.value
    _flush(db)
    _audit(
        db, actor_id=user_id, organization_id=organization_id,
        action="application.submitted", object_id=application.id,
    )
    return applicant_application_view(_application_dict(application))


def withdraw_test_application(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str,
) -> dict:
    _guard()
    _account(db, user_id, tenant_id)
    application = _application_row(db, organization_id, application_id)
    actor = applicant_from_verified_session(session_user_id=user_id)
    if actor is None:
        raise CastingAccessDenied("Application unavailable")
    try:
        current = ApplicationState(application.status)
    except ValueError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    allowed = may_transition_application(
        actor, applicant_id=application.applicant_id, organization_id=organization_id,
        current=current, target=ApplicationState.WITHDRAWN,
    )
    if not allowed:
        raise CastingAccessDenied("Application unavailable")
    application.status = ApplicationState.WITHDRAWN.value
    _flush(db)
    _audit(
        db, actor_id=user_id, organization_id=organization_id,
        action="application.withdrawn", object_id=application.id,
    )
    return applicant_application_view(_application_dict(application))


def list_applications(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    limit: int = 20, offset: int = 0,
) -> dict:
    _guard()
    limit, offset = _bounds(limit, offset)
    _account(db, user_id, tenant_id)
    _org(db, organization_id, tenant_id)
    member = None
    try:
        member = verified_casting_member(
            session_user_id=user_id, organization_id=organization_id,
            session_tenant_id=tenant_id, lookup=_membership_lookup(db, tenant_id),
        )
    except (LookupError, ConnectionError, TimeoutError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    try:
        query = db.query(NovaCastingApplication).filter(NovaCastingApplication.owner_id == organization_id)
        if member is not None and may_review_application(member, organization_id=organization_id):
            rows = query.order_by(NovaCastingApplication.created_at, NovaCastingApplication.id).offset(offset).limit(limit).all()
            items = [organizer_application_view(_application_dict(row)) for row in rows]
            return _page(items, limit, offset)
        owned = query.filter(NovaCastingApplication.applicant_id == user_id)
        if owned.count() == 0:
            raise CastingAccessDenied("Application unavailable")
        own = owned.order_by(
            NovaCastingApplication.created_at, NovaCastingApplication.id,
        ).offset(offset).limit(limit).all()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    return _page([applicant_application_view(_application_dict(row)) for row in own], limit, offset)


def _review_payload(row: NovaCastingReview) -> dict:
    return {
        "id": row.id,
        "application_id": row.application_id,
        "stage": row.stage,
        "score": row.score,
        "note": row.note,
        "updated_at": row.updated_at,
        "shortlisted": row.stage == "In review",
        "callback_proposed": row.stage == "Callback",
        "external_delivery": False,
    }


def _check_review_fields(*, stage: str, score: object, note: object) -> None:
    if stage not in _REVIEW_STAGES:
        raise CastingRequestRejected("Invalid review")
    if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5):
        raise CastingRequestRejected("Invalid review")
    if not isinstance(note, str) or len(note) > 2000:
        raise CastingRequestRejected("Invalid review")


def _upsert_review(
    db: Session, *, actor_id: str, organization_id: str, application: NovaCastingApplication,
    stage: str, score: int | None, note: str, audit_action: str,
) -> dict:
    try:
        row = db.query(NovaCastingReview).filter(
            NovaCastingReview.application_id == application.id,
            NovaCastingReview.reviewer_id == actor_id,
            NovaCastingReview.owner_id == organization_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if audit_action == "callback.proposed" and row is not None and row.stage == "Callback":
        return _review_payload(row)
    if row is None:
        row = NovaCastingReview(
            id=_new_id(), owner_id=organization_id, application_id=application.id,
            reviewer_id=actor_id, stage=stage, score=score, note=note, updated_at=_now(),
        )
        db.add(row)
    else:
        row.stage = stage
        row.score = score
        row.note = note
        row.updated_at = _now()
    _flush(db)
    _audit(db, actor_id=actor_id, organization_id=organization_id, action=audit_action, object_id=application.id)
    return _review_payload(row)


def _submitted_for_review(db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str):
    actor = _member(db, user_id, tenant_id, organization_id)
    if not may_review_application(actor, organization_id=organization_id):
        raise CastingAccessDenied("Application unavailable")
    application = _application_row(db, organization_id, application_id)
    if application.status != ApplicationState.SUBMITTED.value:
        raise CastingAccessDenied("Application unavailable")
    return actor, application


def save_review(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str, payload: dict,
) -> dict:
    _guard()
    _, application = _submitted_for_review(db, user_id, tenant_id, organization_id, application_id)
    stage = payload.get("stage", "New")
    score = payload.get("score", None)
    note = payload.get("note", "")
    if set(payload) - {"stage", "score", "note"}:
        raise CastingRequestRejected("Unsupported field")
    _check_review_fields(stage=stage, score=score, note=note)
    return _upsert_review(
        db, actor_id=user_id, organization_id=organization_id, application=application,
        stage=stage, score=score, note=note, audit_action="review.updated",
    )


def shortlist_application(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str, payload: dict,
) -> dict:
    _guard()
    _, application = _submitted_for_review(db, user_id, tenant_id, organization_id, application_id)
    if set(payload) - {"shortlisted"} or payload.get("shortlisted") not in (True, False):
        raise CastingRequestRejected("Invalid review")
    stage = "In review" if payload["shortlisted"] else "Closed"
    existing_note = ""
    existing_score = None
    try:
        current = db.query(NovaCastingReview).filter(
            NovaCastingReview.application_id == application.id,
            NovaCastingReview.reviewer_id == user_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if current is not None:
        existing_note = current.note
        existing_score = current.score
    return _upsert_review(
        db, actor_id=user_id, organization_id=organization_id, application=application,
        stage=stage, score=existing_score, note=existing_note, audit_action="review.updated",
    )


def propose_callback(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str, payload: dict,
) -> dict:
    _guard()
    actor, application = _submitted_for_review(db, user_id, tenant_id, organization_id, application_id)
    if set(payload) - {"proposed"} or payload.get("proposed") is not True:
        raise CastingRequestRejected("Request rejected")
    if not may_schedule_callback(
        actor, organization_id=organization_id, application_state=ApplicationState.SUBMITTED,
    ):
        raise CastingAccessDenied("Application unavailable")
    existing_note = ""
    existing_score = None
    try:
        current = db.query(NovaCastingReview).filter(
            NovaCastingReview.application_id == application.id,
            NovaCastingReview.reviewer_id == user_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if current is not None:
        existing_note = current.note
        existing_score = current.score
    body = _upsert_review(
        db, actor_id=user_id, organization_id=organization_id, application=application,
        stage="Callback", score=existing_score, note=existing_note, audit_action="callback.proposed",
    )
    body["external_delivery"] = False
    body.pop("note", None)
    return body


def read_own_review(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str, application_id: str,
) -> dict:
    _guard()
    _submitted_for_review(db, user_id, tenant_id, organization_id, application_id)
    try:
        row = db.query(NovaCastingReview).filter(
            NovaCastingReview.application_id == application_id,
            NovaCastingReview.reviewer_id == user_id,
            NovaCastingReview.owner_id == organization_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if row is None:
        raise CastingAccessDenied("Application unavailable")
    return _review_payload(row)


def register_media_metadata(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str, payload: dict,
) -> dict:
    _guard()
    _account(db, user_id, tenant_id)
    application = _application_row(db, organization_id, application_id)
    actor = applicant_from_verified_session(session_user_id=user_id)
    if actor is None or not may_upload_audition(actor, applicant_id=application.applicant_id):
        raise CastingAccessDenied("Media unavailable")
    if application.status == ApplicationState.WITHDRAWN.value:
        raise CastingAccessDenied("Media unavailable")
    if set(payload) - {"mime_type", "byte_size"}:
        raise CastingRequestRejected("Unsupported field")
    mime_type = payload.get("mime_type")
    byte_size = payload.get("byte_size")
    if mime_type not in ALLOWED_MIME_TYPES:
        raise CastingRequestRejected("Unsupported video type")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or not 0 < byte_size <= MAX_VIDEO_BYTES:
        raise CastingRequestRejected("Invalid video size")
    media_id = _new_id()
    row = NovaCastingMedia(
        id=media_id, owner_id=organization_id, application_id=application.id,
        storage_key=f"private-quarantine/{media_id}", mime_type=mime_type,
        byte_size=byte_size, status="QUARANTINED", created_at=_now(),
    )
    db.add(row)
    _flush(db)
    _audit(
        db, actor_id=user_id, organization_id=organization_id,
        action="media.quarantined", object_id=row.id,
    )
    return media_status_view({
        "id": row.id, "application_id": row.application_id, "status": row.status,
        "mime_type": row.mime_type, "byte_size": row.byte_size,
    })


def read_media_for_user(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str, media_id: str,
) -> dict:
    _guard()
    _account(db, user_id, tenant_id)
    _org(db, organization_id, tenant_id)
    application = _application_row(db, organization_id, application_id)
    campaign = _campaign_row(db, organization_id, application.campaign_id)
    try:
        media = db.query(NovaCastingMedia).filter(
            NovaCastingMedia.id == media_id,
            NovaCastingMedia.application_id == application_id,
            NovaCastingMedia.owner_id == organization_id,
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Media unavailable") from exc
    if media is None:
        raise CastingAccessDenied("Media unavailable")
    if application.applicant_id == user_id:
        actor = applicant_from_verified_session(session_user_id=user_id)
    else:
        actor = _member(db, user_id, tenant_id, organization_id)
    return read_media_metadata(
        actor=actor,
        application=_application_dict(application),
        campaign=_campaign_dict(campaign),
        media={
            "id": media.id, "application_id": media.application_id, "owner_id": media.owner_id,
            "status": media.status, "mime_type": media.mime_type, "byte_size": media.byte_size,
        },
    )


def list_audit_events(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    limit: int = 20, offset: int = 0,
) -> dict:
    _guard()
    limit, offset = _bounds(limit, offset)
    actor = _member(db, user_id, tenant_id, organization_id)
    if not may_review_application(actor, organization_id=organization_id):
        raise CastingAccessDenied("Application unavailable")
    try:
        rows = (
            db.query(NovaCastingAuditEvent)
            .filter(NovaCastingAuditEvent.organization_id == organization_id)
            .order_by(NovaCastingAuditEvent.occurred_at, NovaCastingAuditEvent.id)
            .offset(offset).limit(limit).all()
        )
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    items = [
        {
            "actor_id": row.actor_id,
            "organization_id": row.organization_id,
            "action": row.action,
            "object_id": row.object_id,
            "occurred_at": row.occurred_at,
        }
        for row in rows
    ]
    return _page(items, limit, offset)
