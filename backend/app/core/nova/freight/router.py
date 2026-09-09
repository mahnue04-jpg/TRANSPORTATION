"""Nova freight APIs. Separate from /api/health-isf and Delivery checkout."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
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
from app.core.nova.freight.settlement import (
    adjust_payout,
    approve_payout,
    carrier_earnings,
    create_payout,
    execute_simulated_payout,
    finance_board_row,
    get_payout_or_404,
    get_settlement_for_payout,
    get_shipment_payout,
    hold_payout,
    list_org_payouts,
    payout_eligibility,
    remittance_view,
    void_payout,
)
from app.core.nova.freight.commercial import (
    calculate_suggested_quote,
    confirm_customer_payment,
    create_invoice,
    customer_quote_view,
    finalize_invoice,
    finalize_quote,
    get_invoice_or_404,
    get_quote_or_404,
    invoice_out,
    process_nova_freight_webhook,
    quote_out,
    save_quote,
    start_customer_payment,
    verify_nova_freight_webhook,
    void_invoice,
)
from app.core.nova.freight.schemas import (
    NovaFreightCarrierCreate,
    NovaFreightCarrierOut,
    NovaFreightCustomerQuoteOut,
    NovaFreightDispatchShipmentOut,
    NovaFreightInvoiceOut,
    NovaFreightOfferCreate,
    NovaFreightOfferOut,
    NovaFreightPaymentConfirm,
    NovaFreightPaymentStart,
    NovaFreightPayoutAdjust,
    NovaFreightPayoutHold,
    NovaFreightPayoutOut,
    NovaFreightSettlementOut,
    NovaFreightProofCreate,
    NovaFreightProofOut,
    NovaFreightQuoteOut,
    NovaFreightQuoteUpdate,
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
require_freight_finance = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
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
FINANCE_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}


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


def _shipment_out(user: UserContext, shipment) -> NovaFreightShipmentOut:
    item = NovaFreightShipmentOut.model_validate(shipment)
    if user.role not in DISPATCH_ROLES:
        item.amicor_margin = None
        item.carrier_payout_amount = None
    return item


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
        return _shipment_out(
            user,
            create_shipment(
                db,
                payload,
                organization_id=_org_id(user),
                user_id=user.user_id,
            ),
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get("/shipments", response_model=list[NovaFreightShipmentOut], dependencies=[Depends(require_freight_shipper)])
def get_shipments(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return [_shipment_out(user, row) for row in list_shipments(db, organization_id=_org_id(user))]


@router.get("/shipments/{shipment_id}", response_model=NovaFreightShipmentOut, dependencies=[Depends(require_freight_viewer)])
def get_one_shipment(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        return _shipment_out(user, shipment)
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
        return _shipment_out(
            user,
            update_shipment(
                db,
                shipment_id,
                payload,
                organization_id=_org_id(user),
            ),
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
        rows = list_carrier_active_shipments(
            db,
            organization_id=_org_id(user),
            carrier_ids=[
                row.carrier_id for row in list_carriers(db, organization_id=_org_id(user), active_only=True)
            ],
        )
    else:
        rows = list_carrier_active_shipments(
            db,
            organization_id=_org_id(user),
            carrier_ids=_carrier_scope(db, user, False) or [],
        )
    return [_shipment_out(user, row) for row in rows]


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
        return _shipment_out(
            user,
            transition_shipment_status(
                db,
                shipment_id,
                payload,
                organization_id=_org_id(user),
                actor_user_id=user.user_id,
                actor_role=user.role,
                allowed_carrier_ids=_carrier_scope(db, user, user.role in DISPATCH_ROLES),
                dispatcher_view=user.role in DISPATCH_ROLES,
            ),
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


@router.post(
    "/shipments/{shipment_id}/quote/suggest",
    dependencies=[Depends(require_freight_dispatch)],
)
def post_quote_suggest(
    shipment_id: str,
    payload: NovaFreightQuoteUpdate | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        body = payload or NovaFreightQuoteUpdate()
        return calculate_suggested_quote(
            db,
            shipment_id,
            organization_id=_org_id(user),
            estimated_miles=body.estimated_miles,
            estimated_hours=body.estimated_hours,
            other_surcharge=body.other_surcharge,
            discount_amount=body.discount_amount,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/quote",
    response_model=NovaFreightQuoteOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_quote(
    shipment_id: str,
    payload: NovaFreightQuoteUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return quote_out(
            save_quote(
                db,
                shipment_id,
                payload,
                organization_id=_org_id(user),
                actor_user_id=user.user_id,
                actor_role=user.role,
            )
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/quote/finalize",
    response_model=NovaFreightQuoteOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_quote_finalize(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return quote_out(
            finalize_quote(
                db,
                shipment_id,
                organization_id=_org_id(user),
                actor_user_id=user.user_id,
                actor_role=user.role,
            )
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/quote",
    response_model=NovaFreightQuoteOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def get_quote(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return quote_out(get_quote_or_404(db, shipment_id, organization_id=_org_id(user)))
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/quote/customer",
    response_model=NovaFreightCustomerQuoteOut,
    dependencies=[Depends(require_freight_viewer)],
)
def get_customer_quote(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        return customer_quote_view(db, shipment_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/invoice",
    response_model=NovaFreightInvoiceOut,
    status_code=201,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_invoice(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return invoice_out(
            create_invoice(
                db,
                shipment_id,
                organization_id=_org_id(user),
                actor_user_id=user.user_id,
                actor_role=user.role,
            )
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/invoice/finalize",
    response_model=NovaFreightInvoiceOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_invoice_finalize(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return invoice_out(
            finalize_invoice(
                db,
                shipment_id,
                organization_id=_org_id(user),
                actor_user_id=user.user_id,
                actor_role=user.role,
            )
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/invoice",
    response_model=NovaFreightInvoiceOut,
    dependencies=[Depends(require_freight_viewer)],
)
def get_invoice(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        shipment = get_shipment(db, shipment_id, organization_id=_org_id(user))
        _assert_viewer_access(db, user, shipment)
        invoice = get_invoice_or_404(db, shipment_id, organization_id=_org_id(user))
        if user.role not in DISPATCH_ROLES and user.role not in {ROLE_RIDER, ROLE_PROVIDER}:
            raise HTTPException(status_code=403, detail="Only the customer or dispatch can view this invoice")
        return invoice_out(invoice)
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/invoice/void",
    response_model=NovaFreightInvoiceOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_invoice_void(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return invoice_out(
            void_invoice(
                db,
                shipment_id,
                organization_id=_org_id(user),
                actor_user_id=user.user_id,
                actor_role=user.role,
            )
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/invoice/pay",
    dependencies=[Depends(require_freight_shipper)],
)
def post_invoice_pay(
    shipment_id: str,
    payload: NovaFreightPaymentStart | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        body = payload or NovaFreightPaymentStart()
        return start_customer_payment(
            db,
            shipment_id,
            organization_id=_org_id(user),
            actor_user_id=user.user_id,
            actor_role=user.role,
            requested_amount=body.amount,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/invoice/confirm-payment",
    response_model=NovaFreightInvoiceOut,
    dependencies=[Depends(require_freight_shipper)],
)
def post_invoice_confirm_payment(
    shipment_id: str,
    payload: NovaFreightPaymentConfirm | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        body = payload or NovaFreightPaymentConfirm()
        return invoice_out(
            confirm_customer_payment(
                db,
                shipment_id,
                organization_id=_org_id(user),
                actor_user_id=user.user_id,
                actor_role=user.role,
                simulate=body.simulate,
            )
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post("/stripe/webhook")
async def nova_freight_stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
):
    payload = await request.body()
    try:
        event = verify_nova_freight_webhook(payload, stripe_signature)
        result = process_nova_freight_webhook(db, event)
        return {"received": True, **result}
    except NovaFreightError as exc:
        _raise(exc)
    except Exception as exc:
        import stripe

        signature_error = getattr(stripe, "SignatureVerificationError", None)
        if signature_error is not None and isinstance(exc, signature_error):
            raise HTTPException(status_code=400, detail="Invalid Stripe signature.") from exc
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook.") from exc


@router.get(
    "/shipments/{shipment_id}/payout/eligibility",
    dependencies=[Depends(require_freight_dispatch)],
)
def get_payout_eligibility(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return payout_eligibility(db, shipment_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/shipments/{shipment_id}/payout",
    response_model=NovaFreightPayoutOut,
    status_code=201,
    dependencies=[Depends(require_freight_dispatch)],
)
def post_payout(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return create_payout(
            db,
            shipment_id,
            organization_id=_org_id(user),
            actor_user_id=user.user_id,
            actor_role=user.role,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/shipments/{shipment_id}/payout",
    response_model=NovaFreightPayoutOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def get_shipment_payout_route(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return get_shipment_payout(db, shipment_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get("/payouts", dependencies=[Depends(require_freight_dispatch)])
def get_payouts(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return [finance_board_row(db, row) for row in list_org_payouts(db, organization_id=_org_id(user))]


@router.post(
    "/payouts/{payout_id}/adjust",
    response_model=NovaFreightPayoutOut,
    dependencies=[Depends(require_freight_finance)],
)
def post_payout_adjust(
    payout_id: str,
    payload: NovaFreightPayoutAdjust,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return adjust_payout(
            db,
            payout_id,
            organization_id=_org_id(user),
            carrier_payout_amount=payload.carrier_payout_amount,
            reason=payload.reason,
            actor_user_id=user.user_id,
            actor_role=user.role,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/payouts/{payout_id}/hold",
    response_model=NovaFreightPayoutOut,
    dependencies=[Depends(require_freight_finance)],
)
def post_payout_hold(
    payout_id: str,
    payload: NovaFreightPayoutHold | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        body = payload or NovaFreightPayoutHold()
        return hold_payout(
            db,
            payout_id,
            organization_id=_org_id(user),
            reason=body.reason,
            actor_user_id=user.user_id,
            actor_role=user.role,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/payouts/{payout_id}/approve",
    response_model=NovaFreightPayoutOut,
    dependencies=[Depends(require_freight_finance)],
)
def post_payout_approve(
    payout_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return approve_payout(
            db,
            payout_id,
            organization_id=_org_id(user),
            actor_user_id=user.user_id,
            actor_role=user.role,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/payouts/{payout_id}/void",
    response_model=NovaFreightPayoutOut,
    dependencies=[Depends(require_freight_finance)],
)
def post_payout_void(
    payout_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return void_payout(
            db,
            payout_id,
            organization_id=_org_id(user),
            actor_user_id=user.user_id,
            actor_role=user.role,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.post(
    "/payouts/{payout_id}/execute",
    response_model=NovaFreightPayoutOut,
    dependencies=[Depends(require_freight_finance)],
)
def post_payout_execute(
    payout_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return execute_simulated_payout(
            db,
            payout_id,
            organization_id=_org_id(user),
            actor_user_id=user.user_id,
            actor_role=user.role,
        )
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/payouts/{payout_id}/settlement",
    response_model=NovaFreightSettlementOut,
    dependencies=[Depends(require_freight_dispatch)],
)
def get_payout_settlement(
    payout_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return get_settlement_for_payout(db, payout_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get(
    "/payouts/{payout_id}/remittance",
    dependencies=[Depends(require_freight_offer_actor)],
)
def get_payout_remittance(
    payout_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        payout = get_payout_or_404(db, payout_id, organization_id=_org_id(user))
        if user.role not in DISPATCH_ROLES:
            allowed = _carrier_scope(db, user, False) or []
            if payout.carrier_id not in allowed:
                raise HTTPException(status_code=403, detail="Carriers can only view their own remittance")
        return remittance_view(db, payout_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.get("/carrier/earnings", dependencies=[Depends(require_freight_offer_actor)])
def get_carrier_earnings(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    dispatcher_view = user.role in DISPATCH_ROLES
    if dispatcher_view:
        raise HTTPException(status_code=403, detail="Use the finance payout board for dispatch earnings review")
    return carrier_earnings(
        db,
        organization_id=_org_id(user),
        carrier_ids=_carrier_scope(db, user, False) or [],
    )
