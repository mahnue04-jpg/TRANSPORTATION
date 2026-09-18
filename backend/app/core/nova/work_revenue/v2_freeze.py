"""Financial and work mutation freeze for archived/closed/cancelled entities."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.models import NovaWorkEngagement, NovaWorkOpportunity, NovaWorkRevenueEntry
from app.core.nova.work_revenue.service import NovaWorkError, _owner_filter

FROZEN_ENGAGEMENT = frozenset({"ARCHIVED", "CANCELLED"})
FROZEN_OPPORTUNITY = frozenset({"CLOSED"})
FROZEN_REVENUE = frozenset({"CANCELLED", "WRITTEN_OFF"})
FROZEN_SERIES = frozenset({"PAUSED", "ARCHIVED"})

FREEZE_MESSAGE = "Frozen ARCHIVED/CLOSED/CANCELLED work cannot accept ordinary financial mutation"


def _org_query(db: Session, model, organization_id: str, user: UserContext):
    return _owner_filter(
        db.query(model).filter(model.organization_id == organization_id),
        model,
        user,
    )


def engagement_is_frozen(row: NovaWorkEngagement | None) -> bool:
    return row is not None and str(row.status or "").upper() in FROZEN_ENGAGEMENT


def opportunity_is_frozen(row: NovaWorkOpportunity | None) -> bool:
    if row is None:
        return False
    return bool(row.archived) or str(row.status or "").upper() in FROZEN_OPPORTUNITY


def revenue_is_frozen(row: NovaWorkRevenueEntry | None) -> bool:
    return row is not None and str(row.stage or "").upper() in FROZEN_REVENUE


def get_engagement(
    db: Session, engagement_id: str | None, *, organization_id: str, user: UserContext
) -> NovaWorkEngagement | None:
    if not engagement_id:
        return None
    return (
        _org_query(db, NovaWorkEngagement, organization_id, user)
        .filter(NovaWorkEngagement.engagement_id == engagement_id)
        .first()
    )


def get_opportunity(
    db: Session, opportunity_id: str | None, *, organization_id: str, user: UserContext
) -> NovaWorkOpportunity | None:
    if not opportunity_id:
        return None
    return (
        _org_query(db, NovaWorkOpportunity, organization_id, user)
        .filter(NovaWorkOpportunity.opportunity_id == opportunity_id)
        .first()
    )


def assert_engagement_not_frozen(row: NovaWorkEngagement | dict[str, Any] | None) -> None:
    status = ""
    if row is None:
        return
    if isinstance(row, dict):
        status = str(row.get("status") or "")
    else:
        status = str(getattr(row, "status", "") or "")
    if status.upper() in FROZEN_ENGAGEMENT:
        raise NovaWorkError(FREEZE_MESSAGE, status_code=409)


def assert_opportunity_not_frozen(row: NovaWorkOpportunity | None) -> None:
    if opportunity_is_frozen(row):
        raise NovaWorkError(FREEZE_MESSAGE, status_code=409)


def assert_ref_not_frozen(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    ref_type: str | None = None,
    ref_id: str | None = None,
    engagement_id: str | None = None,
    opportunity_id: str | None = None,
    entry: NovaWorkRevenueEntry | None = None,
) -> None:
    if entry is not None:
        if revenue_is_frozen(entry):
            raise NovaWorkError(FREEZE_MESSAGE, status_code=409)
        engagement_id = engagement_id or entry.engagement_id
        opportunity_id = opportunity_id or entry.opportunity_id
    token = str(ref_type or "").strip().lower()
    if token in {"engagement", "nova_work_engagement"} and ref_id:
        engagement_id = engagement_id or ref_id
    if token in {"opportunity", "nova_work_opportunity"} and ref_id:
        opportunity_id = opportunity_id or ref_id
    engagement = get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    if engagement_id and engagement is None:
        raise NovaWorkError("Engagement not found", status_code=404)
    assert_engagement_not_frozen(engagement)
    if engagement and engagement.opportunity_id:
        opportunity_id = opportunity_id or engagement.opportunity_id
    opportunity = get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
    if opportunity_id and opportunity is None:
        raise NovaWorkError("Opportunity not found", status_code=404)
    assert_opportunity_not_frozen(opportunity)
