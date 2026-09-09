"""Nova freight shipment persistence. Org-scoped. No Health/Delivery entities."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import re

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.freight.models import (
    NovaFreightCarrier,
    NovaFreightOffer,
    NovaFreightProof,
    NovaFreightShipment,
    NovaFreightShipmentEvent,
)
from app.core.nova.freight.schemas import (
    DELIVERY_PROOF_STATUSES,
    DISPATCH_STATUSES,
    FORWARD_TRANSITIONS,
    PICKUP_PROOF_STATUSES,
    PRE_DISPATCH_STATUSES,
    SAFE_PROOF_CONTENT_TYPES,
    UNSAFE_PROOF_EXTENSIONS,
    NovaFreightCarrierCreate,
    NovaFreightOfferCreate,
    NovaFreightOfferOut,
    NovaFreightProofCreate,
    NovaFreightShipmentCreate,
    NovaFreightShipmentUpdate,
    NovaFreightStatusUpdate,
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


def _new_event_id() -> str:
    return "NFE-" + uuid4().replace("-", "")[:10].upper()


def list_carrier_active_shipments(
    db: Session,
    *,
    organization_id: str,
    carrier_ids: list[str],
) -> list[NovaFreightShipment]:
    if not carrier_ids:
        return []
    return (
        db.query(NovaFreightShipment)
        .filter(
            NovaFreightShipment.organization_id == organization_id,
            NovaFreightShipment.assigned_carrier_id.in_(carrier_ids),
            NovaFreightShipment.status.notin_(["completed", "cancelled"]),
        )
        .order_by(NovaFreightShipment.updated_at.desc())
        .all()
    )


def list_shipment_events(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
) -> list[NovaFreightShipmentEvent]:
    get_shipment(db, shipment_id, organization_id=organization_id)
    return (
        db.query(NovaFreightShipmentEvent)
        .filter(
            NovaFreightShipmentEvent.shipment_id == shipment_id,
            NovaFreightShipmentEvent.organization_id == organization_id,
        )
        .order_by(NovaFreightShipmentEvent.created_at.asc())
        .all()
    )


def _close_open_offers(db: Session, shipment_id: str, *, organization_id: str, stamp: datetime) -> None:
    (
        db.query(NovaFreightOffer)
        .filter(
            NovaFreightOffer.shipment_id == shipment_id,
            NovaFreightOffer.organization_id == organization_id,
            NovaFreightOffer.status == "pending",
        )
        .update(
            {"status": "cancelled", "responded_at": stamp, "updated_at": stamp},
            synchronize_session=False,
        )
    )


def transition_shipment_status(
    db: Session,
    shipment_id: str,
    payload: NovaFreightStatusUpdate,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
    allowed_carrier_ids: list[str] | None,
    dispatcher_view: bool,
) -> NovaFreightShipment:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    requested = payload.status
    current = shipment.status

    if current == "cancelled":
        raise NovaFreightError("Cancelled shipments cannot enter execution", status_code=409)
    if current in {"draft", "requested", "ready_for_dispatch", "offered", "assigned"} and not shipment.assigned_carrier_id:
        raise NovaFreightError("Unaccepted shipments cannot begin pickup execution", status_code=409)
    if current == "completed" and requested != "completed":
        raise NovaFreightError("Completed shipments cannot be reopened", status_code=409)

    if not dispatcher_view:
        if not shipment.assigned_carrier_id or shipment.assigned_carrier_id not in (allowed_carrier_ids or []):
            raise NovaFreightError("Only the assigned carrier can execute this shipment", status_code=403)

    if requested == current:
        return shipment

    expected = FORWARD_TRANSITIONS.get(current)
    if expected != requested:
        raise NovaFreightError(
            f"Invalid transition from {current} to {requested}",
            status_code=409,
        )

    stamp = now()
    claimed = (
        db.query(NovaFreightShipment)
        .filter(
            NovaFreightShipment.shipment_id == shipment.shipment_id,
            NovaFreightShipment.organization_id == organization_id,
            NovaFreightShipment.status == current,
        )
        .update(
            {
                "status": requested,
                "updated_at": stamp,
                "last_status_at": stamp,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.rollback()
        fresh = get_shipment(db, shipment_id, organization_id=organization_id)
        if fresh.status == requested:
            return fresh
        raise NovaFreightError("Shipment status changed; retry the current next step", status_code=409)

    if requested == "completed":
        _close_open_offers(db, shipment.shipment_id, organization_id=organization_id, stamp=stamp)

    db.add(
        NovaFreightShipmentEvent(
            event_id=_new_event_id(),
            shipment_id=shipment.shipment_id,
            organization_id=organization_id,
            status_before=current,
            status_after=requested,
            event_type="status_transition",
            actor_user_id=actor_user_id,
            actor_carrier_id=shipment.assigned_carrier_id,
            actor_role=actor_role,
            notes=payload.notes,
            latitude=payload.latitude,
            longitude=payload.longitude,
            source=payload.source or "nova_freight_execution",
            created_at=stamp,
        )
    )
    db.commit()
    return get_shipment(db, shipment_id, organization_id=organization_id)


PROOF_EVENT_TYPES = {
    "pickup_photo": "pickup_proof_added",
    "pickup_document": "pickup_proof_added",
    "pickup_signature": "pickup_signature_added",
    "delivery_photo": "delivery_proof_added",
    "delivery_document": "delivery_proof_added",
    "delivery_signature": "delivery_signature_added",
}
MAX_PROOF_BYTES = 10 * 1024 * 1024
PICKUP_PROOF_TYPES = frozenset({"pickup_photo", "pickup_signature", "pickup_document"})
DELIVERY_PROOF_TYPES = frozenset({"delivery_photo", "delivery_signature", "delivery_document"})


def _new_proof_id() -> str:
    return "NFP-" + uuid4().replace("-", "")[:10].upper()


def _new_document_ref() -> str:
    return "nfr-" + uuid4().replace("-", "")[:16]


def _safe_token(value: str, *, limit: int = 128) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", value or "")[:limit]


def proof_store_root() -> Path:
    configured = os.environ.get("NOVA_FREIGHT_PROOF_DIR")
    if configured:
        root = Path(configured)
    else:
        root = Path(__file__).resolve().parents[4] / "data" / "nova_freight_proofs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_proof_bytes(organization_id: str, document_ref: str, content: bytes) -> None:
    org = _safe_token(organization_id, limit=64) or "org"
    ref = _safe_token(document_ref) or _new_document_ref()
    dest = proof_store_root() / org / ref
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)


def proof_file_path(organization_id: str, document_ref: str) -> Path | None:
    org = _safe_token(organization_id, limit=64)
    ref = _safe_token(document_ref)
    if not org or not ref:
        return None
    path = proof_store_root() / org / ref
    if not path.is_file():
        return None
    return path


def validate_proof_file(*, filename: str | None, content_type: str | None, size: int | None) -> None:
    name = (filename or "").lower()
    suffix = Path(name).suffix
    if suffix in UNSAFE_PROOF_EXTENSIONS:
        raise NovaFreightError("Unsafe file type is not allowed", status_code=415)
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype and ctype not in SAFE_PROOF_CONTENT_TYPES:
        raise NovaFreightError("Unsupported proof file type", status_code=415)
    if suffix in {".html", ".htm", ".svg"}:
        raise NovaFreightError("Unsafe file type is not allowed", status_code=415)
    if size is not None and size > MAX_PROOF_BYTES:
        raise NovaFreightError("Proof file exceeds 10 MB", status_code=413)


def _allowed_statuses_for_proof(proof_type: str) -> frozenset[str]:
    if proof_type in PICKUP_PROOF_TYPES:
        return PICKUP_PROOF_STATUSES
    return DELIVERY_PROOF_STATUSES


def _sync_shipment_proof_refs(db: Session, shipment: NovaFreightShipment) -> None:
    active = (
        db.query(NovaFreightProof)
        .filter(
            NovaFreightProof.shipment_id == shipment.shipment_id,
            NovaFreightProof.organization_id == shipment.organization_id,
            NovaFreightProof.is_active.is_(True),
        )
        .all()
    )
    pickup = next((row.proof_id for row in active if row.proof_type in PICKUP_PROOF_TYPES), None)
    delivery = next((row.proof_id for row in active if row.proof_type in DELIVERY_PROOF_TYPES), None)
    shipment.proof_of_pickup_ref = pickup
    shipment.proof_of_delivery_ref = delivery


def _assert_proof_upload_allowed(
    shipment: NovaFreightShipment,
    proof_type: str,
    *,
    allowed_carrier_ids: list[str] | None,
    dispatcher_view: bool,
) -> None:
    if shipment.status == "cancelled":
        raise NovaFreightError("Cancelled shipments cannot accept proof", status_code=409)
    if shipment.status == "completed":
        raise NovaFreightError("Completed shipments are read-only for proof", status_code=409)
    if not shipment.assigned_carrier_id:
        raise NovaFreightError("Unaccepted shipments cannot accept proof", status_code=409)
    if not dispatcher_view:
        if shipment.assigned_carrier_id not in (allowed_carrier_ids or []):
            raise NovaFreightError("Only the assigned carrier can upload proof", status_code=403)
    allowed = _allowed_statuses_for_proof(proof_type)
    if shipment.status not in allowed:
        raise NovaFreightError(
            f"Proof type {proof_type} is not allowed at status {shipment.status}",
            status_code=409,
        )


def create_proof(
    db: Session,
    shipment_id: str,
    payload: NovaFreightProofCreate,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
    allowed_carrier_ids: list[str] | None,
    dispatcher_view: bool,
    file_bytes: bytes | None = None,
) -> NovaFreightProof:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    _assert_proof_upload_allowed(
        shipment,
        payload.proof_type,
        allowed_carrier_ids=allowed_carrier_ids,
        dispatcher_view=dispatcher_view,
    )
    if payload.original_filename or payload.content_type or file_bytes is not None:
        validate_proof_file(
            filename=payload.original_filename,
            content_type=payload.content_type,
            size=len(file_bytes) if file_bytes is not None else None,
        )
    document_ref = (payload.document_ref or "").strip() or _new_document_ref()
    existing = (
        db.query(NovaFreightProof)
        .filter(
            NovaFreightProof.shipment_id == shipment.shipment_id,
            NovaFreightProof.organization_id == organization_id,
            NovaFreightProof.document_ref == document_ref,
        )
        .first()
    )
    if existing:
        if file_bytes is not None and existing.is_active:
            store_proof_bytes(organization_id, document_ref, file_bytes)
        return existing

    stamp = now()
    proof = NovaFreightProof(
        proof_id=_new_proof_id(),
        shipment_id=shipment.shipment_id,
        organization_id=organization_id,
        proof_type=payload.proof_type,
        document_ref=document_ref,
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        uploaded_by_user_id=actor_user_id,
        uploaded_by_carrier_id=shipment.assigned_carrier_id,
        uploader_role=actor_role,
        notes=payload.notes,
        latitude=payload.latitude,
        longitude=payload.longitude,
        captured_at=payload.captured_at or stamp,
        signer_name=payload.signer_name,
        signer_role=payload.signer_role,
        is_active=True,
        uploaded_at=stamp,
        created_at=stamp,
        updated_at=stamp,
    )
    db.add(proof)
    db.flush()
    if file_bytes is not None:
        store_proof_bytes(organization_id, document_ref, file_bytes)
    db.add(
        NovaFreightShipmentEvent(
            event_id=_new_event_id(),
            shipment_id=shipment.shipment_id,
            organization_id=organization_id,
            status_before=shipment.status,
            status_after=shipment.status,
            event_type=PROOF_EVENT_TYPES[payload.proof_type],
            actor_user_id=actor_user_id,
            actor_carrier_id=shipment.assigned_carrier_id,
            actor_role=actor_role,
            notes=payload.notes,
            latitude=payload.latitude,
            longitude=payload.longitude,
            source="nova_freight_proof",
            proof_id=proof.proof_id,
            created_at=stamp,
        )
    )
    _sync_shipment_proof_refs(db, shipment)
    shipment.updated_at = stamp
    db.commit()
    db.refresh(proof)
    return proof


def list_proofs(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
) -> list[NovaFreightProof]:
    get_shipment(db, shipment_id, organization_id=organization_id)
    return (
        db.query(NovaFreightProof)
        .filter(
            NovaFreightProof.shipment_id == shipment_id,
            NovaFreightProof.organization_id == organization_id,
            NovaFreightProof.is_active.is_(True),
        )
        .order_by(NovaFreightProof.uploaded_at.asc())
        .all()
    )


def get_proof(
    db: Session,
    shipment_id: str,
    proof_id: str,
    *,
    organization_id: str,
) -> NovaFreightProof:
    get_shipment(db, shipment_id, organization_id=organization_id)
    row = (
        db.query(NovaFreightProof)
        .filter(
            NovaFreightProof.proof_id == proof_id,
            NovaFreightProof.shipment_id == shipment_id,
            NovaFreightProof.organization_id == organization_id,
            NovaFreightProof.is_active.is_(True),
        )
        .first()
    )
    if row is None:
        raise NovaFreightError("Proof not found", status_code=404)
    return row


def delete_proof(
    db: Session,
    shipment_id: str,
    proof_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    dispatcher_view: bool,
) -> NovaFreightProof:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    if shipment.status == "completed":
        raise NovaFreightError("Completed shipments are read-only for proof", status_code=409)
    if shipment.status == "cancelled":
        raise NovaFreightError("Cancelled shipments cannot change proof", status_code=409)
    row = get_proof(db, shipment_id, proof_id, organization_id=organization_id)
    if not dispatcher_view and row.uploaded_by_user_id != actor_user_id:
        raise NovaFreightError("Carriers cannot delete another user's proof", status_code=403)
    row.is_active = False
    row.updated_at = now()
    _sync_shipment_proof_refs(db, shipment)
    db.commit()
    db.refresh(row)
    return row
