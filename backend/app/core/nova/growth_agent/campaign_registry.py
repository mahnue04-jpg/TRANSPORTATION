"""Growth campaign asset review registry (staging proposal; no auto-schema).

Stores opaque metadata only. A submitted asset reference is NOT proof it exists
in Creative Studio or has owner approval. Records remain verification_pending
until a future verified Studio service adapter is separately implemented.
No lead creation, ads, messages, provider calls, or automatic publication.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
TABLE = "nova_ga_campaign_asset_reviews"


class CampaignRegistryDenied(PermissionError):
    pass


def _id(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise CampaignRegistryDenied("invalid opaque campaign identifier")
    return value


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class CampaignReviewRegistry:
    """Synchronous scoped repository. Table must be provisioned separately.

    db is a SQLAlchemy Session; this class never runs DDL. Its callers must
    authenticate the owner and derive the tenant from the server's session.
    """

    def __init__(self, db):
        self.db = db

    def _row(self, org: str, campaign_id: str):
        return self.db.execute(text(
            "SELECT id, organization_id, owner_user_id, campaign_id, "
            "studio_project_id, asset_id, status, created_at, updated_at "
            f"FROM {TABLE} WHERE organization_id=:org AND campaign_id=:campaign"
        ), {"org": org, "campaign": campaign_id}).mappings().first()

    @staticmethod
    def _public(row):
        if row is None:
            return None
        return {
            "id": row["id"], "organization_id": row["organization_id"],
            "campaign_id": row["campaign_id"],
            "studio_project_id": row["studio_project_id"],
            "asset_id": row["asset_id"], "status": row["status"],
            "studio_verified": False, "publishing_enabled": False,
            "published": False, "messages_sent": False,
            "outbound_messages_sent": False, "lead_created": False,
            "billing_triggered": False,
        }

    def register(self, *, org: str, owner_id: str, campaign_id: str,
                 project_id: str, asset_id: str):
        org, owner_id, campaign_id, project_id, asset_id = (
            _id(v) for v in (org, owner_id, campaign_id, project_id, asset_id)
        )
        existing = self._row(org, campaign_id)
        if existing is not None:
            if (existing["owner_user_id"] != owner_id
                    or existing["studio_project_id"] != project_id
                    or existing["asset_id"] != asset_id):
                raise CampaignRegistryDenied("campaign id collision")
            # A withdrawn record cannot be reopened by a repeated request.
            if existing["status"] == "withdrawn":
                raise CampaignRegistryDenied("withdrawn campaign cannot be replayed")
            return self._public(existing), "duplicate"
        now = _stamp()
        try:
            self.db.execute(text(
                f"INSERT INTO {TABLE} (id, organization_id, owner_user_id, "
                "campaign_id, studio_project_id, asset_id, status, created_at, updated_at) "
                "VALUES (:id, :org, :owner, :campaign, :project, :asset, :status, :now, :now)"
            ), {
                "id": uuid4().hex, "org": org, "owner": owner_id,
                "campaign": campaign_id, "project": project_id,
                "asset": asset_id, "status": "verification_pending", "now": now,
            })
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise CampaignRegistryDenied("concurrent campaign conflict; retry review") from exc
        return self._public(self._row(org, campaign_id)), "recorded"

    def list_for_owner(self, *, org: str, owner_id: str, limit: int = 50):
        org, owner_id = _id(org), _id(owner_id)
        if type(limit) is not int or limit < 1 or limit > 100:
            raise CampaignRegistryDenied("invalid listing limit")
        rows = self.db.execute(text(
            f"SELECT id, organization_id, owner_user_id, campaign_id, studio_project_id, "
            f"asset_id, status, created_at, updated_at FROM {TABLE} "
            "WHERE organization_id=:org AND owner_user_id=:owner "
            "ORDER BY created_at DESC LIMIT :limit"
        ), {"org": org, "owner": owner_id, "limit": limit}).mappings().all()
        return [self._public(row) for row in rows]

    def withdraw(self, *, org: str, owner_id: str, campaign_id: str):
        org, owner_id, campaign_id = _id(org), _id(owner_id), _id(campaign_id)
        row = self._row(org, campaign_id)
        if row is None or row["owner_user_id"] != owner_id:
            raise CampaignRegistryDenied("campaign not found for owner")
        if row["status"] == "withdrawn":
            return self._public(row), "duplicate"
        self.db.execute(text(
            f"UPDATE {TABLE} SET status='withdrawn', updated_at=:now "
            "WHERE organization_id=:org AND owner_user_id=:owner "
            "AND campaign_id=:campaign AND status='verification_pending'"
        ), {
            "now": _stamp(), "org": org, "owner": owner_id,
            "campaign": campaign_id,
        })
        self.db.commit()
        return self._public(self._row(org, campaign_id)), "withdrawn"
