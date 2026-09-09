"""Nova freight APIs. Separate from /api/health-isf and Delivery checkout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_DISPATCHER,
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
    NovaFreightShipmentCreate,
    NovaFreightShipmentOut,
    NovaFreightShipmentUpdate,
)
from app.core.nova.freight.service import (
    NovaFreightError,
    create_shipment,
    get_shipment,
    list_shipments,
    update_shipment,
)
from app.core.nova.service import NovaCoreService
from app.db.session import get_db

require_freight_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_RIDER,
    ROLE_PROVIDER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
)

router = APIRouter(
    prefix="/api/nova/freight",
    tags=["nova-freight"],
    dependencies=[Depends(require_freight_access)],
)


def _org_id(user: UserContext) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, None)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _raise(exc: NovaFreightError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/shipments", response_model=NovaFreightShipmentOut, status_code=201)
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


@router.get("/shipments", response_model=list[NovaFreightShipmentOut])
def get_shipments(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return list_shipments(db, organization_id=_org_id(user))


@router.get("/shipments/{shipment_id}", response_model=NovaFreightShipmentOut)
def get_one_shipment(
    shipment_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return get_shipment(db, shipment_id, organization_id=_org_id(user))
    except NovaFreightError as exc:
        _raise(exc)


@router.patch("/shipments/{shipment_id}", response_model=NovaFreightShipmentOut)
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
