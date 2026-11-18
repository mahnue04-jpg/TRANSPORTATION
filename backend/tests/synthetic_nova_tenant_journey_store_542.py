"""Disposable, read-only tenant-scoped journey lookup acceptance fixture.

Not a live backend repository or migration. This helper only reads an explicitly
created temporary SQLAlchemy table; never queries production customer records.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, select
from sqlalchemy.orm import Session


metadata = MetaData()
journey_rows = Table(
    "synthetic_nova_central_journeys_542", metadata,
    Column("organization_id", String(64), primary_key=True),
    Column("correlation_id", String(128), primary_key=True),
    Column("state", String(32), nullable=False),
    Column("owner_action", String(32), nullable=False),
    Column("assigned_agent", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
)


@dataclass(frozen=True)
class JourneySummary:
    correlation_id: str
    state: str
    assigned_agent: str
    owner_action: str
    revision: int


def get_owner_journey(
    session: Session, *, verified_organization_id: str, verified_role: str,
    correlation_id: str,
) -> JourneySummary | None:
    """Return only non-PII journey status, scoped to a trusted tenant identity.

    The caller MUST derive org/role from authenticated server-side context;
    this function does not authenticate tokens and must not be exposed as an API.
    """
    if (not verified_organization_id or verified_organization_id == "global"
            or verified_role != "admin" or not correlation_id):
        raise PermissionError("verified organization owner required")
    row = session.execute(
        select(
            journey_rows.c.correlation_id, journey_rows.c.state,
            journey_rows.c.assigned_agent, journey_rows.c.owner_action,
            journey_rows.c.revision,
        ).where(
            journey_rows.c.organization_id == verified_organization_id,
            journey_rows.c.correlation_id == correlation_id,
        )
    ).mappings().one_or_none()
    return JourneySummary(**row) if row else None
