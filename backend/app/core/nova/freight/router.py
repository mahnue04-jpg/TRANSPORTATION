"""Nova freight APIs. Separate from /api/health-isf and Delivery checkout."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_SUPERVISOR,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.freight.schemas import (
    NovaFreightCarrierCreate,
    NovaFreightCarrierOut,
    NovaFreightDispatchShipmentOut,
    NovaFreightOfferCreate,
    NovaFreightOfferOut,
    NovaFreightProofCreate,
    NovaFreightProofOut,
    NovaFreightShipmentCreate,
    NovaFreightShipmentEventOut,
    NovaFreightShipmentOut,
    NovaFreightShipmentUpdate,
    NovaFreightStatusUpdate,
)
from app.core.nova.freight.service import (
    NovaFreightError,
    accept_offer,
    cancel_offer,
    carriers_for_user,
    create_carrier,
    create_offers,
    create_proof,
    create_shipment,
    decline_offer,
    delete_proof,
    get_proof,
    get_shipment,
    list_carrier_active_shipments,
    list_carriers,
    list_dispatch_shipments,
    list_proofs,
    list_shipment_events,
    list_shipment_offers,
    list_shipments,
    list_visible_offers,
    proof_file_path,
    transition_shipment_status,
    update_shipment,
)
from app.core.nova.service import NovaCoreService
from app.db.session import get_db

require_freight_shipper = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_RIDER,
    ROLE_PROVIDER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
)
require_freight_dispatch = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
)
require_freight_offer_actor = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_DRIVER,
)
require_freight_viewer = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_RIDER,
    ROLE_PROVIDER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_DRIVER,
)

router = APIRouter(prefix="/api/nova/freight", tags=["nova-freight"])

DISPATCH_ROLES = {
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
}


def _org_id(user: UserContext) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, None)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _raise(exc: NovaFreightError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _carrier_scope(db, user: UserContext, dispatcher_view: bool) -> list[str] | None:
    if dispatcher_view:
        return None
    mine = carriers_for_user(db, organization_id=_org_id(user), user_id=user.user_id)
    return [row.carrier_id for row in mine]


def _assert_viewer_access(db, user: UserContext, shipment) -> None:
    if user.role in DISPATCH_ROLES or user.role in {ROLE_RIDER, ROLE_PROVIDER}:
        return
    allowed = _carrier_scope(db, user, False) or []
    if shipment.assigned_carrier_id and shipment.assigned_carrier_id in allowed:
        return
    raise HTTPException(status_code=403, detail="Only the assigned carrier can view this shipment")


@router.post("/shipments", response_model=NovaFreightShipmentOut, status_code=201, dependencies=[Depends(require_freight_shipper)])
def post_shipment(
    payload: NovaFreightShipmentCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return create_shipment(
            db,
            payload,
            organization_id=_org_id(user),
            user_id=user.user_id,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get("/shipments", response_model=list[NovaFreightShipmentOut], dependencies=[Depends(require_freight_shipper)])
def get_shipments(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return list_shipments(db, organization_id=_org_id(user))


@router.get("/shipments/{shipment_id}", response_model=NovaFreightShipmentOut, dependencies=[Depends(require_freight_viewer)])
def get_one_shipment(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        return shipment
    except NovaFreightError as exc:
        _raise(exc)


@router.patch("/shipments/{shipment_id}", response_model=NovaFreightShipmentOut, dependencies=[Depends(require_freight_shipper)])
def patch_shipment(
    shipment_id: str,
    payload: NovaFreightShipmentUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return update_shipment(
            db,
            shipment_id,
            payload,
            organization_id=_org_id(user),
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/dispatch/shipments",
    response_model=list[NovaFreightDispatchShipmentOut],
    dependencies=[Depends(require_freight_dispatch)],
)
def get_dispatch_board(
    status: str | None = Query(None),
    equipment_type: str | None = Query(None),
    pickup: str | None = Query(None),
    destination: str | None = Query(None),
    window_from: datetime | None = Query(None),
    window_to: datetime | None = Query(None),
    unassigned_only: bool = Query(False),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    rows = list_dispatch_shipments(
        db,
        organization_id=_org_id(user),
        status=status,
        equipment_type=equipment_type,
        pickup=pickup,
        destination=destination,
        window_from=window_from,
        window_to=window_to,
        unassigned_only=unassigned_only,
    )
    out: list[NovaFreightDispatchShipmentOut] = []
    for shipment, carrier_name, pending in rows:
        item = NovaFreightDispatchShipmentOut.model_validate(shipment)
        item.assigned_carrier_name = carrier_name or None
        item.pending_offer_count = pending
        out.append(item)
    return out


@router.post("/carriers", response_model=NovaFreightCarrierOut, status_code=201, dependencies=[Depends(require_freight_dispatch)])
def post_carrier(
    payload: NovaFreightCarrierCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return create_carrier(db, payload, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get("/carriers", response_model=list[NovaFreightCarrierOut], dependencies=[Depends(require_freight_dispatch)])
def get_carriers(
    equipment_type: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return list_carriers(db, organization_id=_org_id(user), equipment_type=equipment_type)


@router.post(
    "/shipments/{shipment_id}/offers",
    response_model=list[NovaFreightOfferOut],
    status_code=201,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_shipment_offers(
    shipment_id: str,
    payload: NovaFreightOfferCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return create_offers(
            db,
            shipment_id,
            payload,
            organization_id=_org_id(user),
            user_id=user.user_id,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/offers",
    response_model=list[NovaFreightOfferOut],
    dependencies=[Depends(require_freight_dispatch)],
)
def get_one_shipment_offers(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return list_shipment_offers(db, shipment_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get("/offers", response_model=list[NovaFreightOfferOut], dependencies=[Depends(require_freight_offer_actor)])
def get_offers(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return list_visible_offers(
        db,
        organization_id=_org_id(user),
        user_id=user.user_id,
        dispatcher_view=user.role in DISPATCH_ROLES,
    )


@router.post(
    "/offers/{offer_id}/accept",
    response_model=NovaFreightOfferOut,
    dependencies=[Depends(require_freight_offer_actor)],
)
def post_accept_offer(
    offer_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return accept_offer(
            db,
            offer_id,
            organization_id=_org_id(user),
            allowed_carrier_ids=_carrier_scope(db, user, user.role in DISPATCH_ROLES),
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/offers/{offer_id}/decline",
    response_model=NovaFreightOfferOut,
    dependencies=[Depends(require_freight_offer_actor)],
)
def post_decline_offer(
    offer_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return decline_offer(
            db,
            offer_id,
            organization_id=_org_id(user),
            allowed_carrier_ids=_carrier_scope(db, user, user.role in DISPATCH_ROLES),
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/offers/{offer_id}/cancel",
    response_model=NovaFreightOfferOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_cancel_offer(
    offer_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return cancel_offer(db, offer_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/carrier/shipments",
    response_model=list[NovaFreightShipmentOut],
    dependencies=[Depends(require_freight_offer_actor)],
)
def get_carrier_active_shipments(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    dispatcher_view = user.role in DISPATCH_ROLES
    if dispatcher_view:
        return list_carrier_active_shipments(
            db,
            organization_id=_org_id(user),
            carrier_ids=[
                row.carrier_id for row in list_carriers(db, organization_id=_org_id(user), active_only=True)
            ],
        )
    return list_carrier_active_shipments(
        db,
        organization_id=_org_id(user),
        carrier_ids=_carrier_scope(db, user, False) or [],
    )


@router.get(
    "/shipments/{shipment_id}/events",
    response_model=list[NovaFreightShipmentEventOut],
    dependencies=[Depends(require_freight_viewer)],
)
def get_shipment_events(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        return list_shipment_events(db, shipment_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/status",
    response_model=NovaFreightShipmentOut,
    dependencies=[Depends(require_freight_offer_actor)],
)
def post_shipment_status(
    shipment_id: str,
    payload: NovaFreightStatusUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return transition_shipment_status(
            db,
            shipment_id,
            payload,
            organization_id=_org_id(user),
            actor_user_id=user.user_id,
            actor_role=user.role,
            allowed_carrier_ids=_carrier_scope(db, user, user.role in DISPATCH_ROLES),
            dispatcher_view=user.role in DISPATCH_ROLES,
        )
    except NovaFreightError as exc:
        _raise(exc)


def _create_proof_for_user(
    db,
    shipment_id: str,
    payload: NovaFreightProofCreate,
    user: UserContext,
    file_bytes: bytes | None = None,
):
    return create_proof(
        db,
        shipment_id,
        payload,
        organization_id=_org_id(user),
        actor_user_id=user.user_id,
        actor_role=user.role,
        allowed_carrier_ids=_carrier_scope(db, user, user.role in DISPATCH_ROLES),
        dispatcher_view=user.role in DISPATCH_ROLES,
        file_bytes=file_bytes,
    )


@router.post(
    "/shipments/{shipment_id}/proofs",
    response_model=NovaFreightProofOut,
    status_code=201,
    dependencies=[Depends(require_freight_offer_actor)],
)
def post_shipment_proof(
    shipment_id: str,
    payload: NovaFreightProofCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return _create_proof_for_user(db, shipment_id, payload, user)
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/proofs/upload",
    response_model=NovaFreightProofOut,
    status_code=201,
    dependencies=[Depends(require_freight_offer_actor)],
)
async def upload_shipment_proof(
    shipment_id: str,
    proof_type: str = Form(...),
    document_ref: str | None = Form(None),
    notes: str | None = Form(None),
    signer_name: str | None = Form(None),
    signer_role: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        file_bytes = await file.read() if file is not None else None
        payload = NovaFreightProofCreate(
            proof_type=proof_type,
            document_ref=document_ref,
            original_filename=file.filename if file is not None else None,
            content_type=file.content_type if file is not None else None,
            notes=notes,
            signer_name=signer_name,
            signer_role=signer_role,
        )
        return _create_proof_for_user(db, shipment_id, payload, user, file_bytes=file_bytes)
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/proofs",
    response_model=list[NovaFreightProofOut],
    dependencies=[Depends(require_freight_viewer)],
)
def get_shipment_proofs(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        return list_proofs(db, shipment_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/proofs/{proof_id}",
    response_model=NovaFreightProofOut,
    dependencies=[Depends(require_freight_viewer)],
)
def get_one_shipment_proof(
    shipment_id: str,
    proof_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        return get_proof(db, shipment_id, proof_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/proofs/{proof_id}/file",
    dependencies=[Depends(require_freight_viewer)],
)
def get_shipment_proof_file(
    shipment_id: str,
    proof_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        proof = get_proof(db, shipment_id, proof_id, organization_id=_org_id(user))
        stored = proof_file_path(proof.organization_id, proof.document_ref)
        if stored is None:
            raise HTTPException(status_code=404, detail="Proof file is not stored")
        return FileResponse(
            path=str(stored),
            media_type=proof.content_type or "application/octet-stream",
            filename=proof.original_filename or f"{proof.proof_id}.bin",
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.delete(
    "/shipments/{shipment_id}/proofs/{proof_id}",
    response_model=NovaFreightProofOut,
    dependencies=[Depends(require_freight_offer_actor)],
)
def delete_shipment_proof(
    shipment_id: str,
    proof_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        return delete_proof(
            db,
            shipment_id,
            proof_id,
            organization_id=_org_id(user),
            actor_user_id=user.user_id,
            dispatcher_view=user.role in DISPATCH_ROLES,
        )
    except NovaFreightError as exc:
        _raise(exc)
