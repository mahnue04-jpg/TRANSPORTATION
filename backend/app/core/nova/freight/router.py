"""Nova freight APIs. Separate from /api/health-isf and Delivery checkout."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
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
    NovaFreightShipmentCreate,
    NovaFreightShipmentOut,
    NovaFreightShipmentUpdate,
)
from app.core.nova.freight.service import (
    NovaFreightError,
    accept_offer,
    cancel_offer,
    carriers_for_user,
    create_carrier,
    create_offers,
    create_shipment,
    decline_offer,
    get_shipment,
    list_carriers,
    list_dispatch_shipments,
    list_shipment_offers,
    list_shipments,
    list_visible_offers,
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


@router.get("/shipments/{shipment_id}", response_model=NovaFreightShipmentOut, dependencies=[Depends(require_freight_shipper)])
def get_one_shipment(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return get_shipment(db, shipment_id, organization_id=_org_id(user))
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
