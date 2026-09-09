"""Nova freight shipment persistence. Org-scoped. No Health/Delivery entities."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.freight.models import NovaFreightCarrier, NovaFreightOffer, NovaFreightShipment
from app.core.nova.freight.schemas import (
    DISPATCH_STATUSES,
    PRE_DISPATCH_STATUSES,
    NovaFreightCarrierCreate,
    NovaFreightOfferCreate,
    NovaFreightOfferOut,
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


def _new_carrier_id() -> str:
    return "NFC-" + uuid4().replace("-", "")[:10].upper()


def _new_offer_id() -> str:
    return "NFO-" + uuid4().replace("-", "")[:10].upper()


def _carrier_name_map(db: Session, organization_id: str, carrier_ids: list[str]) -> dict[str, str]:
    if not carrier_ids:
        return {}
    rows = (
        db.query(NovaFreightCarrier)
        .filter(
            NovaFreightCarrier.organization_id == organization_id,
            NovaFreightCarrier.carrier_id.in_(carrier_ids),
        )
        .all()
    )
    return {row.carrier_id: row.name for row in rows}


def create_carrier(
    db: Session,
    payload: NovaFreightCarrierCreate,
    *,
    organization_id: str,
) -> NovaFreightCarrier:
    row = None
    for _ in range(5):
        row = NovaFreightCarrier(
            carrier_id=_new_carrier_id(),
            organization_id=organization_id,
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
    raise NovaFreightError("Could not allocate a unique carrier ID", status_code=409)


def list_carriers(
    db: Session,
    *,
    organization_id: str,
    equipment_type: str | None = None,
    active_only: bool = True,
) -> list[NovaFreightCarrier]:
    query = db.query(NovaFreightCarrier).filter(NovaFreightCarrier.organization_id == organization_id)
    if active_only:
        query = query.filter(NovaFreightCarrier.active.is_(True))
    if equipment_type:
        query = query.filter(NovaFreightCarrier.equipment_type == equipment_type)
    return query.order_by(NovaFreightCarrier.name.asc()).all()


def get_carrier(
    db: Session,
    carrier_id: str,
    *,
    organization_id: str,
) -> NovaFreightCarrier:
    row = (
        db.query(NovaFreightCarrier)
        .filter(
            NovaFreightCarrier.carrier_id == carrier_id,
            NovaFreightCarrier.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise NovaFreightError("Carrier not found", status_code=404)
    return row


def carriers_for_user(db: Session, *, organization_id: str, user_id: str) -> list[NovaFreightCarrier]:
    return (
        db.query(NovaFreightCarrier)
        .filter(
            NovaFreightCarrier.organization_id == organization_id,
            NovaFreightCarrier.user_id == user_id,
            NovaFreightCarrier.active.is_(True),
        )
        .all()
    )


def list_dispatch_shipments(
    db: Session,
    *,
    organization_id: str,
    status: str | None = None,
    equipment_type: str | None = None,
    pickup: str | None = None,
    destination: str | None = None,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
    unassigned_only: bool = False,
) -> list[tuple[NovaFreightShipment, str | None, int]]:
    query = db.query(NovaFreightShipment).filter(NovaFreightShipment.organization_id == organization_id)
    if status:
        query = query.filter(NovaFreightShipment.status == status)
    else:
        query = query.filter(NovaFreightShipment.status.in_(DISPATCH_STATUSES))
    if equipment_type:
        query = query.filter(NovaFreightShipment.equipment_type == equipment_type)
    if pickup:
        like = f"%{pickup.strip()}%"
        query = query.filter(
            or_(
                NovaFreightShipment.pickup_city.ilike(like),
                NovaFreightShipment.pickup_state.ilike(like),
            )
        )
    if destination:
        like = f"%{destination.strip()}%"
        query = query.filter(
            or_(
                NovaFreightShipment.delivery_city.ilike(like),
                NovaFreightShipment.delivery_state.ilike(like),
            )
        )
    if window_from:
        query = query.filter(
            or_(
                NovaFreightShipment.pickup_window_end.is_(None),
                NovaFreightShipment.pickup_window_end >= window_from,
            )
        )
    if window_to:
        query = query.filter(
            or_(
                NovaFreightShipment.pickup_window_start.is_(None),
                NovaFreightShipment.pickup_window_start <= window_to,
            )
        )
    if unassigned_only:
        query = query.filter(NovaFreightShipment.assigned_carrier_id.is_(None))
    rows = query.order_by(NovaFreightShipment.created_at.desc()).all()
    names = _carrier_name_map(db, organization_id, [row.assigned_carrier_id for row in rows if row.assigned_carrier_id])
    pending_by_shipment: dict[str, int] = {}
    if rows:
        pending_rows = (
            db.query(NovaFreightOffer)
            .filter(
                NovaFreightOffer.organization_id == organization_id,
                NovaFreightOffer.status == "pending",
                NovaFreightOffer.shipment_id.in_([row.shipment_id for row in rows]),
            )
            .all()
        )
        for offer in pending_rows:
            pending_by_shipment[offer.shipment_id] = pending_by_shipment.get(offer.shipment_id, 0) + 1
    return [
        (row, names.get(row.assigned_carrier_id or ""), pending_by_shipment.get(row.shipment_id, 0))
        for row in rows
    ]


def _expire_stale_offers(db: Session, offers: list[NovaFreightOffer]) -> None:
    stamp = now()
    changed = False
    for offer in offers:
        if offer.status == "pending" and offer.expires_at and offer.expires_at < stamp:
            offer.status = "expired"
            offer.responded_at = stamp
            offer.updated_at = stamp
            changed = True
    if changed:
        db.flush()


def _offer_out(offer: NovaFreightOffer, shipment: NovaFreightShipment | None, carrier_name: str | None) -> NovaFreightOfferOut:
    return NovaFreightOfferOut(
        offer_id=offer.offer_id,
        shipment_id=offer.shipment_id,
        organization_id=offer.organization_id,
        carrier_id=offer.carrier_id,
        carrier_name=carrier_name,
        status=offer.status,
        offered_rate=offer.offered_rate,
        currency=offer.currency,
        offered_at=offer.offered_at,
        expires_at=offer.expires_at,
        responded_at=offer.responded_at,
        pickup_city=shipment.pickup_city if shipment else None,
        pickup_state=shipment.pickup_state if shipment else None,
        delivery_city=shipment.delivery_city if shipment else None,
        delivery_state=shipment.delivery_state if shipment else None,
        pickup_window_start=shipment.pickup_window_start if shipment else None,
        pickup_window_end=shipment.pickup_window_end if shipment else None,
        delivery_window_start=shipment.delivery_window_start if shipment else None,
        delivery_window_end=shipment.delivery_window_end if shipment else None,
        commodity=shipment.commodity if shipment else None,
        weight=shipment.weight if shipment else None,
        weight_unit=shipment.weight_unit if shipment else None,
        equipment_type=shipment.equipment_type if shipment else None,
        shipment_status=shipment.status if shipment else None,
    )


def create_offers(
    db: Session,
    shipment_id: str,
    payload: NovaFreightOfferCreate,
    *,
    organization_id: str,
    user_id: str | None,
) -> list[NovaFreightOfferOut]:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    if shipment.assigned_carrier_id:
        raise NovaFreightError("Shipment is already assigned", status_code=409)
    if shipment.status not in {"ready_for_dispatch", "offered"}:
        raise NovaFreightError("Shipment is not available for offering", status_code=409)

    created: list[NovaFreightOffer] = []
    stamp = now()
    for carrier_id in payload.carrier_ids:
        carrier = get_carrier(db, carrier_id, organization_id=organization_id)
        if not carrier.active:
            raise NovaFreightError(f"Carrier {carrier_id} is inactive", status_code=409)
        existing = (
            db.query(NovaFreightOffer)
            .filter(
                NovaFreightOffer.shipment_id == shipment.shipment_id,
                NovaFreightOffer.carrier_id == carrier.carrier_id,
                NovaFreightOffer.status == "pending",
            )
            .first()
        )
        if existing is not None:
            created.append(existing)
            continue
        offer = NovaFreightOffer(
            offer_id=_new_offer_id(),
            shipment_id=shipment.shipment_id,
            organization_id=organization_id,
            carrier_id=carrier.carrier_id,
            status="pending",
            offered_rate=payload.offered_rate,
            currency=payload.currency,
            offered_at=stamp,
            expires_at=payload.expires_at,
            created_by_user_id=user_id,
        )
        db.add(offer)
        created.append(offer)

    if shipment.status == "ready_for_dispatch":
        shipment.status = "offered"
        shipment.updated_at = stamp
    db.commit()
    names = _carrier_name_map(db, organization_id, [row.carrier_id for row in created])
    return [_offer_out(row, shipment, names.get(row.carrier_id)) for row in created]


def list_shipment_offers(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
) -> list[NovaFreightOfferOut]:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    offers = (
        db.query(NovaFreightOffer)
        .filter(
            NovaFreightOffer.shipment_id == shipment.shipment_id,
            NovaFreightOffer.organization_id == organization_id,
        )
        .order_by(NovaFreightOffer.offered_at.desc())
        .all()
    )
    _expire_stale_offers(db, offers)
    db.commit()
    names = _carrier_name_map(db, organization_id, [row.carrier_id for row in offers])
    return [_offer_out(row, shipment, names.get(row.carrier_id)) for row in offers]


def list_visible_offers(
    db: Session,
    *,
    organization_id: str,
    user_id: str | None,
    dispatcher_view: bool,
) -> list[NovaFreightOfferOut]:
    query = db.query(NovaFreightOffer).filter(NovaFreightOffer.organization_id == organization_id)
    if not dispatcher_view:
        mine = carriers_for_user(db, organization_id=organization_id, user_id=user_id or "")
        carrier_ids = [row.carrier_id for row in mine]
        if not carrier_ids:
            return []
        query = query.filter(NovaFreightOffer.carrier_id.in_(carrier_ids))
    offers = query.order_by(NovaFreightOffer.offered_at.desc()).all()
    _expire_stale_offers(db, offers)
    db.commit()
    shipment_ids = list({row.shipment_id for row in offers})
    shipments = {
        row.shipment_id: row
        for row in db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id.in_(shipment_ids or ["__none__"])).all()
    }
    names = _carrier_name_map(db, organization_id, [row.carrier_id for row in offers])
    return [_offer_out(row, shipments.get(row.shipment_id), names.get(row.carrier_id)) for row in offers]


def _get_offer(db: Session, offer_id: str, *, organization_id: str) -> NovaFreightOffer:
    row = (
        db.query(NovaFreightOffer)
        .filter(
            NovaFreightOffer.offer_id == offer_id,
            NovaFreightOffer.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise NovaFreightError("Offer not found", status_code=404)
    _expire_stale_offers(db, [row])
    return row


def accept_offer(
    db: Session,
    offer_id: str,
    *,
    organization_id: str,
    allowed_carrier_ids: list[str] | None,
) -> NovaFreightOfferOut:
    offer = _get_offer(db, offer_id, organization_id=organization_id)
    if allowed_carrier_ids is not None and offer.carrier_id not in allowed_carrier_ids:
        raise NovaFreightError("Offer not found", status_code=404)
    if offer.status != "pending":
        if offer.status == "accepted":
            raise NovaFreightError("Offer already accepted", status_code=409)
        raise NovaFreightError("Offer is no longer available", status_code=409)

    stamp = now()
    claimed = (
        db.query(NovaFreightShipment)
        .filter(
            NovaFreightShipment.shipment_id == offer.shipment_id,
            NovaFreightShipment.organization_id == organization_id,
            NovaFreightShipment.assigned_carrier_id.is_(None),
            NovaFreightShipment.status.in_(["ready_for_dispatch", "offered"]),
        )
        .update(
            {
                "assigned_carrier_id": offer.carrier_id,
                "assigned_offer_id": offer.offer_id,
                "status": "accepted",
                "updated_at": stamp,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.rollback()
        raise NovaFreightError("Shipment already assigned", status_code=409)

    offer.status = "accepted"
    offer.responded_at = stamp
    offer.updated_at = stamp
    (
        db.query(NovaFreightOffer)
        .filter(
            NovaFreightOffer.shipment_id == offer.shipment_id,
            NovaFreightOffer.offer_id != offer.offer_id,
            NovaFreightOffer.status == "pending",
        )
        .update(
            {"status": "cancelled", "responded_at": stamp, "updated_at": stamp},
            synchronize_session=False,
        )
    )
    db.commit()
    shipment = get_shipment(db, offer.shipment_id, organization_id=organization_id)
    names = _carrier_name_map(db, organization_id, [offer.carrier_id])
    return _offer_out(offer, shipment, names.get(offer.carrier_id))


def decline_offer(
    db: Session,
    offer_id: str,
    *,
    organization_id: str,
    allowed_carrier_ids: list[str] | None,
) -> NovaFreightOfferOut:
    offer = _get_offer(db, offer_id, organization_id=organization_id)
    if allowed_carrier_ids is not None and offer.carrier_id not in allowed_carrier_ids:
        raise NovaFreightError("Offer not found", status_code=404)
    if offer.status != "pending":
        raise NovaFreightError("Offer is no longer pending", status_code=409)
    stamp = now()
    offer.status = "declined"
    offer.responded_at = stamp
    offer.updated_at = stamp
    db.flush()
    _restore_ready_if_unassigned(db, offer.shipment_id, organization_id=organization_id, stamp=stamp)
    db.commit()
    shipment = get_shipment(db, offer.shipment_id, organization_id=organization_id)
    names = _carrier_name_map(db, organization_id, [offer.carrier_id])
    return _offer_out(offer, shipment, names.get(offer.carrier_id))


def cancel_offer(
    db: Session,
    offer_id: str,
    *,
    organization_id: str,
) -> NovaFreightOfferOut:
    offer = _get_offer(db, offer_id, organization_id=organization_id)
    if offer.status != "pending":
        raise NovaFreightError("Only pending offers can be cancelled", status_code=409)
    stamp = now()
    offer.status = "cancelled"
    offer.responded_at = stamp
    offer.updated_at = stamp
    db.flush()
    _restore_ready_if_unassigned(db, offer.shipment_id, organization_id=organization_id, stamp=stamp)
    db.commit()
    shipment = get_shipment(db, offer.shipment_id, organization_id=organization_id)
    names = _carrier_name_map(db, organization_id, [offer.carrier_id])
    return _offer_out(offer, shipment, names.get(offer.carrier_id))


def _restore_ready_if_unassigned(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    stamp: datetime,
) -> None:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    if shipment.assigned_carrier_id:
        return
    pending = (
        db.query(NovaFreightOffer)
        .filter(
            NovaFreightOffer.shipment_id == shipment_id,
            NovaFreightOffer.organization_id == organization_id,
            NovaFreightOffer.status == "pending",
        )
        .count()
    )
    if pending == 0 and shipment.status == "offered":
        shipment.status = "ready_for_dispatch"
        shipment.updated_at = stamp
