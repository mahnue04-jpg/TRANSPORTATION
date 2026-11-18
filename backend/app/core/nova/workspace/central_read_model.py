"""Nova Central tenant-scoped journey read-model contract (not yet activated).

No migrations or table creation happen on import. No writer, service
dispatcher, external calls or customer data access. This is a proposed
durable schema and read repository for isolated acceptance testing only.

Before runtime use, approve the production schema/migration, source-of-truth
sync and retention policy independently. The existing Workspace endpoint
must remain default-off and return not_connected until those gates pass.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, select
from sqlalchemy.orm import Session

# Intentionally isolated from Base.metadata so startup create_all cannot
# silently create a new production table.
READ_MODEL_METADATA = MetaData()
JOURNEY_READ_ROWS = Table(
    "nova_central_journey_read_model",
    READ_MODEL_METADATA,
    Column("organization_id", String(64), primary_key=True),
    Column("correlation_id", String(128), primary_key=True),
    Column("state", String(32), nullable=False),
    Column("assigned_agent", String(32), nullable=False),
    Column("owner_action", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
)


@dataclass(frozen=True)
class JourneyStatus:
    correlation_id: str
    state: str
    assigned_agent: str
    owner_action: str
    revision: int


def read_journey(
    db: Session, *, authenticated_organization_id: str,
    authenticated_role: str, correlation_id: str,
) -> JourneyStatus | None:
    """Read one tenant-bound, non-PII status row.

    An authenticated service layer must derive organization and role from
    current persisted session context; browser-supplied fields are not trusted.
    This function deliberately returns no source payloads, media, contacts or
    customer identity fields.
    """
    if (not authenticated_organization_id or
            authenticated_organization_id == "global" or
            authenticated_role != "admin" or not correlation_id):
        raise PermissionError("organization owner context required")
    row = db.execute(
        select(
            JOURNEY_READ_ROWS.c.correlation_id,
            JOURNEY_READ_ROWS.c.state,
            JOURNEY_READ_ROWS.c.assigned_agent,
            JOURNEY_READ_ROWS.c.owner_action,
            JOURNEY_READ_ROWS.c.revision,
        ).where(
            JOURNEY_READ_ROWS.c.organization_id == authenticated_organization_id,
            JOURNEY_READ_ROWS.c.correlation_id == correlation_id,
        )
    ).mappings().one_or_none()
    return JourneyStatus(**row) if row is not None else None


def list_journeys(
    db: Session, *, authenticated_organization_id: str,
    authenticated_role: str, limit: int = 20,
) -> tuple[JourneyStatus, ...]:
    """Bounded, deterministic owner-only listing with tenant filter in SQL."""
    if (not authenticated_organization_id or
            authenticated_organization_id == "global" or
            authenticated_role != "admin"):
        raise PermissionError("organization owner context required")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("invalid page limit")
    rows = db.execute(
        select(
            JOURNEY_READ_ROWS.c.correlation_id,
            JOURNEY_READ_ROWS.c.state,
            JOURNEY_READ_ROWS.c.assigned_agent,
            JOURNEY_READ_ROWS.c.owner_action,
            JOURNEY_READ_ROWS.c.revision,
        ).where(
            JOURNEY_READ_ROWS.c.organization_id == authenticated_organization_id
        ).order_by(
            JOURNEY_READ_ROWS.c.correlation_id,
        ).limit(limit)
    ).mappings().all()
    return tuple(JourneyStatus(**row) for row in rows)
