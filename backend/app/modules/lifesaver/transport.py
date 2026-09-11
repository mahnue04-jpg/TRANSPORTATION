"""Transportation connection/status interface.

Intentionally does not import Health ISF, Delivery, or ride internals.
V1 stores a Lifesaver-owned status record only.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.lifesaver.constants import TRANSPORT_STATUSES
from app.modules.lifesaver.models import LifesaverTransportConnection

_STATUS_TEXT = {
    "not_connected": "No transportation connection is linked.",
    "requested": "A transportation connection was requested. No ride internals are called.",
    "status_only": "Status-only interface is on. This is not a live dispatch feed.",
}


def get_or_create_connection(db: Session, *, organization_id: str, profile_id: str) -> LifesaverTransportConnection:
    row = (
        db.query(LifesaverTransportConnection)
        .filter(
            LifesaverTransportConnection.organization_id == organization_id,
            LifesaverTransportConnection.profile_id == profile_id,
        )
        .first()
    )
    if row:
        return row
    row = LifesaverTransportConnection(
        organization_id=organization_id,
        profile_id=profile_id,
        status="not_connected",
        status_text=_STATUS_TEXT["not_connected"],
    )
    db.add(row)
    db.flush()
    return row


def update_connection(
    db: Session,
    connection: LifesaverTransportConnection,
    status: str,
) -> LifesaverTransportConnection:
    if status not in TRANSPORT_STATUSES:
        raise ValueError("unsupported_transport_status")
    connection.status = status
    connection.status_text = _STATUS_TEXT[status]
    connection.updated_at = now()
    return connection


def serialize_connection(connection: LifesaverTransportConnection) -> dict:
    return {
        "id": connection.id,
        "status": connection.status,
        "status_text": connection.status_text,
        "linked_to_production_transport": False,
        "dispatches_rides": False,
        "updated_at": connection.updated_at.isoformat() if connection.updated_at else None,
    }
