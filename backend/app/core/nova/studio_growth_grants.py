"""Proposed owner grant storage for Studio->Growth staging, NOT deployed.

The SQL schema below is for disposable SQLite contract tests only; it is never
executed on import or at application startup. A separately reviewed database
migration and authenticated owner-only route are prerequisites for activation.

Repository callers MUST independently authenticate the owner and select the
tenant from their signed session. A supplied actor ID is not proof of identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Protocol

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
ACTION = "share_campaign_asset_with_growth"
SCHEMA_VERSION = "nova.studio-growth-grant.v0.1"
TEST_SCHEMA = """
CREATE TABLE studio_growth_owner_grants (
    grant_id TEXT NOT NULL PRIMARY KEY,
    organization_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action = 'share_campaign_asset_with_growth'),
    approved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    schema_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (organization_id, idempotency_key),
    UNIQUE (organization_id, project_id, asset_id, campaign_id, action)
)
"""


class QueryConnection(Protocol):
    def execute(self, sql: str, parameters: tuple = ()): ...


def _id(value: str) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC-aware datetime required")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class OwnerGrant:
    grant_id: str
    organization_id: str
    owner_user_id: str
    project_id: str
    asset_id: str
    campaign_id: str
    approved_at: datetime
    expires_at: datetime
    idempotency_key: str
    action: str = ACTION
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        if not all(_id(getattr(self, k)) for k in (
            "grant_id", "organization_id", "owner_user_id", "project_id",
            "asset_id", "campaign_id", "idempotency_key"
        )):
            raise ValueError("invalid owner grant identifier")
        if self.action != ACTION or self.schema_version != SCHEMA_VERSION:
            raise ValueError("unexpected approval action or grant schema")
        if _utc(self.expires_at) <= _utc(self.approved_at):
            raise ValueError("grant expiration must follow approval")


class OwnerGrantLedger:
    """Explicitly provisioned, tenant-scoped grant table. No implicit writes.

    Tests inject a local SQLite connection. Production use requires a separate
    migration and transactional authorizer; do not inject a production connection.
    """

    def __init__(self, connection: QueryConnection):
        self.db = connection

    def record(self, grant: OwnerGrant, *, authenticated_owner_id: str) -> str:
        """Caller must have verified the signed owner session and tenant."""
        if not _id(authenticated_owner_id) or grant.owner_user_id != authenticated_owner_id:
            raise PermissionError("verified owner session mismatch")
        existing = self.db.execute(
            """SELECT grant_id, owner_user_id, project_id, asset_id, campaign_id,
                      action, approved_at, expires_at, schema_version, revoked_at
               FROM studio_growth_owner_grants
               WHERE organization_id=? AND idempotency_key=?""",
            (grant.organization_id, grant.idempotency_key),
        ).fetchone()
        expected = (
            grant.grant_id, grant.owner_user_id, grant.project_id, grant.asset_id,
            grant.campaign_id, grant.action, _stamp(grant.approved_at),
            _stamp(grant.expires_at), grant.schema_version,
        )
        if existing is not None:
            # Never represent a revoked grant as a successful approval replay.
            # A new authorization requires a separately reviewed grant lifecycle.
            if tuple(existing[:-1]) == expected:
                if existing[-1] is not None:
                    raise PermissionError("revoked owner grant cannot be replayed")
                return "duplicate"
            raise PermissionError("owner grant idempotency collision")
        self.db.execute(
            """INSERT INTO studio_growth_owner_grants
               (grant_id, organization_id, owner_user_id, project_id, asset_id,
                campaign_id, action, approved_at, expires_at, revoked_at,
                schema_version, idempotency_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                grant.grant_id, grant.organization_id, grant.owner_user_id,
                grant.project_id, grant.asset_id, grant.campaign_id, grant.action,
                _stamp(grant.approved_at), _stamp(grant.expires_at),
                grant.schema_version, grant.idempotency_key,
            ),
        )
        return "recorded"

    def revoke(self, *, organization_id: str, grant_id: str,
               authenticated_owner_id: str, now: datetime) -> bool:
        if not all(_id(x) for x in (organization_id, grant_id, authenticated_owner_id)):
            raise PermissionError("invalid revocation identity")
        cursor = self.db.execute(
            """UPDATE studio_growth_owner_grants SET revoked_at=?
               WHERE organization_id=? AND grant_id=? AND owner_user_id=?
                 AND revoked_at IS NULL""",
            (_stamp(now), organization_id, grant_id, authenticated_owner_id),
        )
        return cursor.rowcount == 1

    def read_approved(self, *, organization_id: str, owner_id: str,
                      project_id: str, asset_id: str, campaign_id: str,
                      now: datetime) -> dict[str, object] | None:
        if not all(_id(x) for x in (
            organization_id, owner_id, project_id, asset_id, campaign_id
        )):
            raise PermissionError("invalid owner or tenant scope")
        row = self.db.execute(
            """SELECT grant_id, approved_at, expires_at
               FROM studio_growth_owner_grants
               WHERE organization_id=? AND owner_user_id=? AND project_id=?
                 AND asset_id=? AND campaign_id=? AND action=?
                 AND schema_version=? AND revoked_at IS NULL
                 AND approved_at<=? AND expires_at>?""",
            (
                organization_id, owner_id, project_id, asset_id, campaign_id,
                ACTION, SCHEMA_VERSION, _stamp(now), _stamp(now),
            ),
        ).fetchone()
        if row is None:
            return None
        return {
            "organization_id": organization_id,
            "owner_id": owner_id,
            "project_id": project_id,
            "asset_id": asset_id,
            "approved": True,
            "action": ACTION,
        }
