"""Sandbox pilot routes. Registered on the existing casting router and default-off.

No public intake, signed URL, or outbound email, SMS, or WhatsApp delivery.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.auth import UserContext, get_current_user_context

from .casting_access import CastingAccessDenied, CastingRequestRejected
from .casting_flags import casting_sandbox_writes_enabled
from .casting_pilot import SAFE_REASONS, PilotRejected

pilot_router = APIRouter()
_DISABLED = "Casting application access is not enabled"


class QuestionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    prompt: str


class RoleBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str
    requirements: str = ""
    deadline: str
    minimum_age: int = 18
    questions: list[QuestionBody] = []


class IntakeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role_id: str
    display_name: str
    contact_email: str
    video_url: str
    age_years: int
    consent_accepted: bool
    consent_version: str
    retention_days: int = 30
    answers: dict[str, str] = {}


class ReviewStageBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stage: str
    shortlisted: bool


class RubricBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    criterion: str
    score: int
    comment: str = ""


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: str
    idempotency_key: str
    application_id: str = ""
    channel: str = "email"


class SuppressionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contact_email: str
    reason: str


class ScheduleBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role_id: str
    timezone: str
    starts_at: str
    ends_at: str
    location_label: str
    document_url: str = ""


def pilot_session():
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=_DISABLED)
    from .casting_router_sandbox import casting_sandbox_session
    yield from casting_sandbox_session()


def _identity(user: UserContext) -> tuple[str, str]:
    user_id = str(user.user_id or "").strip()
    tenant_id = str(user.organization_id or "").strip()
    if not user_id or not tenant_id:
        raise HTTPException(status_code=404, detail="Application unavailable")
    return user_id, tenant_id


def _bounds(limit: str, offset: str) -> tuple[int, int]:
    try:
        parsed_limit = int(limit)
        parsed_offset = int(offset)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Request rejected")
    if parsed_limit < 1 or parsed_limit > 50 or parsed_offset < 0 or parsed_offset > 10000:
        raise HTTPException(status_code=422, detail="Request rejected")
    return parsed_limit, parsed_offset


def _parse(model, payload: dict):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request rejected")
    try:
        return model.model_validate(payload).model_dump()
    except ValidationError:
        raise HTTPException(status_code=422, detail="Request rejected")


def _call(action):
    try:
        return action()
    except PilotRejected as exc:
        detail = str(exc) if str(exc) in SAFE_REASONS else "Request rejected"
        raise HTTPException(status_code=422, detail=detail)
    except CastingRequestRejected as exc:
        detail = str(exc) if str(exc) in SAFE_REASONS else "Request rejected"
        raise HTTPException(status_code=422, detail=detail)
    except (CastingAccessDenied, SQLAlchemyError):
        raise HTTPException(status_code=404, detail="Application unavailable")


def _store():
    from . import casting_pilot_store
    return casting_pilot_store


def _providers() -> tuple[bool, bool]:
    sms = bool(str(os.getenv("NOVA_CASTING_SMS_PROVIDER") or "").strip())
    whatsapp = bool(str(os.getenv("NOVA_CASTING_WHATSAPP_PROVIDER") or "").strip())
    return sms, whatsapp


@pilot_router.post("/organizations/{organization_id}/campaigns/{campaign_id}/roles")
def create_role(organization_id: str, campaign_id: str, payload: dict = Body(...),
                user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    body = _parse(RoleBody, payload)
    return _call(lambda: _store().create_role(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        campaign_id=campaign_id, payload=body,
    ))


@pilot_router.get("/organizations/{organization_id}/campaigns/{campaign_id}/roles")
def list_roles(organization_id: str, campaign_id: str, limit: str = "20", offset: str = "0",
               user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    parsed_limit, parsed_offset = _bounds(limit, offset)
    return _call(lambda: _store().list_roles(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        campaign_id=campaign_id, limit=parsed_limit, offset=parsed_offset,
    ))


@pilot_router.post("/organizations/{organization_id}/campaigns/{campaign_id}/pilot-demo")
def seed_demo(organization_id: str, campaign_id: str, user: UserContext = Depends(get_current_user_context),
              db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    return _call(lambda: _store().seed_harborlight(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, campaign_id=campaign_id,
    ))


@pilot_router.post("/organizations/{organization_id}/applications/{application_id}/intake")
def save_intake(organization_id: str, application_id: str, payload: dict = Body(...),
                user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    body = _parse(IntakeBody, payload)
    return _call(lambda: _store().save_intake(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, payload=body,
    ))


@pilot_router.post("/organizations/{organization_id}/applications/{application_id}/intake/submit")
def submit_intake(organization_id: str, application_id: str, user: UserContext = Depends(get_current_user_context),
                  db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    return _call(lambda: _store().submit_intake(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, application_id=application_id,
    ))


@pilot_router.post("/organizations/{organization_id}/applications/{application_id}/intake/revoke")
def revoke_intake(organization_id: str, application_id: str, user: UserContext = Depends(get_current_user_context),
                  db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    return _call(lambda: _store().revoke_intake(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, application_id=application_id,
    ))


@pilot_router.post("/organizations/{organization_id}/applications/{application_id}/intake/minimize")
def minimize_intake(organization_id: str, application_id: str, user: UserContext = Depends(get_current_user_context),
                    db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    return _call(lambda: _store().minimize_intake(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, application_id=application_id,
    ))


@pilot_router.get("/organizations/{organization_id}/review-queue")
def review_queue(organization_id: str, q: str = "", status: str = "", shortlisted: str = "",
                 limit: str = "20", offset: str = "0", user: UserContext = Depends(get_current_user_context),
                 db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    parsed_limit, parsed_offset = _bounds(limit, offset)
    return _call(lambda: _store().review_queue(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        query=q[:80], status=status[:16], shortlisted=shortlisted[:5],
        limit=parsed_limit, offset=parsed_offset,
    ))


@pilot_router.post("/organizations/{organization_id}/applications/{application_id}/pilot-review")
def pilot_review(organization_id: str, application_id: str, payload: dict = Body(...),
                 user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    body = _parse(ReviewStageBody, payload)
    return _call(lambda: _store().set_review(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, payload=body,
    ))


@pilot_router.post("/organizations/{organization_id}/applications/{application_id}/rubric")
def rubric(organization_id: str, application_id: str, payload: dict = Body(...),
           user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    body = _parse(RubricBody, payload)
    return _call(lambda: _store().add_rubric(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, payload=body,
    ))


@pilot_router.post("/organizations/{organization_id}/messages")
def create_message(organization_id: str, payload: dict = Body(...),
                   user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    body = _parse(MessageBody, payload)
    sms, whatsapp = _providers()
    return _call(lambda: _store().draft_message(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, payload=body,
        sms_configured=sms, whatsapp_configured=whatsapp,
    ))


@pilot_router.post("/organizations/{organization_id}/messages/{message_id}/approve")
def approve_message(organization_id: str, message_id: str, user: UserContext = Depends(get_current_user_context),
                    db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    return _call(lambda: _store().approve_message(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, message_id=message_id,
    ))


@pilot_router.post("/organizations/{organization_id}/messages/{message_id}/retry")
def retry_message(organization_id: str, message_id: str, user: UserContext = Depends(get_current_user_context),
                  db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    return _call(lambda: _store().retry_message(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, message_id=message_id,
    ))


@pilot_router.post("/organizations/{organization_id}/suppressions")
def suppress(organization_id: str, payload: dict = Body(...),
             user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    body = _parse(SuppressionBody, payload)
    return _call(lambda: _store().suppress(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, payload=body,
    ))


@pilot_router.post("/organizations/{organization_id}/campaigns/{campaign_id}/schedule")
def save_schedule(organization_id: str, campaign_id: str, payload: dict = Body(...),
                  user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    body = _parse(ScheduleBody, payload)
    return _call(lambda: _store().save_schedule(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        campaign_id=campaign_id, payload=body,
    ))


@pilot_router.get("/organizations/{organization_id}/roles/{role_id}/call-sheet")
def call_sheet(organization_id: str, role_id: str, user: UserContext = Depends(get_current_user_context),
               db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    return _call(lambda: _store().call_sheet(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id, role_id=role_id,
    ))


@pilot_router.get("/organizations/{organization_id}/pilot-snapshot")
def pilot_snapshot(organization_id: str, campaign_id: str = "",
                   user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    if len(campaign_id) > 48:
        raise HTTPException(status_code=422, detail="Request rejected")
    return _call(lambda: _store().snapshot(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        campaign_id=campaign_id.strip(),
    ))


@pilot_router.get("/organizations/{organization_id}/pilot-export")
def export_csv(organization_id: str, include_contact: str = "false",
               user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    text = _call(lambda: _store().export_csv(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        include_contact=include_contact == "true",
    ))
    return Response(
        content=text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=casting-sandbox.csv", "Cache-Control": "private, no-store"},
    )


@pilot_router.get("/organizations/{organization_id}/pilot-audit")
def pilot_audit(organization_id: str, limit: str = "20", offset: str = "0",
                user: UserContext = Depends(get_current_user_context), db=Depends(pilot_session)):
    user_id, tenant_id = _identity(user)
    parsed_limit, parsed_offset = _bounds(limit, offset)
    return _call(lambda: _store().list_audit(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        limit=parsed_limit, offset=parsed_offset,
    ))
