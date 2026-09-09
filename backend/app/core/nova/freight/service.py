"""Nova freight shipment persistence. Org-scoped. No Health/Delivery entities."""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.freight.models import NovaFreightShipment
from app.core.nova.freight.schemas import (
    PRE_DISPATCH_STATUSES,
    NovaFreightShipmentCreate,
    NovaFreightShipmentUpdate,
)
from app.helpers import now, uuid4


class NovaFreightError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _new_shipment_id() -> str:
    return "NF-" + uuid4().replace("-", "")[:12].upper()


def create_shipment(
    db: Session,
    payload: NovaFreightShipmentCreate,
    *,
    organization_id: str,
    user_id: str | None,
) -> NovaFreightShipment:
    row = None
    for _ in range(5):
        row = NovaFreightShipment(
            shipment_id=_new_shipment_id(),
            organization_id=organization_id,
            shipper_user_id=user_id,
            created_by_user_id=user_id,
            status="ready_for_dispatch",
            **payload.model_dump(),
        )
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return row
        except IntegrityError:
            db.rollback()
            row = None
    raise NovaFreightError("Could not allocate a unique shipment ID", status_code=409)


def list_shipments(db: Session, *, organization_id: str) -> list[NovaFreightShipment]:
    return (
        db.query(NovaFreightShipment)
        .filter(NovaFreightShipment.organization_id == organization_id)
        .order_by(NovaFreightShipment.created_at.desc())
        .all()
    )


def get_shipment(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
) -> NovaFreightShipment:
    row = (
        db.query(NovaFreightShipment)
        .filter(
            NovaFreightShipment.shipment_id == shipment_id,
            NovaFreightShipment.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise NovaFreightError("Shipment not found", status_code=404)
    return row


def update_shipment(
    db: Session,
    shipment_id: str,
    payload: NovaFreightShipmentUpdate,
    *,
    organization_id: str,
) -> NovaFreightShipment:
    row = get_shipment(db, shipment_id, organization_id=organization_id)
    if row.status not in PRE_DISPATCH_STATUSES:
        raise NovaFreightError(
            "Only pre-dispatch shipments can be edited",
            status_code=409,
        )
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return row
    for key, value in updates.items():
        setattr(row, key, value)
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row
