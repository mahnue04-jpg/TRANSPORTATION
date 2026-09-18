"""Lifesaver transportation coordination bridge.

Never imports Health ISF, never creates rides, never assigns drivers or fares.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.lifesaver.constants import TRANSPORT_COORD_DISCLAIMER, TRANSPORT_REQUEST_STATUSES
from app.modules.lifesaver.models import LifesaverTransportRequest

_ADVANCE = {
    "requested": "needs_review",
    "needs_review": "ready_for_handoff",
    "ready_for_handoff": "handed_off_simulated",
}


def serialize_request(row: LifesaverTransportRequest) -> dict:
    return {
        "id": row.id,
        "appointment_id": row.appointment_id,
        "pickup_at": row.pickup_at.isoformat() if row.pickup_at else None,
        "pickup_label": row.pickup_label,
        "destination_label": row.destination_label,
        "accessibility_needs": row.accessibility_needs,
        "mobility_note": row.mobility_note,
        "companion_needed": bool(row.companion_needed),
        "status": row.status,
        "dispatches_ride": False,
        "creates_health_isf_ride": False,
        "simulated": row.status == "handed_off_simulated",
        "disclaimer": TRANSPORT_COORD_DISCLAIMER,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def create_request(
    db: Session,
    *,
    organization_id: str,
    profile_id: str,
    created_by_user_id: str,
    appointment_id: str | None,
    pickup_at: datetime | None,
    pickup_label: str,
    destination_label: str,
    accessibility_needs: str | None,
    mobility_note: str | None,
    companion_needed: bool,
) -> LifesaverTransportRequest:
    row = LifesaverTransportRequest(
        organization_id=organization_id,
        profile_id=profile_id,
        appointment_id=appointment_id,
        pickup_at=pickup_at,
        pickup_label=pickup_label.strip()[:160],
        destination_label=destination_label.strip()[:160],
        accessibility_needs=(accessibility_needs or "").strip()[:256] or None,
        mobility_note=(mobility_note or "").strip()[:256] or None,
        companion_needed=bool(companion_needed),
        status="requested",
        created_by_user_id=created_by_user_id,
        updated_at=now(),
    )
    db.add(row)
    db.flush()
    return row


def confirm_ready(db: Session, row: LifesaverTransportRequest, *, user_id: str, confirm: bool) -> LifesaverTransportRequest:
    if not confirm:
        raise HTTPException(status_code=422, detail="Human confirmation is required before READY_FOR_HANDOFF.")
    if row.status not in {"requested", "needs_review"}:
        raise HTTPException(status_code=409, detail="This request cannot be confirmed in its current status.")
    row.status = "ready_for_handoff"
    row.confirmed_by_user_id = user_id
    row.updated_at = now()
    return row


def simulated_handoff(db: Session, row: LifesaverTransportRequest) -> LifesaverTransportRequest:
    if row.status != "ready_for_handoff":
        raise HTTPException(status_code=409, detail="Simulated handoff requires READY_FOR_HANDOFF.")
    row.status = "handed_off_simulated"
    row.updated_at = now()
    return row


def cancel_request(db: Session, row: LifesaverTransportRequest) -> LifesaverTransportRequest:
    if row.status == "handed_off_simulated":
        raise HTTPException(status_code=409, detail="A simulated handoff cannot be cancelled.")
    row.status = "cancelled"
    row.updated_at = now()
    return row


def list_requests(db: Session, *, organization_id: str, profile_id: str) -> list[LifesaverTransportRequest]:
    return (
        db.query(LifesaverTransportRequest)
        .filter(
            LifesaverTransportRequest.organization_id == organization_id,
            LifesaverTransportRequest.profile_id == profile_id,
        )
        .order_by(LifesaverTransportRequest.created_at.desc())
        .limit(40)
        .all()
    )


def get_owned(db: Session, *, organization_id: str, profile_id: str, request_id: str) -> LifesaverTransportRequest:
    row = (
        db.query(LifesaverTransportRequest)
        .filter(
            LifesaverTransportRequest.id == request_id,
            LifesaverTransportRequest.organization_id == organization_id,
            LifesaverTransportRequest.profile_id == profile_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Transportation request was not found.")
    if row.status not in TRANSPORT_REQUEST_STATUSES:
        raise HTTPException(status_code=409, detail="Unsupported transportation status.")
    return row
