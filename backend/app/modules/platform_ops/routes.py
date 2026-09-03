"""HTTP routes for driver onboarding (platform_ops)."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.auth import _bearer, extract_access_token, _jwt_verify, get_current_user, require_any_role
from app.db.models import User as UserModel
from app.db.session import get_db
from app.modules.platform_ops.models import PlatformDriverOnboardingDocument, ensure_platform_ops_schema
from app.modules.platform_ops.onboarding import activation as activation_service
from app.modules.platform_ops.onboarding import service as onboarding_service
from app.modules.platform_ops.onboarding import work_setup as work_setup_service
from app.modules.platform_ops.permissions import (
    can_activate,
    can_approve,
    can_review,
    can_view_compliance,
    can_view_full_identity,
    is_driver_role,
    user_role,
)
from app.modules.platform_ops.readiness import compute_readiness_summary
from app.modules.platform_ops.secure_storage import SecureStorageNotConfigured
from app.modules.platform_ops.storage import get_document_storage
from app.modules.platform_ops.schemas import (
    ActivationResponse,
    ApplicantAgreementSignRequest,
    ApplicantPayoutStartRequest,
    ApplicantTokenReissueResponse,
    DocumentReviewRequest,
    DocumentStatusOnlyRequest,
    DriverApplicationAssignReviewerRequest,
    DriverApplicationCreateResponse,
    DriverApplicationDecisionRequest,
    DriverApplicationDetailResponse,
    DriverApplicationDraftRequest,
    DriverApplicationInternalNoteRequest,
    DriverApplicationListItemResponse,
    DriverApplicationStatusTransitionRequest,
    DriverApplicationSubmitRequest,
    ReadinessSummaryResponse,
    WorkSetupStatusResponse,
)

logger = logging.getLogger("amicor.platform_ops.routes")

router = APIRouter(prefix="/api/platform-ops/driver-onboarding", tags=["platform-ops-driver-onboarding"])

require_onboarding_reviewer = require_any_role(
    "admin",
    "super_admin_support",
    "supervisor",
    "dispatcher",
    "driver_support",
    "compliance_officer",
)

require_onboarding_admin = require_any_role("admin", "super_admin_support", "supervisor")
require_onboarding_compliance = require_any_role(
    "admin",
    "super_admin_support",
    "supervisor",
    "compliance_officer",
)


def _optional_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    token = extract_access_token(creds, request)
    if not token:
        return None
    payload = _jwt_verify(token)
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user or not user.is_active:
        return None
    return user


def _include_full_identity(user) -> bool:
    return bool(user and can_view_full_identity(user))


def _audit_identity_reveal(db, *, application, user) -> None:
    if user is None or application is None:
        return
    onboarding_service._record_audit(
        db,
        application=application,
        event_type="sensitive_identity_revealed",
        actor_user_id=str(user.id),
        actor_role=user_role(user),
        reason="Full driver-license number returned to compliance-authorized reviewer",
        metadata={"fields": ["drivers_license_number"], "masked": False},
    )


def _detail_for_user(db, application, user):
    include_full = _include_full_identity(user)
    if include_full:
        _audit_identity_reveal(db, application=application, user=user)
        db.commit()
    return onboarding_service.application_to_detail(db, application, include_full_license=include_full)


def _resolve_org_id(explicit_org_id: str | None, user) -> str:
    if explicit_org_id:
        return explicit_org_id
    org_id = getattr(user, "organization_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail="organization_id is required.")
    return str(org_id)


def _parse_service_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if message.startswith("{"):
        try:
            payload = json.loads(message)
            if isinstance(payload, dict) and payload.get("errors"):
                return HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=payload,
                )
        except json.JSONDecodeError:
            pass
    if "COMPLIANCE_STORAGE_BLOCKED" in message:
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message)
    if "not allowed" in message.lower() or "cannot" in message.lower():
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    if "not found" in message.lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _authorize_application_access(
    *,
    application,
    user,
    applicant_token: str | None,
) -> None:
    if user and can_review(user):
        return
    if onboarding_service.verify_applicant_token(application, applicant_token):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this application.")


ensure_platform_ops_schema()


@router.get("/document-categories")
def get_document_categories() -> list[dict[str, Any]]:
    return [item.model_dump() for item in onboarding_service.list_document_categories()]


@router.get("/storage-status")
def get_secure_storage_status(user=Depends(require_onboarding_compliance)):  # type: ignore
    from app.modules.platform_ops.secure_storage import secure_document_storage_readiness

    _ = user
    return secure_document_storage_readiness()


@router.post("/applications", response_model=DriverApplicationCreateResponse)
def create_application(
    payload: DriverApplicationDraftRequest,
    db: Session = Depends(get_db),
    user=Depends(_optional_current_user),  # type: ignore
) -> DriverApplicationCreateResponse:
    organization_id = _resolve_org_id(payload.organization_id, user)
    try:
        application, token = onboarding_service.create_draft_application(
            db, organization_id=organization_id, payload=payload
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    detail = onboarding_service.application_to_detail(db, application, include_full_license=True)
    return DriverApplicationCreateResponse(application=detail, applicant_access_token=token)


@router.get("/applications", response_model=list[DriverApplicationListItemResponse])
def list_applications(
    organization_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_reviewer),  # type: ignore
) -> list[DriverApplicationListItemResponse]:
    org_id = _resolve_org_id(organization_id, user)
    rows = onboarding_service.list_applications_for_org(db, organization_id=org_id, status=status_filter)
    return [onboarding_service.application_to_list_item(db, row) for row in rows]


@router.get("/applications/{application_id}", response_model=DriverApplicationDetailResponse)
def get_application(
    application_id: str,
    db: Session = Depends(get_db),
    user=Depends(_optional_current_user),  # type: ignore
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> DriverApplicationDetailResponse:
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    _authorize_application_access(application=application, user=user, applicant_token=x_applicant_token)
    if onboarding_service.verify_applicant_token(application, x_applicant_token):
        # Applicant token holders receive their own saved fields so the portal can resume
        # without writing masked values back over real data.
        return onboarding_service.application_to_detail(db, application, include_full_license=True)
    return _detail_for_user(db, application, user)


@router.post(
    "/applications/{application_id}/applicant-token/reissue",
    response_model=ApplicantTokenReissueResponse,
)
def reissue_applicant_token(
    application_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_reviewer),  # type: ignore
) -> ApplicantTokenReissueResponse:
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    try:
        token = onboarding_service.reissue_applicant_access_token(
            db,
            application=application,
            actor_user_id=str(user.id),
            actor_role=user_role(user),
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    apply_path = (
        "/platform-ops/driver-apply"
        f"?organization_id={application.organization_id}"
        f"&application_id={application.id}"
        f"&token={token}"
    )
    logger.info(
        "applicant_access_reissued application_id=%s actor_user_id=%s",
        application.id,
        user.id,
    )
    return ApplicantTokenReissueResponse(
        application_id=str(application.id),
        organization_id=str(application.organization_id),
        status=application.status,
        applicant_access_token=token,
        apply_path=apply_path,
        previous_token_revoked=True,
    )


@router.get("/applications/{application_id}/applicant-status")
def get_applicant_status(
    application_id: str,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    """Simple applicant-facing status — no internal adapter/status jargon."""
    from app.modules.approval_engine.driver_messages import applicant_facing_status
    from app.modules.approval_engine.models import ApprovalCase

    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not onboarding_service.verify_applicant_token(application, x_applicant_token):
        raise HTTPException(status_code=403, detail="Applicant token required.")
    case = (
        db.query(ApprovalCase)
        .filter(ApprovalCase.platform_ops_application_id == application.id)
        .order_by(ApprovalCase.created_at.desc())
        .first()
    )
    return applicant_facing_status(case, application_status=application.status)


@router.get("/applications/{application_id}/progress")
def get_applicant_progress(
    application_id: str,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    """Driver-facing onboarding progress. No admin-only notes or full license numbers."""
    from app.modules.approval_engine.compliance_summary import (
        build_compliance_summary,
        resolve_case_and_application,
    )
    from app.modules.approval_engine.models import ApprovalCase

    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not onboarding_service.verify_applicant_token(application, x_applicant_token):
        raise HTTPException(status_code=403, detail="Applicant token required.")
    case = (
        db.query(ApprovalCase)
        .filter(ApprovalCase.platform_ops_application_id == application.id)
        .order_by(ApprovalCase.updated_at.desc())
        .first()
    )
    case, application = resolve_case_and_application(db, case=case, application=application)
    summary = build_compliance_summary(db, application=application, case=case)
    public_items = []
    for item in summary.get("items") or []:
        public_item = dict(item)
        public_item.pop("notes", None)
        public_items.append(public_item)
    summary["items"] = public_items
    return {
        "application_id": application.id,
        "application_status": application.status,
        "progress_path": "/platform-ops/driver-onboarding",
        "apply_path": "/platform-ops/driver-apply",
        **summary,
    }


def _require_applicant_draft(
    db: Session,
    application_id: str,
    x_applicant_token: str | None,
) -> Any:
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not onboarding_service.verify_applicant_token(application, x_applicant_token):
        raise HTTPException(status_code=403, detail="Applicant token required.")
    return application


@router.get("/applications/{application_id}/work-setup", response_model=WorkSetupStatusResponse)
def get_work_setup(
    application_id: str,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    application = _require_applicant_draft(db, application_id, x_applicant_token)
    return work_setup_service.serialize_work_setup(application)


@router.get("/applications/{application_id}/work-setup/agreement")
def get_work_setup_agreement(
    application_id: str,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    application = _require_applicant_draft(db, application_id, x_applicant_token)
    packet = work_setup_service.agreement_packet()
    status = work_setup_service.serialize_work_setup(application)
    return {**packet, "agreement": status["agreement"]}


@router.post("/applications/{application_id}/work-setup/agreement/sign", response_model=WorkSetupStatusResponse)
def sign_work_setup_agreement(
    application_id: str,
    payload: ApplicantAgreementSignRequest,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    application = _require_applicant_draft(db, application_id, x_applicant_token)
    try:
        return work_setup_service.sign_independent_contractor_agreement(
            db,
            application=application,
            typed_signature=payload.typed_signature,
            accepted=payload.accepted,
            agreement_version=payload.agreement_version,
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc


@router.post("/applications/{application_id}/work-setup/w9", response_model=WorkSetupStatusResponse)
async def complete_work_setup_w9(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    application = _require_applicant_draft(db, application_id, x_applicant_token)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid tax information payload.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid tax information payload.")
    try:
        return work_setup_service.complete_electronic_w9(
            db,
            application=application,
            payload=payload,
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc


@router.post("/applications/{application_id}/work-setup/payout/start", response_model=WorkSetupStatusResponse)
def start_work_setup_payout(
    application_id: str,
    payload: ApplicantPayoutStartRequest | None = None,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    application = _require_applicant_draft(db, application_id, x_applicant_token)
    body = payload or ApplicantPayoutStartRequest()
    try:
        return work_setup_service.start_payout_onboarding(
            db,
            application=application,
            return_url=body.return_url,
            refresh_url=body.refresh_url,
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc


@router.post("/applications/{application_id}/work-setup/payout/refresh", response_model=WorkSetupStatusResponse)
def refresh_work_setup_payout(
    application_id: str,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> dict[str, Any]:
    application = _require_applicant_draft(db, application_id, x_applicant_token)
    try:
        return work_setup_service.refresh_payout_status(db, application=application)
    except ValueError as exc:
        raise _parse_service_error(exc) from exc


@router.put("/applications/{application_id}", response_model=DriverApplicationDetailResponse)
def update_application(
    application_id: str,
    payload: DriverApplicationDraftRequest,
    db: Session = Depends(get_db),
    user=Depends(_optional_current_user),  # type: ignore
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> DriverApplicationDetailResponse:
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if user and is_driver_role(user):
        raise HTTPException(status_code=403, detail="Drivers cannot modify onboarding applications.")
    if not onboarding_service.verify_applicant_token(application, x_applicant_token) and not (user and can_review(user)):
        raise HTTPException(status_code=403, detail="Not authorized to update this application.")
    try:
        updated = onboarding_service.update_draft_application(
            db,
            application=application,
            payload=payload,
            actor_user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    if onboarding_service.verify_applicant_token(updated, x_applicant_token):
        return onboarding_service.application_to_detail(db, updated, include_full_license=True)
    return _detail_for_user(db, updated, user)


@router.post("/applications/{application_id}/submit", response_model=DriverApplicationDetailResponse)
def submit_application(
    application_id: str,
    payload: DriverApplicationSubmitRequest,
    db: Session = Depends(get_db),
    user=Depends(_optional_current_user),  # type: ignore
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> DriverApplicationDetailResponse:
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not onboarding_service.verify_applicant_token(application, x_applicant_token):
        raise HTTPException(status_code=403, detail="Applicant token required to submit.")
    try:
        updated = onboarding_service.submit_application(
            db,
            application=application,
            actor_user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    detail = onboarding_service.application_to_detail(db, updated, include_full_license=True)
    if payload.simple_confirmation_message:
        from app.modules.approval_engine.driver_messages import render_template

        detail.applicant_message = render_template("application_submitted")
        detail.applicant_follow_up_messages = [detail.applicant_message]
    return detail


@router.post("/applications/{application_id}/documents")
async def upload_document(
    application_id: str,
    category: str = Query(...),
    expires_at: str | None = Query(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
    user=Depends(_optional_current_user),  # type: ignore
):
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not onboarding_service.verify_applicant_token(application, x_applicant_token) and not (user and can_review(user)):
        raise HTTPException(status_code=403, detail="Not authorized to upload documents.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    parsed_expires = None
    if expires_at:
        from datetime import date

        parsed_expires = date.fromisoformat(expires_at)
    try:
        document = onboarding_service.upload_document(
            db,
            application=application,
            category=category,
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            file_bytes=content,
            expires_at=parsed_expires,
        )
    except SecureStorageNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    return onboarding_service.document_to_response(document).model_dump()


@router.get("/applications/{application_id}/documents/{document_id}/download")
def download_document(
    application_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
    user=Depends(_optional_current_user),  # type: ignore
):
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    applicant_ok = onboarding_service.verify_applicant_token(application, x_applicant_token)
    staff_ok = bool(user and can_view_full_identity(user))
    if not applicant_ok and not staff_ok:
        onboarding_service._record_audit(
            db,
            application=application,
            event_type="document_inspect_denied",
            actor_user_id=str(user.id) if user is not None else None,
            actor_role=user_role(user) if user is not None else "anonymous",
            reason="Unauthorized document retrieval attempt",
            metadata={"document_id": document_id, "result": "denied"},
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="Document inspect requires owner/compliance role or the applicant token.",
        )
    document = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(
            PlatformDriverOnboardingDocument.id == document_id,
            PlatformDriverOnboardingDocument.application_id == application_id,
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not document.storage_ref:
        raise HTTPException(status_code=404, detail="Document has no stored file.")
    onboarding_service._record_audit(
        db,
        application=application,
        event_type="document_inspected",
        actor_user_id=str(user.id) if user is not None else None,
        actor_role=user_role(user) if user is not None else "applicant",
        reason="Authorized document retrieval",
        metadata={
            "document_id": document_id,
            "category": document.category,
            "result": "allowed",
            "actor": "staff" if staff_ok else "applicant",
        },
    )
    db.commit()
    logger.info(
        "document_download application_id=%s document_id=%s category=%s result=allowed",
        application_id,
        document_id,
        document.category,
    )
    try:
        storage = get_document_storage()
        payload, _ = storage.retrieve(storage_ref=document.storage_ref)
    except SecureStorageNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid storage reference.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Stored document file not found.") from exc
    media_type = document.content_type or "application/octet-stream"
    filename = document.original_filename or "document.bin"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=payload, media_type=media_type, headers=headers)


@router.post("/applications/{application_id}/documents/status-only")
def upsert_status_only_document(
    application_id: str,
    payload: DocumentStatusOnlyRequest,
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
    user=Depends(_optional_current_user),  # type: ignore
):
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not onboarding_service.verify_applicant_token(application, x_applicant_token) and not (user and can_view_compliance(user)):
        raise HTTPException(status_code=403, detail="Not authorized.")
    try:
        document = onboarding_service.upsert_status_only_document(
            db,
            application=application,
            category=payload.category,
            status_only_value=payload.status_only_value,
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    return onboarding_service.document_to_response(document).model_dump()


@router.patch("/applications/{application_id}/documents/{document_id}/review")
def review_document(
    application_id: str,
    document_id: str,
    payload: DocumentReviewRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_compliance),  # type: ignore
):
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    document = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(
            PlatformDriverOnboardingDocument.id == document_id,
            PlatformDriverOnboardingDocument.application_id == application_id,
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    updated = onboarding_service.review_document(
        db,
        application=application,
        document=document,
        review_status=payload.review_status,
        review_reason=payload.review_reason,
        reviewer_user_id=str(user.id),
        expires_at=payload.expires_at,
    )
    return onboarding_service.document_to_response(updated).model_dump()


@router.post("/applications/{application_id}/status", response_model=DriverApplicationDetailResponse)
def transition_status(
    application_id: str,
    payload: DriverApplicationStatusTransitionRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_reviewer),  # type: ignore
) -> DriverApplicationDetailResponse:
    if payload.to_status in {"approved", "activated", "rejected", "suspended"} and not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required for this status change.")
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    try:
        updated = onboarding_service.transition_application_status(
            db,
            application=application,
            to_status=payload.to_status,
            reason=payload.reason,
            actor_user_id=str(user.id),
            actor_role=user_role(user),
            assigned_reviewer_id=payload.assigned_reviewer_id,
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    return _detail_for_user(db, updated, user)


@router.post("/applications/{application_id}/approve", response_model=DriverApplicationDetailResponse)
def approve_application(
    application_id: str,
    payload: DriverApplicationDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_admin),  # type: ignore
) -> DriverApplicationDetailResponse:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to approve applicant.")
    if not can_approve(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions to approve.")
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if application.email and getattr(user, "email", None) and application.email.lower() == str(user.email).lower():
        raise HTTPException(status_code=403, detail="Applicants cannot approve their own application.")
    try:
        updated = onboarding_service.approve_application(
            db,
            application=application,
            actor_user_id=str(user.id),
            actor_role=user_role(user),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    return _detail_for_user(db, updated, user)


@router.post("/applications/{application_id}/reject", response_model=DriverApplicationDetailResponse)
def reject_application(
    application_id: str,
    payload: DriverApplicationDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_admin),  # type: ignore
) -> DriverApplicationDetailResponse:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to reject applicant.")
    if not payload.reason:
        raise HTTPException(status_code=400, detail="Rejection reason is required.")
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    updated = onboarding_service.reject_application(
        db,
        application=application,
        actor_user_id=str(user.id),
        actor_role=user_role(user),
        reason=payload.reason,
    )
    return _detail_for_user(db, updated, user)


@router.post("/applications/{application_id}/suspend", response_model=DriverApplicationDetailResponse)
def suspend_application(
    application_id: str,
    payload: DriverApplicationDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_admin),  # type: ignore
) -> DriverApplicationDetailResponse:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to suspend applicant.")
    if not payload.reason:
        raise HTTPException(status_code=400, detail="Suspension reason is required.")
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    updated = onboarding_service.suspend_application(
        db,
        application=application,
        actor_user_id=str(user.id),
        actor_role=user_role(user),
        reason=payload.reason,
    )
    return _detail_for_user(db, updated, user)


@router.post("/applications/{application_id}/activate", response_model=ActivationResponse)
def activate_application(
    application_id: str,
    payload: DriverApplicationDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_admin),  # type: ignore
) -> ActivationResponse:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to activate driver.")
    if not can_activate(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions to activate.")
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    try:
        driver, idempotent = activation_service.activate_application(
            db,
            application=application,
            actor_user_id=str(user.id),
            actor_role=user_role(user),
        )
    except ValueError as exc:
        raise _parse_service_error(exc) from exc
    refreshed = onboarding_service.get_application_by_id(db, application_id)
    assert refreshed is not None
    readiness = ReadinessSummaryResponse(**compute_readiness_summary(db, refreshed))
    return ActivationResponse(
        application_id=application_id,
        driver_id=driver.id,
        driver_status=str(getattr(driver, "status", "offline")),
        idempotent=idempotent,
        readiness=readiness,
    )


@router.post("/applications/{application_id}/notes")
def add_internal_note(
    application_id: str,
    payload: DriverApplicationInternalNoteRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_reviewer),  # type: ignore
):
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    note = onboarding_service.add_internal_note(
        db,
        application=application,
        author_user_id=str(user.id),
        note_text=payload.note_text,
        category=payload.category,
    )
    return {
        "id": note.id,
        "note_text": note.note_text,
        "category": getattr(note, "category", None),
        "author_user_id": note.author_user_id,
        "created_at": note.created_at,
    }


@router.get("/applications/{application_id}/notes")
def list_internal_notes(
    application_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_reviewer),  # type: ignore
):
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    from app.modules.approval_engine.phase2b import list_internal_notes as _list_notes

    return _list_notes(db, application)


@router.post("/applications/{application_id}/assign-reviewer", response_model=DriverApplicationDetailResponse)
def assign_reviewer(
    application_id: str,
    payload: DriverApplicationAssignReviewerRequest,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_reviewer),  # type: ignore
) -> DriverApplicationDetailResponse:
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    application.assigned_reviewer_id = payload.assigned_reviewer_id
    onboarding_service._record_audit(
        db,
        application=application,
        event_type="reviewer_assigned",
        actor_user_id=str(user.id),
        actor_role=user_role(user),
        metadata={"assigned_reviewer_id": payload.assigned_reviewer_id},
    )
    db.commit()
    db.refresh(application)
    return _detail_for_user(db, application, user)


@router.get("/applications/{application_id}/readiness", response_model=ReadinessSummaryResponse)
def get_readiness(
    application_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_onboarding_reviewer),  # type: ignore
) -> ReadinessSummaryResponse:
    application = onboarding_service.get_application_by_id(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return ReadinessSummaryResponse(**compute_readiness_summary(db, application))
