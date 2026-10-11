"""Disposable Nova Casting workflows. Registered under the existing casting router.

Production and misconfigured environments cannot open a session. Public intake,
file uploads, and external delivery stay off.
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context

from .casting_access import CastingAccessDenied, CastingRequestRejected
from .casting_flags import casting_sandbox_writes_enabled

sandbox_router = APIRouter()
CASTING_SANDBOX_DISABLED_DETAIL = "Casting application access is not enabled"
_SAFE_DETAILS = frozenset({
    "Consent required",
    "Consent version required",
    "Applicant does not meet the minimum age",
    "Unsupported video type",
    "Invalid video size",
    "Invalid title",
    "Unsupported category",
    "Minimum age must be at least 18",
    "Campaign cannot be published",
    "Unsupported field",
    "Invalid review",
    "Request rejected",
    "Invalid intake",
    "Invalid campaign",
})


class CampaignBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str
    category: str
    minimum_age: int = 18
    status: str = "DRAFT"


class ApplicationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    consent_accepted: bool
    consent_version: str
    age_years: int


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stage: str = "New"
    score: int | None = None
    note: str = ""


class ShortlistBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    shortlisted: bool


class CallbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proposed: bool = True


class MediaBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mime_type: str
    byte_size: int


class CampaignRead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    title: str
    category: str
    status: str
    created_at: str
    minimum_age: int


class CampaignPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[CampaignRead]
    limit: int
    offset: int


class ApplicationRead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    campaign_id: str
    status: str
    created_at: str


class ApplicationPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[ApplicationRead]
    limit: int
    offset: int


class ReviewRead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    application_id: str
    stage: str
    score: int | None = None
    note: str = ""
    updated_at: str
    shortlisted: bool
    callback_proposed: bool
    external_delivery: bool


class CallbackRead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    application_id: str
    stage: str
    score: int | None = None
    updated_at: str
    shortlisted: bool
    callback_proposed: bool
    external_delivery: bool


class MediaRead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    application_id: str
    status: str
    mime_type: str
    byte_size: int
    playback: str


class AuditRead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    actor_id: str
    organization_id: str
    action: str
    object_id: str
    occurred_at: str


class AuditPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[AuditRead]
    limit: int
    offset: int


def casting_sandbox_session():
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    from sqlalchemy.exc import SQLAlchemyError
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Application unavailable")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _session_identity(user: UserContext) -> tuple[str, str]:
    user_id = str(user.user_id or "").strip()
    tenant_id = str(user.organization_id or "").strip()
    if not user_id or not tenant_id:
        raise HTTPException(status_code=404, detail="Application unavailable")
    return user_id, tenant_id


def _bounds(limit: str = "20", offset: str = "0") -> tuple[int, int]:
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
    from sqlalchemy.exc import SQLAlchemyError
    try:
        return action()
    except CastingRequestRejected as exc:
        detail = str(exc) if str(exc) in _SAFE_DETAILS else "Request rejected"
        raise HTTPException(status_code=422, detail=detail)
    except (CastingAccessDenied, SQLAlchemyError):
        raise HTTPException(status_code=404, detail="Application unavailable")


def _writes():
    from . import casting_db_writes
    return casting_db_writes


@sandbox_router.post("/organizations/{organization_id}/campaigns", response_model=CampaignRead)
def create_campaign(
    organization_id: str,
    payload: dict = Body(...),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    body = _parse(CampaignBody, payload)
    return _call(lambda: _writes().create_draft_campaign(
        db=db, user_id=user_id, tenant_id=tenant_id,
        organization_id=organization_id, payload=body,
    ))


@sandbox_router.patch("/organizations/{organization_id}/campaigns/{campaign_id}", response_model=CampaignRead)
def update_campaign(
    organization_id: str,
    campaign_id: str,
    payload: dict = Body(...),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    body = _parse(CampaignBody, payload)
    return _call(lambda: _writes().update_draft_campaign(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        campaign_id=campaign_id, payload=body,
    ))


@sandbox_router.get("/organizations/{organization_id}/campaigns", response_model=CampaignPage)
def list_campaigns(
    organization_id: str,
    limit: str = "20",
    offset: str = "0",
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    parsed_limit, parsed_offset = _bounds(limit, offset)
    return _call(lambda: _writes().list_draft_campaigns(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        limit=parsed_limit, offset=parsed_offset,
    ))


@sandbox_router.post(
    "/organizations/{organization_id}/campaigns/{campaign_id}/applications",
    response_model=ApplicationRead,
)
def save_application(
    organization_id: str,
    campaign_id: str,
    payload: dict = Body(...),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    body = _parse(ApplicationBody, payload)
    return _call(lambda: _writes().save_test_application(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        campaign_id=campaign_id, payload=body,
    ))


@sandbox_router.get("/organizations/{organization_id}/applications", response_model=ApplicationPage)
def list_applications(
    organization_id: str,
    limit: str = "20",
    offset: str = "0",
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    parsed_limit, parsed_offset = _bounds(limit, offset)
    return _call(lambda: _writes().list_applications(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        limit=parsed_limit, offset=parsed_offset,
    ))


@sandbox_router.post(
    "/organizations/{organization_id}/applications/{application_id}/submit",
    response_model=ApplicationRead,
)
def submit_application(
    organization_id: str,
    application_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    return _call(lambda: _writes().submit_test_application(
        db=db, user_id=user_id, tenant_id=tenant_id,
        organization_id=organization_id, application_id=application_id,
    ))


@sandbox_router.post(
    "/organizations/{organization_id}/applications/{application_id}/withdraw",
    response_model=ApplicationRead,
)
def withdraw_application(
    organization_id: str,
    application_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    return _call(lambda: _writes().withdraw_test_application(
        db=db, user_id=user_id, tenant_id=tenant_id,
        organization_id=organization_id, application_id=application_id,
    ))


@sandbox_router.put(
    "/organizations/{organization_id}/applications/{application_id}/review",
    response_model=ReviewRead,
)
def save_review(
    organization_id: str,
    application_id: str,
    payload: dict = Body(...),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    body = _parse(ReviewBody, payload)
    result = _call(lambda: _writes().save_review(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, payload=body,
    ))
    result.pop("storage_key", None)
    return result


@sandbox_router.post(
    "/organizations/{organization_id}/applications/{application_id}/shortlist",
    response_model=ReviewRead,
)
def shortlist_application(
    organization_id: str,
    application_id: str,
    payload: dict = Body(...),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    body = _parse(ShortlistBody, payload)
    return _call(lambda: _writes().shortlist_application(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, payload=body,
    ))


@sandbox_router.post(
    "/organizations/{organization_id}/applications/{application_id}/callback",
    response_model=CallbackRead,
)
def propose_callback(
    organization_id: str,
    application_id: str,
    payload: dict | None = Body(default=None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    body = _parse(CallbackBody, payload or {"proposed": True})
    result = _call(lambda: _writes().propose_callback(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, payload=body,
    ))
    result["external_delivery"] = False
    result.pop("note", None)
    result.pop("storage_key", None)
    result.pop("signed_url", None)
    return result


@sandbox_router.get(
    "/organizations/{organization_id}/applications/{application_id}/review",
    response_model=ReviewRead,
)
def read_review(
    organization_id: str,
    application_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    return _call(lambda: _writes().read_own_review(
        db=db, user_id=user_id, tenant_id=tenant_id,
        organization_id=organization_id, application_id=application_id,
    ))


@sandbox_router.post(
    "/organizations/{organization_id}/applications/{application_id}/media",
    response_model=MediaRead,
)
def register_media(
    organization_id: str,
    application_id: str,
    payload: dict = Body(...),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    body = _parse(MediaBody, payload)
    result = _call(lambda: _writes().register_media_metadata(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, payload=body,
    ))
    result["playback"] = "unavailable"
    result.pop("storage_key", None)
    result.pop("signed_url", None)
    return result


@sandbox_router.get(
    "/organizations/{organization_id}/applications/{application_id}/media/{media_id}",
    response_model=MediaRead,
)
def read_media(
    organization_id: str,
    application_id: str,
    media_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    result = _call(lambda: _writes().read_media_for_user(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        application_id=application_id, media_id=media_id,
    ))
    result["playback"] = "unavailable"
    result.pop("storage_key", None)
    result.pop("signed_url", None)
    return result


@sandbox_router.get("/organizations/{organization_id}/audit", response_model=AuditPage)
def list_audit(
    organization_id: str,
    limit: str = "20",
    offset: str = "0",
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_sandbox_session),
):
    if not casting_sandbox_writes_enabled():
        raise HTTPException(status_code=503, detail=CASTING_SANDBOX_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    parsed_limit, parsed_offset = _bounds(limit, offset)
    return _call(lambda: _writes().list_audit_events(
        db=db, user_id=user_id, tenant_id=tenant_id, organization_id=organization_id,
        limit=parsed_limit, offset=parsed_offset,
    ))
