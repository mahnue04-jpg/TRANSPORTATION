"""Nova V2 Today aggregator. Reads V1 dashboards. Writes only nova_v2_command_actions."""
from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_SUPERVISOR,
    UserContext,
    normalize_role,
)
from app.core.nova.business.schemas import NovaBizTaskCreate
from app.core.nova.business.service import create_task as create_business_task
from app.core.nova.business.service import dashboard as business_dashboard
from app.core.nova.communications.schemas import NovaCommsDraftCreate
from app.core.nova.communications.service import create_draft as create_communications_draft
from app.core.nova.communications.service import dashboard as communications_dashboard
from app.core.nova.government.service import dashboard as government_dashboard
from app.core.nova.service import NovaCoreService
from app.core.nova.today.live_tools import (
    asks_for_name,
    extract_location_statement,
    extract_name_statement,
    extract_news_query,
    extract_weather_location,
    extract_known_site,
    extract_web_query,
    fetch_news,
    fetch_web_search,
    fetch_weather,
    format_news,
    format_weather,
    format_web_search,
    is_news_request,
    is_weather_request,
    is_web_search_capability_question,
    is_web_search_request,
    read_user_profile,
    update_user_profile,
)
from app.core.nova.today.links import (
    is_standing_synthetic,
    is_workflow_fixture,
    prior_status_for,
    result_type_for,
    source_details,
    source_href,
)
from app.core.nova.today.db_recovery import recover_today_session
from app.core.nova.today.mailbox import ConnectorHealth, MailboxItem, read_mailbox
from app.core.nova.today.models import NovaV2CommandAction, NovaV2RecheckEvent
from app.core.nova.today.readiness import beta_readiness_checklist
from app.core.nova.today.verify import verification_label, verify_result
from app.core.nova.today.schemas import (
    RECOMMENDED_ACTIONS,
    SNOOZE_HOURS,
    TRUST_LABELS,
    NovaTodayActionCreate,
    NovaTodayActionOut,
    NovaTodayApproveOut,
    NovaTodayApproveRequest,
    NovaTodayBrainOut,
    NovaTodayBrainRequest,
    NovaTodayCard,
    NovaTodayDashboardOut,
    NovaTodayHistoryItem,
    NovaTodayMailboxItemOut,
    NovaTodayMailboxOut,
    NovaTodayReadinessOut,
    NovaTodayRecheckOut,
    NovaTodayProductCount,
    NovaTodaySourceHealth,
)
from app.core.nova.workspace.service import dashboard as workspace_dashboard
from app.core.nova.work_revenue.capability_first_discovery import targeted_queries_for_request
from app.core.nova.v3.autopilot_cycle import run_autopilot_cycle
from app.core.nova.v3.multi_source_discovery import search_multi_source_jobs
from app.core.nova.v3.live_qualification import OUTCOME_QUALIFIED, qualify_and_rank_live_jobs
from app.core.nova.v3.work_revenue_bridge import persist_ranked_jobs, reset_live_discovery_opportunities
from app.helpers import now, uuid4
from app.db.models import User as PlatformUser
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class NovaTodayError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _new_id() -> str:
    return "NV2-" + uuid4().replace("-", "")[:12].upper()


def _can_see_org_wide(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}


_HEALTH_DELIVERY_COUNT_ROLES = {
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_ANALYTICS_READONLY,
}
_FREIGHT_COUNT_ROLES = {
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_RIDER,
    ROLE_PROVIDER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
}
_PRODUCT_COUNT_SPECS = (
    {
        "key": "health",
        "label": "AMICOR Health",
        "metric": "Active rides",
        "href": "/workspace",
        "roles": _HEALTH_DELIVERY_COUNT_ROLES,
    },
    {
        "key": "delivery",
        "label": "AMICOR Delivery",
        "metric": "Open requests",
        "href": "/app",
        "roles": _HEALTH_DELIVERY_COUNT_ROLES,
    },
    {
        "key": "freight",
        "label": "AMICOR Nova Freight",
        "metric": "Active shipments",
        "href": "/nova/freight",
        "roles": _FREIGHT_COUNT_ROLES,
    },
)


def _product_count_card(spec: dict, *, count: int | None, status: str) -> NovaTodayProductCount:
    return NovaTodayProductCount(
        key=spec["key"],
        label=spec["label"],
        metric=spec["metric"],
        count=count,
        status=status,
        href=spec["href"],
        trust_label="VERIFIED DATA",
    )


def _count_health_active_rides(db: Session, organization_id: str) -> int:
    from app.modules.health_isf.service import get_all_rides

    return len(
        get_all_rides(
            db,
            skip=0,
            limit=500,
            organization_id=organization_id,
            active_only=True,
            exclude_test=True,
        )
    )


def _count_delivery_open_requests(db: Session, organization_id: str) -> int:
    from app.modules.health_isf.service import get_customer_ride_queue_metrics

    metrics = get_customer_ride_queue_metrics(db, organization_id=organization_id)
    open_count = int(metrics.get("total") or 0) - int(metrics.get("completed") or 0) - int(metrics.get("cancelled") or 0)
    return max(open_count, 0)


def _count_freight_active_shipments(db: Session, organization_id: str) -> int:
    from app.core.nova.freight.service import list_shipments

    return len(list_shipments(db, organization_id=organization_id, scope="active"))


def _read_one_product_count(db: Session, *, organization_id: str, user: UserContext, spec: dict) -> NovaTodayProductCount:
    try:
        if normalize_role(user.role) not in spec["roles"]:
            return _product_count_card(spec, count=None, status="unavailable")
        counters = {
            "health": _count_health_active_rides,
            "delivery": _count_delivery_open_requests,
            "freight": _count_freight_active_shipments,
        }
        count = counters[spec["key"]](db, organization_id)
        return _product_count_card(spec, count=int(count), status="ok")
    except Exception:
        recover_today_session(db)
        return _product_count_card(spec, count=None, status="unavailable")


def _hide_frozen_products(db: Session, organization_id: str) -> bool:
    try:
        from app.core.nova.signup.isolation import is_nova_saas_customer_org

        return is_nova_saas_customer_org(db, organization_id)
    except Exception:
        return False


def product_counts(db: Session, *, organization_id: str, user: UserContext) -> list[NovaTodayProductCount]:
    specs = () if _hide_frozen_products(db, organization_id) else _PRODUCT_COUNT_SPECS
    return [
        _read_one_product_count(db, organization_id=organization_id, user=user, spec=spec)
        for spec in specs
    ]


def _owner_filter(query, user: UserContext):
    if _can_see_org_wide(user):
        return query
    return query.filter(NovaV2CommandAction.owner_user_id == user.user_id)


_SOURCE_LABELS = {
    "communications": "Nova Communications",
    "government": "Nova Government / Compliance",
    "business": "Nova Business / Operations",
    "workspace": "Nova Workspace",
    "work_revenue": "Nova Work & Revenue",
    "link": "Product shortcut",
}


def priority_band(priority: int) -> str:
    if int(priority or 0) >= 85:
        return "critical"
    if int(priority or 0) >= 70:
        return "high"
    if int(priority or 0) >= 50:
        return "normal"
    return "low"


def _maybe_autonomy_ledger(
    db: Session,
    *,
    user: UserContext,
    organization_id: str,
    action,
    result: str,
    verification_result: str | None = None,
    executed: bool = True,
) -> None:
    try:
        from app.core.nova.autonomy.executor import record_today_wrapper

        record_today_wrapper(
            db,
            user=user,
            organization_id=organization_id,
            action_type=action.recommended_action,
            source_module=action.source_module,
            source_ref_id=action.source_ref_id,
            today_action_id=action.action_id,
            result_ref_id=getattr(action, "result_ref_id", None),
            result=result,
            verification_result=verification_result,
            executed=executed,
        )
    except Exception:
        return


def action_consequences(recommended_action: str) -> tuple[str, str, str]:
    if recommended_action == "open_link":
        return (
            "Open the existing record so you can review it yourself.",
            "Nova returns a safe in-app link. No new product record is created.",
            "No email send, government filing, payment, Stripe charge, ledger post, or phone call.",
        )
    if recommended_action == "create_draft":
        return (
            "Prepare a Communications draft for you to edit. Sending stays a separate Communications step.",
            "A draft is saved in Nova Communications. Nothing is sent.",
            "No email send, filing, payment, Stripe charge, ledger post, or phone call.",
        )
    if recommended_action == "create_task":
        return (
            "Create a Business follow-up task you can track later.",
            "A Business task is created. This is not accounting, payroll, or a filing.",
            "No email send, government filing, payment, Stripe charge, ledger post, or phone call.",
        )
    if recommended_action == "acknowledge":
        return (
            "Mark that you have seen this item. No external action is taken.",
            "The item is recorded as acknowledged on Nova Today.",
            "No email send, filing, payment, Stripe charge, ledger post, or phone call.",
        )
    if recommended_action == "recheck_source":
        return (
            "Re-read the authorized connector or re-verify a saved draft/task reference.",
            "Nova refreshes connector/source health and verification status only.",
            "No send, recreate, edit, payment, Stripe charge, ledger post, call, submit, delete, or filing.",
        )
    return (
        "This action is not supported on Nova Today.",
        "Nothing will be executed.",
        "No email send, filing, payment, Stripe charge, ledger post, or phone call.",
    )


def action_out(
    row: NovaV2CommandAction,
    *,
    resolved_href: str | None = None,
    use_resolved: bool = False,
    details: dict[str, str] | None = None,
    related: list[NovaTodayHistoryItem] | None = None,
    verification_status: str | None = None,
) -> NovaTodayActionOut:
    why, if_approved, will_not = action_consequences(row.recommended_action)
    href = resolved_href if use_resolved else (resolved_href or row.href)
    result = result_type_for(row)
    verify_state = verification_status
    from app.core.nova.autonomy.policy import labels_for

    labels = labels_for(row.recommended_action, row.status)
    return NovaTodayActionOut(
        action_id=row.action_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        source_module=row.source_module,
        source_ref_id=row.source_ref_id,
        title=row.title,
        detail=row.detail,
        explanation=row.detail,
        source_label=_SOURCE_LABELS.get(row.source_module, row.source_module),
        href=href,
        trust_label=row.trust_label,
        priority=row.priority,
        priority_band=priority_band(row.priority),
        status=row.status,
        recommended_action=row.recommended_action,
        risk_class=labels["risk_class"],
        approval_state=labels["approval_state"],
        execution_state=labels["execution_state"],
        why_recommended=why,
        if_approved=if_approved,
        will_not_happen=will_not,
        result_ref_id=row.result_ref_id,
        created_at=row.created_at,
        decided_at=row.decided_at,
        snoozed_until=row.snoozed_until,
        prior_status=prior_status_for(row),
        resulting_status=row.status,
        result_type=result,
        actor_user_id=row.owner_user_id,
        source_href=resolved_href if use_resolved else resolved_href,
        source_details=details,
        related_history=related or [],
        why_surfaced=why,
        verification_status=verify_state,
        verification_label=verification_label(result, verify_state) if verify_state else None,
    )


def history_item(
    row: NovaV2CommandAction,
    *,
    resolved_href: str | None = None,
    verification_status: str | None = None,
    prior_verification_status: str | None = None,
) -> NovaTodayHistoryItem:
    result = result_type_for(row)
    return NovaTodayHistoryItem(
        action_id=row.action_id,
        source_module=row.source_module,
        source_ref_id=row.source_ref_id,
        title=row.title,
        prior_status=prior_status_for(row),
        resulting_status=row.status,
        result_ref_id=row.result_ref_id,
        actor_user_id=row.owner_user_id,
        decided_at=row.decided_at,
        trust_label=row.trust_label,
        recommended_action=row.recommended_action,
        result_type=result,
        source_href=resolved_href,
        verification_status=verification_status,
        verification_label=verification_label(result, verification_status) if verification_status else None,
        prior_verification_status=prior_verification_status,
    )


def _resolved_source_href(
    db: Session,
    row: NovaV2CommandAction,
    *,
    organization_id: str,
    user: UserContext,
) -> str | None:
    return source_href(
        db,
        source_module=row.source_module,
        source_ref_id=row.source_ref_id,
        organization_id=organization_id,
        user=user,
    )


def list_history(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int = 20,
) -> list[NovaTodayHistoryItem]:
    rows = [
        row
        for row in _list_actions(db, organization_id=organization_id, user=user)
        if row.status != "proposed" and row.decided_at is not None
    ]
    rows.sort(key=lambda row: row.decided_at or row.created_at, reverse=True)
    items: list[NovaTodayHistoryItem] = []
    for row in rows[:limit]:
        items.append(
            history_item(
                row,
                resolved_href=_resolved_source_href(
                    db, row, organization_id=organization_id, user=user
                ),
                verification_status=verify_result(
                    db, row, organization_id=organization_id, user=user
                ),
            )
        )
    for event in list_recheck_events(db, organization_id=organization_id, user=user, limit=limit):
        items.append(_recheck_history_item(event))
    items.sort(key=lambda item: item.decided_at or item.action_id, reverse=True)
    return items[:limit]


_MODULE_RANK = {
    "government": 8,
    "communications": 6,
    "business": 5,
    "workspace": 2,
    "link": 0,
}


def rank_score(card: NovaTodayCard) -> int:
    """Phase 2 richer ranking: keep V1 priority, boost overdue / grants / important."""
    score = int(card.priority or 0)
    title = str(card.title or "").lower()
    if title.startswith("overdue"):
        score += 20
    elif title.startswith("grant deadline"):
        score += 10
    elif title.startswith("important"):
        score += 8
    score += _MODULE_RANK.get(card.source_module, 0)
    return score


def _is_active_snooze(row: NovaV2CommandAction, *, at=None) -> bool:
    if str(row.status or "") != "snoozed":
        return False
    until = row.snoozed_until
    if until is None:
        return False
    current = at or now()
    if until.tzinfo is None and getattr(current, "tzinfo", None) is not None:
        until = until.replace(tzinfo=current.tzinfo)
    return until > current


def _card(
    *,
    source_module: str,
    source_ref_id: str,
    title: str,
    detail: str | None,
    href: str | None,
    trust_label: str,
    priority: int,
    recommended_action: str,
    explanation: str | None = None,
    sender: str | None = None,
    subject: str | None = None,
    received_at=None,
    source_href: str | None = None,
    source_label: str | None = None,
    unread: bool | None = None,
    important: bool | None = None,
    provider: str | None = None,
    connector_status: str | None = None,
) -> NovaTodayCard:
    why, if_approved, will_not = action_consequences(recommended_action)
    from app.core.nova.autonomy.policy import labels_for

    labels = labels_for(recommended_action)
    return NovaTodayCard(
        source_module=source_module,
        source_ref_id=source_ref_id,
        title=title,
        detail=detail,
        explanation=explanation or detail,
        source_label=source_label or _SOURCE_LABELS.get(source_module, source_module),
        sender=sender,
        subject=subject,
        href=href,
        trust_label=trust_label,
        priority=priority,
        priority_band=priority_band(priority),
        recommended_action=recommended_action,
        risk_class=labels["risk_class"],
        approval_state=labels["approval_state"],
        execution_state=labels["execution_state"],
        why_recommended=why,
        if_approved=if_approved,
        will_not_happen=will_not,
        received_at=received_at,
        source_href=source_href,
        unread=unread,
        important=important,
        provider=provider,
        connector_status=connector_status,
    )


def _list_actions(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    include_deactivated: bool = True,
) -> list[NovaV2CommandAction]:
    query = db.query(NovaV2CommandAction).filter(NovaV2CommandAction.organization_id == organization_id)
    if not include_deactivated:
        query = query.filter(NovaV2CommandAction.status != "deactivated")
    return _owner_filter(query, user).order_by(NovaV2CommandAction.priority.desc(), NovaV2CommandAction.created_at.desc()).all()


def find_in_org_today_action(
    db: Session,
    *,
    organization_id: str,
    source_module: str,
    source_ref_id: str,
    recommended_action: str,
) -> NovaV2CommandAction | None:
    """Reuse the oldest in-org logical Today row. Owner is not part of this key.

    Exception: V2 create/upsert still writes owner-scoped unique rows for
    user-specific mailbox/task items when no in-org match exists yet.
    Standing org-wide cards omit owner from the uniqueness check.
    """
    return (
        db.query(NovaV2CommandAction)
        .filter(
            NovaV2CommandAction.organization_id == organization_id,
            NovaV2CommandAction.source_module == source_module,
            NovaV2CommandAction.source_ref_id == source_ref_id,
            NovaV2CommandAction.recommended_action == recommended_action,
            NovaV2CommandAction.status != "deactivated",
        )
        .order_by(NovaV2CommandAction.created_at.asc())
        .first()
    )


def get_in_org_today_action_by_id(
    db: Session,
    action_id: str,
    *,
    organization_id: str,
) -> NovaV2CommandAction | None:
    """Load a Today row by id within the organization. Owner is not required."""
    return (
        db.query(NovaV2CommandAction)
        .filter(
            NovaV2CommandAction.action_id == action_id,
            NovaV2CommandAction.organization_id == organization_id,
        )
        .first()
    )


def _get_action(db: Session, action_id: str, *, organization_id: str, user: UserContext) -> NovaV2CommandAction:
    query = db.query(NovaV2CommandAction).filter(
        NovaV2CommandAction.action_id == action_id,
        NovaV2CommandAction.organization_id == organization_id,
    )
    row = _owner_filter(query, user).first()
    if row is None:
        raise NovaTodayError("Today action not found", status_code=404)
    return row


def _logical_key(item) -> tuple[str, str, str]:
    return (
        str(getattr(item, "source_module", None) or ""),
        str(getattr(item, "source_ref_id", None) or ""),
        str(getattr(item, "recommended_action", None) or ""),
    )


def _is_workflow_fixture_item(item) -> bool:
    return is_workflow_fixture(getattr(item, "title", None), getattr(item, "source_ref_id", None))


def _dedupe_logical(items: list):
    """Keep one item per logical key inside a single section. Oldest / first wins."""
    seen: set[tuple[str, str, str]] = set()
    kept = []
    for item in items:
        key = _logical_key(item)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _canonical_action_map(rows: list[NovaV2CommandAction]) -> dict[tuple[str, str, str], NovaV2CommandAction]:
    """Prefer the oldest in-org row for standing cards; otherwise first seen."""
    ordered = sorted(rows, key=lambda row: (row.created_at is None, row.created_at or row.action_id, row.action_id))
    keyed: dict[tuple[str, str, str], NovaV2CommandAction] = {}
    for row in ordered:
        if str(row.status or "") == "deactivated":
            continue
        key = (row.source_module, row.source_ref_id, row.recommended_action)
        if key in keyed and not is_standing_synthetic(row.source_module, row.source_ref_id):
            continue
        keyed.setdefault(key, row)
    return keyed


def _upsert_proposed(
    db: Session,
    card: NovaTodayCard,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaV2CommandAction:
    standing = is_standing_synthetic(card.source_module, card.source_ref_id)
    if standing:
        existing = find_in_org_today_action(
            db,
            organization_id=organization_id,
            source_module=card.source_module,
            source_ref_id=card.source_ref_id,
            recommended_action=card.recommended_action,
        )
    else:
        existing = (
            db.query(NovaV2CommandAction)
            .filter(
                NovaV2CommandAction.organization_id == organization_id,
                NovaV2CommandAction.owner_user_id == user.user_id,
                NovaV2CommandAction.source_module == card.source_module,
                NovaV2CommandAction.source_ref_id == card.source_ref_id,
                NovaV2CommandAction.recommended_action == card.recommended_action,
            )
            .first()
        )
    if existing is not None:
        if existing.status == "snoozed" and _is_active_snooze(existing):
            return existing
        if existing.status == "snoozed" and not _is_active_snooze(existing):
            existing.status = "proposed"
            existing.snoozed_until = None
            existing.decided_at = None
        if existing.status == "proposed":
            existing.title = card.title
            existing.detail = card.detail
            existing.href = card.href
            existing.trust_label = "ACTION REQUIRES APPROVAL"
            existing.priority = card.priority
        return existing
    row = NovaV2CommandAction(
        action_id=_new_id(),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        source_module=card.source_module,
        source_ref_id=card.source_ref_id,
        title=card.title,
        detail=card.detail,
        href=card.href,
        trust_label="ACTION REQUIRES APPROVAL",
        priority=card.priority,
        status="proposed",
        recommended_action=card.recommended_action,
    )
    db.add(row)
    return row


def _attach_action(card: NovaTodayCard, rows: dict[tuple[str, str, str], NovaV2CommandAction]) -> NovaTodayCard:
    row = rows.get((card.source_module, card.source_ref_id, card.recommended_action))
    if row is None:
        return card
    card.action_id = row.action_id
    card.status = row.status
    if row.status == "proposed":
        card.trust_label = "ACTION REQUIRES APPROVAL"
    return card


def _safe_source(db: Session, loader):
    try:
        return loader(), "ok"
    except Exception:
        recover_today_session(db)
        return None, "unavailable"


def _health(
    source: str,
    status: str,
    *,
    count: int = 0,
    connector: str = "n/a",
    email_connected: bool | None = None,
    last_sync_at=None,
    mailbox_status: str | None = None,
) -> NovaTodaySourceHealth:
    connector_state = mailbox_status or connector
    if status == "unavailable":
        return NovaTodaySourceHealth(
            source=source,
            status="unavailable",
            detail="This Nova source is unavailable. Today did not invent records.",
            connector="unavailable" if mailbox_status == "unavailable" else ("n/a" if connector == "n/a" else mailbox_status or connector),
            last_sync_at=last_sync_at,
        )
    if source == "communications" and email_connected is not None:
        if mailbox_status in {"connected", "degraded", "stale", "unavailable", "disconnected"}:
            connector_value = mailbox_status
        elif email_connected:
            connector_value = "connected"
        else:
            connector_value = "not_configured"
        if email_connected and count > 0:
            return NovaTodaySourceHealth(
                source=source,
                status="ok" if connector_value in {"connected", "degraded"} else "partial",
                detail=f"{count} real items from the connected mailbox or saved messages.",
                connector=connector_value,
                last_sync_at=last_sync_at,
            )
        if email_connected and count == 0:
            return NovaTodaySourceHealth(
                source=source,
                status="empty",
                detail="Mailbox connector is present. No unread or important messages were invented.",
                connector=connector_value,
                last_sync_at=last_sync_at,
            )
        if not email_connected and count > 0:
            not_configured = connector_value == "not_configured"
            return NovaTodaySourceHealth(
                source=source,
                status="partial",
                detail=(
                    "Local saved messages only. Gmail/Outlook has never been connected. This is not an error."
                    if not_configured
                    else "Local saved messages only. No mailbox connector is connected."
                ),
                connector=connector_value if connector_value != "n/a" else "not_configured",
                last_sync_at=last_sync_at,
            )
        return NovaTodaySourceHealth(
            source=source,
            status="empty",
            detail=(
                "Mailbox is not configured. Gmail/Outlook has never been connected for this owner. This is not an error."
                if connector_value == "not_configured"
                else "No mailbox connector. No saved messages were invented."
            ),
            connector=connector_value if connector_value != "n/a" else "not_configured",
            last_sync_at=last_sync_at,
        )
    if count == 0:
        return NovaTodaySourceHealth(
            source=source,
            status="empty",
            detail="No real records in this source today.",
            connector=connector,
            last_sync_at=last_sync_at,
        )
    return NovaTodaySourceHealth(
        source=source,
        status="ok",
        detail=f"{count} real items.",
        connector=connector,
        last_sync_at=last_sync_at,
    )


def _collect_v1_cards(db: Session, *, organization_id: str, user: UserContext) -> dict[str, list[NovaTodayCard]]:
    mailbox_items: list[MailboxItem] = []
    mailbox_health = ConnectorHealth(
        status="n/a",
        detail="Mailbox connector was not checked.",
    )
    try:
        mailbox_items, mailbox_health = read_mailbox(
            db, organization_id=organization_id, user=user, persist=True
        )
    except PermissionError:
        recover_today_session(db)
        mailbox_health = ConnectorHealth(
            status="unavailable",
            detail="Cross-owner or cross-org connector access is denied.",
        )
    except Exception:
        recover_today_session(db)
        mailbox_health = ConnectorHealth(
            status="unavailable",
            detail="Mailbox connector is unavailable. Today did not invent messages.",
        )
    workspace, workspace_status = _safe_source(
        db, lambda: workspace_dashboard(db, organization_id=organization_id, user=user)
    )
    communications, comms_status = _safe_source(
        db, lambda: communications_dashboard(db, organization_id=organization_id, user=user)
    )
    government, gov_status = _safe_source(
        db, lambda: government_dashboard(db, organization_id=organization_id, user=user)
    )
    business, biz_status = _safe_source(
        db, lambda: business_dashboard(db, organization_id=organization_id, user=user)
    )

    comms_cards: list[NovaTodayCard] = []
    seen_messages: set[str] = set()
    email_connected = bool(getattr(communications, "email_connected", False)) if communications is not None else False
    email_connected = email_connected or mailbox_health.status in {"connected", "degraded", "stale"}
    if communications is not None:
        for row in list(communications.important) + list(communications.inbox):
            if row.message_id in seen_messages:
                continue
            if not row.important and row.read:
                continue
            seen_messages.add(row.message_id)
            label = "Important" if row.important else "Unread"
            connector_backed = email_connected and str(getattr(row, "source", "local") or "local") != "local"
            comms_cards.append(
                _card(
                    source_module="communications",
                    source_ref_id=row.message_id,
                    title=f"{label}: {row.subject}",
                    detail=row.snippet or row.sender,
                    explanation=f"From {row.sender}. {row.snippet or 'Saved message. Prepare a draft only.'}",
                    href="/nova/communications",
                    source_href="/nova/communications",
                    trust_label="USER-SAVED INFORMATION",
                    priority=82 if row.important else 75,
                    recommended_action="create_draft",
                    sender=row.sender,
                    subject=row.subject,
                    received_at=row.created_at,
                    source_label="Connected mailbox" if connector_backed else "Nova saved message",
                    unread=not bool(row.read),
                    important=bool(row.important),
                    provider=str(getattr(row, "source", "local") or "local"),
                    connector_status=mailbox_health.status if connector_backed else "n/a",
                )
            )
        for row in communications.today:
            comms_cards.append(
                _card(
                    source_module="communications",
                    source_ref_id=row.event_id,
                    title=f"Today: {row.title}",
                    detail=row.location,
                    explanation=row.location or "Calendar item saved in Nova Communications.",
                    href="/nova/communications",
                    source_href="/nova/communications",
                    trust_label="USER-SAVED INFORMATION",
                    priority=60,
                    recommended_action="open_link",
                    subject=row.title,
                    received_at=row.start_time,
                    source_label="Connected calendar" if getattr(communications, "calendar_connected", False) else "Nova saved calendar",
                )
            )
        for row in communications.drafts[:6]:
            comms_cards.append(
                _card(
                    source_module="communications",
                    source_ref_id=row.draft_id,
                    title=f"Draft: {row.subject}",
                    detail="Saved draft. Nothing was sent.",
                    explanation="This is a saved Communications draft. Nova Today will not send it.",
                    href="/nova/communications",
                    source_href="/nova/communications",
                    trust_label="USER-SAVED INFORMATION",
                    priority=55,
                    recommended_action="open_link",
                    subject=row.subject,
                    source_label="Nova saved draft",
                )
            )
    if mailbox_items:
        seen_mailbox = {card.source_ref_id for card in comms_cards}
        for item in mailbox_items:
            ref = item.message_id or item.external_message_id
            if not ref or ref in seen_mailbox:
                continue
            label = "Important" if item.important else "Unread"
            comms_cards.append(
                _card(
                    source_module="communications",
                    source_ref_id=ref,
                    title=f"{label}: {item.subject}",
                    detail=item.snippet or item.sender,
                    explanation=f"From {item.sender}. {item.snippet or 'Connector message. Prepare a draft only.'}",
                    href="/nova/communications",
                    source_href=item.source_href,
                    trust_label="USER-SAVED INFORMATION",
                    priority=82 if item.important else 75,
                    recommended_action="create_draft",
                    sender=item.sender,
                    subject=item.subject,
                    received_at=item.received_at,
                    source_label="Connected mailbox",
                    unread=item.unread,
                    important=item.important,
                    provider=item.provider,
                    connector_status=mailbox_health.status,
                )
            )

    gov_cards: list[NovaTodayCard] = []
    if government is not None:
        for row in government.overdue:
            gov_cards.append(
                _card(
                    source_module="government",
                    source_ref_id=row.item_id,
                    title=f"Overdue: {row.title}",
                    detail=row.agency,
                    explanation=f"Saved compliance item is overdue{f' at {row.agency}' if row.agency else ''}. Nova will not file this.",
                    href="/nova/government",
                    source_href="/nova/government",
                    trust_label="USER-SAVED INFORMATION",
                    priority=95,
                    recommended_action="create_task",
                )
            )
        for row in government.upcoming_deadlines:
            gov_cards.append(
                _card(
                    source_module="government",
                    source_ref_id=row.item_id,
                    title=f"Deadline: {row.title}",
                    detail=f"Due {row.due_date}" if row.due_date else row.agency,
                    explanation=f"Upcoming deadline from a user-saved Government record. Due {row.due_date}." if row.due_date else "Upcoming deadline from a user-saved Government record.",
                    href="/nova/government",
                    source_href="/nova/government",
                    trust_label="USER-SAVED INFORMATION",
                    priority=78,
                    recommended_action="open_link",
                )
            )
        for row in government.renewals:
            gov_cards.append(
                _card(
                    source_module="government",
                    source_ref_id=f"{row.item_id}:renewal",
                    title=f"Renewal: {row.title}",
                    detail=f"Renewal {row.renewal_date}" if row.renewal_date else row.agency,
                    explanation="Saved renewal date. This is not a government notice invented by Nova.",
                    href="/nova/government",
                    source_href="/nova/government",
                    trust_label="USER-SAVED INFORMATION",
                    priority=74,
                    recommended_action="create_task",
                )
            )
        for row in government.programs:
            if row.deadline:
                gov_cards.append(
                    _card(
                        source_module="government",
                        source_ref_id=row.program_id,
                        title=f"Grant deadline: {row.program_name}",
                        detail=row.agency,
                        explanation="Program deadline from saved Government records. Nova will not file an application.",
                        href="/nova/government",
                        source_href="/nova/government",
                        trust_label="USER-SAVED INFORMATION",
                        priority=76,
                        recommended_action="open_link",
                    )
                )

    biz_cards: list[NovaTodayCard] = []
    if business is not None:
        for row in business.overdue_tasks:
            biz_cards.append(
                _card(
                    source_module="business",
                    source_ref_id=row.task_id,
                    title=f"Overdue task: {row.title}",
                    detail=row.notes,
                    explanation="Overdue Business task from saved workspace data.",
                    href="/nova/business",
                    source_href="/nova/business",
                    trust_label="USER-SAVED INFORMATION",
                    priority=88,
                    recommended_action="open_link",
                )
            )
        for row in business.follow_ups_due:
            biz_cards.append(
                _card(
                    source_module="business",
                    source_ref_id=row.customer_id,
                    title=f"Follow up: {row.name}",
                    detail=f"Next follow-up {row.next_follow_up}" if row.next_follow_up else None,
                    explanation="Saved customer follow-up. Prepare a draft only; nothing is sent.",
                    href="/nova/business",
                    source_href="/nova/business",
                    trust_label="USER-SAVED INFORMATION",
                    priority=70,
                    recommended_action="create_draft",
                    sender=row.name,
                )
            )
        for row in business.open_opportunities[:8]:
            biz_cards.append(
                _card(
                    source_module="business",
                    source_ref_id=row.opportunity_id,
                    title=f"Opportunity: {row.title}",
                    detail=row.next_action,
                    explanation=row.next_action or "Open opportunity from saved Business records.",
                    href="/nova/business",
                    source_href="/nova/business",
                    trust_label="USER-SAVED INFORMATION",
                    priority=58,
                    recommended_action="create_task",
                )
            )

    workspace_cards: list[NovaTodayCard] = []
    if workspace is not None:
        for row in workspace.recent_work[:8]:
            workspace_cards.append(
                _card(
                    source_module="workspace",
                    source_ref_id=row.activity_id,
                    title=row.title,
                    detail=row.kind,
                    explanation=f"Recent workspace activity ({row.kind}).",
                    href="/nova/workspace",
                    source_href="/nova/workspace",
                    trust_label="USER-SAVED INFORMATION",
                    priority=35,
                    recommended_action="open_link",
                )
            )
        for row in workspace.active_projects[:6]:
            workspace_cards.append(
                _card(
                    source_module="workspace",
                    source_ref_id=row.workspace_id,
                    title=f"Project: {row.title}",
                    detail=row.status,
                    explanation=f"Active project status: {row.status}.",
                    href="/nova/workspace",
                    source_href="/nova/workspace",
                    trust_label="USER-SAVED INFORMATION",
                    priority=32,
                    recommended_action="open_link",
                )
            )

    product_links = [
        _card(
            source_module="link",
            source_ref_id="health",
            title="AMICOR Health",
            detail="Open the existing Health ISF workspace. Linked, not merged.",
            href="/workspace",
            source_href="/workspace",
            trust_label="VERIFIED DATA",
            priority=12,
            recommended_action="open_link",
        ),
        _card(
            source_module="link",
            source_ref_id="delivery",
            title="AMICOR Delivery",
            detail="Open the frozen Delivery operations surface.",
            href="/app",
            source_href="/app",
            trust_label="VERIFIED DATA",
            priority=11,
            recommended_action="open_link",
        ),
        _card(
            source_module="link",
            source_ref_id="freight",
            title="AMICOR Nova Freight",
            detail="Open the frozen Freight V1 product.",
            href="/nova/freight",
            source_href="/nova/freight",
            trust_label="VERIFIED DATA",
            priority=10,
            recommended_action="open_link",
        ),
    ]
    if _hide_frozen_products(db, organization_id):
        product_links = []

    has_real_work = bool(comms_cards or gov_cards or biz_cards)
    recommendations: list[NovaTodayCard] = []
    if has_real_work:
        recommendations = [
            _card(
                source_module="business",
                source_ref_id="rec-attention",
                title="Review today's follow-ups and overdue work",
                detail="Mrs. Nova Brain suggestion from existing Business and Government records.",
                explanation="AI suggestion based on real saved records already listed on Today. Not a new deadline.",
                href="/nova/today",
                source_href=None,
                trust_label="AI SUGGESTION",
                priority=40,
                recommended_action="acknowledge",
            ),
            _card(
                source_module="communications",
                source_ref_id="rec-drafts",
                title="Keep replies in drafts until you confirm send in Communications",
                detail="Today will not send email.",
                explanation="Standing safety reminder. Approve only acknowledges this guidance.",
                href="/nova/communications",
                source_href=None,
                trust_label="AI SUGGESTION",
                priority=38,
                recommended_action="acknowledge",
            ),
        ]

    return {
        "communications": comms_cards,
        "government": gov_cards,
        "business": biz_cards,
        "workspace": workspace_cards,
        "product_links": product_links,
        "recommendations": recommendations,
        "source_health": [
            _health(
                "communications",
                comms_status,
                count=len(comms_cards),
                email_connected=email_connected if communications is not None or mailbox_health.status != "n/a" else None,
                last_sync_at=mailbox_health.last_success_at,
                mailbox_status=mailbox_health.status,
            ),
            _health("government", gov_status, count=len(gov_cards)),
            _health("business", biz_status, count=len(biz_cards)),
            _health("workspace", workspace_status, count=len(workspace_cards)),
        ],
        "email_connected": email_connected,
        "connector_health": mailbox_health.as_dict(),
        "mailbox_items": mailbox_items,
    }


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> NovaTodayDashboardOut:
    groups = _collect_v1_cards(db, organization_id=organization_id, user=user)
    persistable = (
        groups["communications"]
        + groups["government"]
        + groups["business"]
        + groups["recommendations"]
        + groups["product_links"]
    )
    for card in persistable:
        _upsert_proposed(db, card, organization_id=organization_id, user=user)
    db.commit()

    rows = _list_actions(db, organization_id=organization_id, user=user, include_deactivated=False)
    keyed = _canonical_action_map(rows)
    hidden = {
        (row.source_module, row.source_ref_id, row.recommended_action)
        for row in rows
        if row.status == "dismissed" or _is_active_snooze(row)
    }

    def visible(cards: list[NovaTodayCard]) -> list[NovaTodayCard]:
        kept: list[NovaTodayCard] = []
        for card in cards:
            key = (card.source_module, card.source_ref_id, card.recommended_action)
            if key in hidden:
                continue
            if _is_workflow_fixture_item(card):
                continue
            kept.append(_attach_action(card, keyed))
        return _dedupe_logical(sorted(kept, key=rank_score, reverse=True))

    communications = visible(groups["communications"])
    government = visible(groups["government"])
    business = visible(groups["business"])
    workspace = visible(groups["workspace"])
    product_links = visible(groups["product_links"])
    recommendations = visible(groups["recommendations"])
    attention_now = _dedupe_logical(
        sorted(
            communications + government + business + workspace,
            key=rank_score,
            reverse=True,
        )
    )[:16]
    active_recommendation_refs = {
        card.source_ref_id
        for card in groups["recommendations"]
        if str(card.source_ref_id or "").startswith("rec-")
    }
    approval_queue = []
    for row in rows:
        if row.status != "proposed":
            continue
        if _is_workflow_fixture_item(row):
            continue
        if is_standing_synthetic(row.source_module, row.source_ref_id) and row.source_module == "link":
            continue
        if str(row.source_ref_id or "").startswith("rec-") and row.source_ref_id not in active_recommendation_refs:
            continue
        if is_standing_synthetic(row.source_module, row.source_ref_id):
            canonical = keyed.get((row.source_module, row.source_ref_id, row.recommended_action))
            if canonical is None or canonical.action_id != row.action_id:
                continue
        approval_queue.append(
            action_out(
                row,
                resolved_href=_resolved_source_href(db, row, organization_id=organization_id, user=user),
                use_resolved=True,
            )
        )
    approval_queue = _dedupe_logical(approval_queue)
    recent_activity = [
        item
        for item in list_history(db, organization_id=organization_id, user=user)
        if not _is_workflow_fixture_item(item)
    ]
    try:
        counts = product_counts(db, organization_id=organization_id, user=user)
    except Exception:
        recover_today_session(db)
        specs = () if _hide_frozen_products(db, organization_id) else _PRODUCT_COUNT_SPECS
        counts = [_product_count_card(spec, count=None, status="unavailable") for spec in specs]
    return NovaTodayDashboardOut(
        attention_now=attention_now,
        communications=communications,
        government=government,
        business=business,
        workspace=workspace,
        product_links=product_links,
        product_counts=counts,
        recommendations=recommendations,
        approval_queue=approval_queue,
        recent_activity=recent_activity,
        source_health=list(groups.get("source_health") or []),
        connector_health=dict(groups.get("connector_health") or {}),
        trust_labels=list(TRUST_LABELS),
    )


def list_actions(db: Session, *, organization_id: str, user: UserContext) -> list[NovaTodayActionOut]:
    return [action_out(row) for row in _list_actions(db, organization_id=organization_id, user=user)]


def get_action(db: Session, action_id: str, *, organization_id: str, user: UserContext) -> NovaTodayActionOut:
    row = _get_action(db, action_id, organization_id=organization_id, user=user)
    resolved = _resolved_source_href(db, row, organization_id=organization_id, user=user)
    details = source_details(
        db,
        source_module=row.source_module,
        source_ref_id=row.source_ref_id,
        organization_id=organization_id,
        user=user,
    )
    related = [
        history_item(
            other,
            resolved_href=_resolved_source_href(db, other, organization_id=organization_id, user=user),
            verification_status=verify_result(
                db, other, organization_id=organization_id, user=user
            ),
        )
        for other in _list_actions(db, organization_id=organization_id, user=user)
        if other.source_ref_id == row.source_ref_id
        and other.action_id != row.action_id
        and other.status != "proposed"
        and other.decided_at is not None
    ]
    return action_out(
        row,
        resolved_href=resolved,
        use_resolved=True,
        details=details,
        related=related[:8],
        verification_status=verify_result(db, row, organization_id=organization_id, user=user),
    )


def create_action(
    db: Session,
    payload: NovaTodayActionCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaTodayActionOut:
    if payload.recommended_action not in RECOMMENDED_ACTIONS:
        raise NovaTodayError("Unsupported Today action", status_code=422)
    card = _card(
        source_module=payload.source_module,
        source_ref_id=payload.source_ref_id,
        title=payload.title,
        detail=payload.detail,
        href=payload.href or "/nova/today",
        trust_label=payload.trust_label,
        priority=payload.priority,
        recommended_action=payload.recommended_action,
    )
    row = _upsert_proposed(db, card, organization_id=organization_id, user=user)
    if row.status != "proposed":
        raise NovaTodayError("That Today item was already decided", status_code=409)
    db.commit()
    db.refresh(row)
    return action_out(row)


def dismiss_action(db: Session, action_id: str, *, organization_id: str, user: UserContext) -> NovaTodayActionOut:
    row = _get_action(db, action_id, organization_id=organization_id, user=user)
    row.status = "dismissed"
    row.decided_at = now()
    row.snoozed_until = None
    db.commit()
    db.refresh(row)
    out = action_out(row)
    _maybe_autonomy_ledger(
        db,
        user=user,
        organization_id=organization_id,
        action=out,
        result="dismissed",
        verification_result="verified",
        executed=True,
    )
    return out


def snooze_action(
    db: Session,
    action_id: str,
    *,
    organization_id: str,
    user: UserContext,
    hours: int = 24,
) -> NovaTodayActionOut:
    if hours not in SNOOZE_HOURS:
        raise NovaTodayError("Snooze hours must be 1, 4, 24, or 72.", status_code=422)
    row = _get_action(db, action_id, organization_id=organization_id, user=user)
    if row.status in {"approved", "done", "dismissed"}:
        raise NovaTodayError("Only open Today items can be snoozed.", status_code=409)
    stamp = now()
    row.status = "snoozed"
    row.decided_at = stamp
    row.snoozed_until = stamp + timedelta(hours=hours)
    db.commit()
    db.refresh(row)
    out = action_out(row)
    _maybe_autonomy_ledger(
        db,
        user=user,
        organization_id=organization_id,
        action=out,
        result=row.status,
        verification_result="verified",
        executed=True,
    )
    return out


def approve_action(
    db: Session,
    action_id: str,
    payload: NovaTodayApproveRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaTodayApproveOut:
    row = _get_action(db, action_id, organization_id=organization_id, user=user)
    if row.status == "dismissed":
        raise NovaTodayError("Dismissed Today items cannot be approved", status_code=409)
    if row.status in {"approved", "done"}:
        return NovaTodayApproveOut(
            action=action_out(
                row,
                verification_status=verify_result(db, row, organization_id=organization_id, user=user),
            ),
            href=row.href,
            draft_id=row.result_ref_id if row.recommended_action == "create_draft" else None,
            task_id=row.result_ref_id if row.recommended_action == "create_task" else None,
            message="Already approved. Nothing else was sent or filed.",
            fact_label="USER-SAVED INFORMATION",
            verification_status=verify_result(db, row, organization_id=organization_id, user=user),
        )
    if row.recommended_action == "open_link":
        row.status = "done"
        row.decided_at = now()
        db.commit()
        db.refresh(row)
        out = action_out(row)
        _maybe_autonomy_ledger(
            db, user=user, organization_id=organization_id, action=out, result="open_link", verification_result="verified"
        )
        return NovaTodayApproveOut(
            action=out,
            href=row.href,
            message="Open the existing V1 record. No new product data was created.",
            fact_label="VERIFIED DATA",
        )
    if row.recommended_action == "acknowledge":
        row.status = "done"
        row.decided_at = now()
        db.commit()
        db.refresh(row)
        out = action_out(row)
        _maybe_autonomy_ledger(
            db, user=user, organization_id=organization_id, action=out, result="acknowledged", verification_result="verified"
        )
        return NovaTodayApproveOut(
            action=out,
            message="Acknowledged. Nothing was sent, filed, or charged.",
            fact_label="USER-SAVED INFORMATION",
        )
    if row.recommended_action == "create_draft":
        subject = (payload.draft_subject or f"Follow-up: {row.title}").strip()
        body = payload.draft_body or (
            "Draft created from Nova Today.\n\nNothing was sent. Confirm send only in Communications."
        )
        draft = create_communications_draft(
            db,
            NovaCommsDraftCreate(to=payload.draft_to, subject=subject[:512], body=body),
            organization_id=organization_id,
            user=user,
        )
        row.status = "done"
        row.decided_at = now()
        row.result_ref_id = draft.id
        db.commit()
        db.refresh(row)
        verified = verify_result(db, row, organization_id=organization_id, user=user)
        out = action_out(row, verification_status=verified)
        _maybe_autonomy_ledger(
            db, user=user, organization_id=organization_id, action=out, result="draft_created", verification_result=verified
        )
        return NovaTodayApproveOut(
            action=out,
            href="/nova/communications",
            draft_id=draft.id,
            message="Communications draft saved. External send was not performed.",
            fact_label="USER-SAVED INFORMATION",
            verification_status=verified,
        )
    if row.recommended_action == "recheck_source":
        checked = recheck_source(
            db,
            organization_id=organization_id,
            user=user,
            action_id=row.action_id,
        )
        row.status = "done"
        row.decided_at = now()
        db.commit()
        db.refresh(row)
        out = action_out(row, verification_status=checked.verification_status)
        _maybe_autonomy_ledger(
            db,
            user=user,
            organization_id=organization_id,
            action=out,
            result="source_rechecked",
            verification_result=checked.verification_status,
        )
        return NovaTodayApproveOut(
            action=out,
            href=row.href,
            message=checked.message,
            fact_label="VERIFIED DATA",
            verification_status=checked.verification_status,
        )
    if row.recommended_action == "create_task":
        title = (payload.task_title or row.title).strip()
        task = create_business_task(
            db,
            NovaBizTaskCreate(title=title[:220], notes="Created from Nova Today approval."),
            organization_id=organization_id,
            user=user,
        )
        row.status = "done"
        row.decided_at = now()
        row.result_ref_id = task.task_id
        db.commit()
        db.refresh(row)
        verified = verify_result(db, row, organization_id=organization_id, user=user)
        out = action_out(row, verification_status=verified)
        _maybe_autonomy_ledger(
            db, user=user, organization_id=organization_id, action=out, result="task_created", verification_result=verified
        )
        return NovaTodayApproveOut(
            action=out,
            href="/nova/business",
            task_id=task.task_id,
            message="Business task created. This is not accounting, payroll, or a filing.",
            fact_label="USER-SAVED INFORMATION",
            verification_status=verified,
        )
    raise NovaTodayError("Unsupported Today action", status_code=422)


_TODAY_EXTERNAL_HINTS = (
    "weather",
    "forecast",
    "news",
    "headline",
    "my name",
    "i am ",
    "i'm ",
    "hello",
    "hi there",
    "good morning",
    "good afternoon",
    "good evening",
    "who are you",
    "who am i",
    "joke",
    "sports score",
    "stock price",
)
_TODAY_OPERATIONAL_HINTS = (
    "attention",
    "what needs",
    "needs my",
    "approval",
    "mailbox",
    "inbox",
    "connector",
    "email",
    "communications",
    "dashboard",
    "follow-up",
    "follow up",
    "overdue",
    "recheck",
    "operational",
    "standing",
    "drafts",
    "nova today",
    "today's work",
    "todays work",
    "what should i do with this",
    "summarize this mailbox",
    "summarize this source",
    "summarize this action",
)


def today_supporting_context_relevant(question: str, *, selected_item: bool) -> bool:
    """Today dashboard is supporting context only for operational Today intent."""
    if selected_item:
        return True
    text = f" {question.lower().strip()} "
    if any(hint in text for hint in _TODAY_EXTERNAL_HINTS):
        return False
    return any(hint in text for hint in _TODAY_OPERATIONAL_HINTS)


def _mailbox_supporting_line(health: dict[str, str | None] | None) -> str:
    if not health:
        return ""
    status = health.get("status") or "n/a"
    if status == "not_configured":
        return (
            " Mailbox is not configured. Gmail/Outlook has never been connected for this owner. "
            "This is not an error and does not require repair."
        )
    line = (
        f" Mailbox connector {status}."
        f" Provider {health.get('provider') or 'none'}."
        f" Freshness {health.get('freshness') or 'unknown'}."
    )
    if status == "disconnected":
        line += " A previously configured mailbox connector is disconnected."
    if status == "stale" or health.get("freshness") == "stale":
        line += " This connector is stale."
    if status == "unavailable":
        line += " This is a connector error, not an unconfigured mailbox."
    if health.get("last_success_at"):
        line += f" Last successful read was {health.get('last_success_at')}."
    if health.get("last_attempted_at"):
        line += f" Last attempted read was {health.get('last_attempted_at')}."
    if health.get("recheck_available") == "yes":
        line += " You can re-check the source."
    return line


def _build_today_ask_prompt(
    *,
    question: str,
    selected: str,
    include_supporting: bool,
    dash: NovaTodayDashboardOut | None,
    mailbox_line: str = "",
    comms_line: str = "",
    history_line: str = "",
) -> str:
    primary = (
        "PRIMARY USER PROMPT (this is the user's actual text; answer it directly):\n"
        f"{question.strip()}\n\n"
        "Rules: The user prompt is the primary intent. "
        "Do not substitute AMICOR operational data for requested live or external information "
        "such as weather or news. If that live/external information is not available, say so plainly "
        "and do not invent unrelated next actions. "
        "Conversational statements and questions get relevant conversational replies. "
        "Do not send email, file, pay, call, or execute external actions."
    )
    if not include_supporting:
        return primary + (
            "\n\nNo Today dashboard, mailbox, attention, approval, or history context is provided "
            "because it is not relevant to this prompt."
        )
    assert dash is not None
    supporting = (
        "SUPPORTING TODAY CONTEXT (use only if relevant to the user prompt; "
        "do not treat this as today's news, weather, or a request to repair an unconfigured mailbox):\n"
        f"Attention items: {len(dash.attention_now)}. "
        f"Communications: {len(dash.communications)}. "
        f"Government: {len(dash.government)}. "
        f"Business: {len(dash.business)}. "
        f"Workspace: {len(dash.workspace)}. "
        f"Approval queue: {len(dash.approval_queue)}. "
        f"Recent activity: {len(dash.recent_activity)}.\n"
        "Top attention: "
        + "; ".join(f"{card.trust_label} {card.title}" for card in dash.attention_now[:8])
        + mailbox_line
        + comms_line
        + history_line
        + selected
    )
    return primary + "\n\n" + supporting


def _is_work_revenue_job_request(question: str) -> bool:
    """Recognize owner requests to actively discover suitable revenue work."""
    text = " ".join(str(question or "").lower().split())
    discovery_words = ("find", "search", "look for", "locate", "discover", "get me")
    work_words = (
        "job",
        "jobs",
        "job opportunity",
        "job opportunities",
        "work opportunity",
        "work opportunities",
        "application",
        "applications",
        "employment",
        "revenue-ready work",
        "revenue ready work",
        "work & revenue",
        "work and revenue",
    )
    client_words = (
        "client",
        "clients",
        "customer",
        "customers",
        "buyer",
        "buyers",
        "nova anonymous",
        "anonymous operations agent",
        "anonymous operation agent",
    )
    return (
        any(word in text for word in discovery_words)
        and any(word in text for word in work_words)
        and not any(word in text for word in client_words)
    )


def _run_work_revenue_job_search(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaTodayBrainOut:
    """Run one bounded capability-first Work & Revenue discovery cycle."""
    try:
        reset = reset_live_discovery_opportunities(
            db,
            organization_id=organization_id,
            user=user,
        )
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(constraint, "constraint_name", None) or "unknown"
        raise NovaTodayError(
            f"integrity_stage=reset_live_discovery; constraint={constraint_name}",
            status_code=500,
        ) from exc
    result = run_autopilot_cycle(
        db,
        organization_id=organization_id,
        user=user,
        query_limit=5,
        per_query_limit=10,
        save_limit=10,
        prepare_limit=5,
        min_relevance_score=60,
    )

    persistent = list(result.get("persistent_results") or [])
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in persistent:
        url = str(row.get("source_url") or row.get("application_url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append({
            "title": str(row.get("company_name") or row.get("client") or row.get("title") or "Work opportunity"),
            "url": url,
            "label": str(row.get("title") or "Work & Revenue opportunity"),
        })

    selected = int(result.get("selected_count") or 0)
    prepared = int(result.get("prepared_application_count") or 0)
    ready = int(result.get("ready_for_owner_review_count") or 0)
    held = len([
        row for row in persistent
        if row.get("package_review_status") == "HELD_FOR_OWNER_REVIEW"
    ])
    answer = (
        f"Work & Revenue search completed. I replaced {reset.get('archived_count', 0)} prior "
        f"unprotected live-search opportunities and selected {selected} suitable revenue "
        f"opportunit{'y' if selected == 1 else 'ies'} from the live search. "
        f"I prepared {prepared} application package{'s' if prepared != 1 else ''}; "
        f"{ready} {'is' if ready == 1 else 'are'} ready for owner review, and "
        f"{held} opportunit{'y is' if held == 1 else 'ies are'} held for owner review before preparation. "
        "No application was externally submitted, no client or employer was contacted, "
        "no contract was accepted, and no money moved."
    )
    if not selected:
        answer = (
            f"Work & Revenue search completed. I replaced {reset.get('archived_count', 0)} prior "
            "unprotected live-search opportunities, but no suitable revenue opportunity passed "
            "the current qualification threshold. I did not save random or unsuitable work, "
            "and nothing was submitted externally."
        )

    return NovaTodayBrainOut(
        answer=answer,
        fact_label="VERIFIED DATA",
        next_actions=["Review Nova Work & Revenue applications"] if selected else [],
        generated_at=now().isoformat(),
        source_href="/nova/work",
        sources=sources[:10],
        verification_status="verified",
    )


def _is_nova_anonymous_client_request(question: str) -> bool:
    text = " ".join(str(question or "").lower().split())
    names = (
        "nova anonymous",
        "amicor anonymous",
        "anonymous operations agent",
        "anonymous operation agent",
        "autonomous operations agent",
        "autonomous operation agent",
    )
    buyer_words = ("client", "customer", "buyer", "project", "contract", "work")
    discovery_words = ("find", "search", "look for", "get", "locate", "discover")
    return (
        any(name in text for name in names)
        and any(word in text for word in buyer_words)
        and any(word in text for word in discovery_words)
    )


def _discover_nova_anonymous_web_buyers(question: str, *, max_candidates: int = 6) -> tuple[list[dict], dict]:
    """Find public buyer-intent web sources for Nova Anonymous owner review.

    These are leads, not automatically qualified customers. They are held for
    owner verification before any outreach or proposal activity.
    """
    queries = (
        '"request for proposal" workflow automation',
        '"seeking contractor" business operations automation',
        '"request for proposal" CRM automation support',
        '"seeking vendor" document processing automation',
        '"RFP" administrative workflow automation',
        '"request for quote" operations automation',
        '"solicitation" data processing automation',
        '"bid opportunity" administrative support automation',
        '"accepting proposals" workflow automation',
        '"seeking vendor" spreadsheet automation',
        'site:sam.gov "request for proposal" automation services',
        'site:gov "solicitation" administrative support services',
        'site:gov "request for quote" data processing services',
        'site:gov "bid opportunity" workflow automation',
        'site:gov "professional services" process automation rfp',
    )
    leads: list[dict] = []
    seen_urls: set[str] = set()
    diagnostics = {"queries_run": 0, "sources_seen": 0, "provider_statuses": [], "rejected": {}, "accepted": 0}
    buyer_signals = (
        "request for proposal",
        "rfp",
        "seeking",
        "vendor",
        "contractor",
        "proposal",
        "automation",
        "workflow",
        "operations",
        "crm",
        "document",
        "support",
    )
    reject_signals = (
        "how to",
        "guide",
        "template",
        "course",
        "training",
        "job board",
        "jobs",
        "wikipedia",
        "what is an rfp",
        "what is a request for proposal",
        "understanding the differences",
        "sample rfp",
        "rfp example",
        "rfp process",
        "definition",
        "glossary",
        "explained",
        "best practices",
    )
    blocked_domains = (
        "youtube.com",
        "reddit.com",
        "wikipedia.org",
        "facebook.com",
        "instagram.com",
        "investopedia.com",
        "project-management.com",
    )
    action_signals = (
        "request for proposal",
        "rfp",
        "request for quote",
        "rfq",
        "invitation to bid",
        "bid opportunity",
        "procurement",
        "solicitation",
        "seeking vendor",
        "seeking contractor",
        "accepting proposals",
        "submit proposal",
        "proposal deadline",
        "due date",
    )

    directory_signals = (
        "search government bids",
        "search for government bids",
        "find bid opportunities",
        "government bids, rfps, rfqs",
        "government contracts & bids",
        "bid search",
        "bids and contracts",
        "vendor profiles",
        "bid opportunities from state and local agencies",
        "thousands of active",
        "daily email report",
    )
    generic_path_markers = (
        "",
        "/",
        "/search",
        "/search/",
        "/bids",
        "/bids/",
        "/rfp",
        "/rfp/",
        "/rfps",
        "/rfps/",
        "/contracts",
        "/contracts/",
        "/government-bids",
        "/government-bids/",
    )

    def _reject(reason: str) -> None:
        bucket = diagnostics["rejected"]
        bucket[reason] = int(bucket.get(reason, 0)) + 1

    for query in queries:
        result = fetch_web_search(query, max_results=5)
        diagnostics["queries_run"] += 1
        diagnostics["provider_statuses"].append(str(result.get("status") or "unknown"))
        sources_found = list(result.get("sources") or [])
        diagnostics["sources_seen"] += len(sources_found)
        for source in sources_found:
            title = str(source.get("title") or "").strip()
            url = str(source.get("url") or "").strip()
            label = str(source.get("label") or "").strip()
            snippet = str(source.get("snippet") or "").strip()
            blob = f"{title} {label} {snippet}".lower()
            if not title or not url.startswith(("http://", "https://")):
                _reject("invalid_source")
                continue
            if url in seen_urls:
                _reject("duplicate")
                continue
            if any(domain in url.lower() for domain in blocked_domains):
                _reject("blocked_domain")
                continue
            if any(signal in blob for signal in reject_signals):
                _reject("informational_or_educational")
                continue
            parsed = urlparse(url)
            path = (parsed.path or "/").rstrip("/") or "/"
            if any(signal in blob for signal in directory_signals) or path in generic_path_markers:
                _reject("directory_or_portal_page")
                continue
            if not any(signal in blob for signal in buyer_signals):
                _reject("no_service_need_signal")
                continue
            if not any(signal in blob for signal in action_signals):
                _reject("no_actionable_procurement_signal")
                continue
            seen_urls.add(url)
            diagnostics["accepted"] += 1
            leads.append(
                {
                    "provider_id": "web_buyer_discovery",
                    "provider_type": "public_buyer_intent_web",
                    "source_name": label or "Public web",
                    "source_attribution": label or "Public web",
                    "source_url": url,
                    "application_url": url,
                    "title": title,
                    "company_name": label or title[:160],
                    "client": label or title[:160],
                    "description": (
                        "Specific public buyer opportunity discovered for owner review. "
                        f"Discovery query: {query}. Source context: {snippet[:500] if snippet else 'No provider snippet.'} "
                        "Owner must still verify scope, compensation, vendor terms, and contact path before any outreach."
                    ),
                    "job_type": "unknown",
                    "contract_type": "unknown",
                    "remote_status": "unknown",
                    "compensation_text": None,
                    "simulated": False,
                    "search_family": "nova_anonymous_clients",
                    "search_family_label": "Nova Anonymous client acquisition",
                    "why_searched": question,
                    "qualification_status": "NEEDS_OWNER_REVIEW",
                    "live_qualification": {
                        "qualification_status": "NEEDS_OWNER_REVIEW",
                        "qualification_outcome": "NEEDS_OWNER_REVIEW",
                        "customer_type": "NOVA_ANONYMOUS_CUSTOMER",
                        "revenue_ready": False,
                        "blockers": [],
                        "review_flags": [
                            "Buyer identity, service need, compensation, and vendor terms require owner verification."
                        ],
                        "owner_review_reason": (
                            "Public buyer-intent lead found; verify the buyer, scope, compensation, "
                            "vendor compatibility, and contact path before preparing outreach."
                        ),
                    },
                }
            )
            if len(leads) >= max_candidates:
                return leads, diagnostics
    return leads, diagnostics


def _find_nova_anonymous_clients(
    db: Session,
    *,
    question: str,
    organization_id: str,
    user: UserContext,
) -> NovaTodayBrainOut:
    integrity_stage = "reset_live_discovery"
    """Run one owner-requested Nova Anonymous buyer-intent discovery cycle.

    This is discovery/preparation only. It never contacts a buyer, submits a
    proposal, accepts a contract, or executes a financial action.
    """
    # Dedicated opportunity sources are the primary discovery path for Nova
    # Anonymous client acquisition. Public-web buyer discovery is intentionally
    # not used here unless a future owner-approved mode explicitly enables it.
    capability_plan = targeted_queries_for_request(question, max_queries=12)
    dedicated_queries = tuple(
        str(row.get("query") or "").strip()
        for row in capability_plan
        if str(row.get("search_family") or "") == "nova_anonymous_clients"
        and str(row.get("query") or "").strip()
        and str(row.get("query") or "").strip().lower() != str(question or "").strip().lower()
    )
    collected: list[dict] = []
    dedicated_diagnostics = {
        "providers_queried": [],
        "provider_result_counts": {},
        "provider_screened_counts": {},
        "provider_errors": [],
        "queries_run": 0,
    }
    for query in dedicated_queries:
        dedicated_diagnostics["queries_run"] += 1
        try:
            multi = search_multi_source_jobs(
                query,
                limit=10,
                provider_ids=["sam_gov", "remotive", "remoteok"],
            )
        except Exception as exc:
            logger.exception("Nova Anonymous dedicated query failed")
            dedicated_diagnostics["provider_errors"].append({
                "provider_id": "query_pipeline",
                "error": f"{type(exc).__name__}: dedicated query failed",
                "query": query[:120],
            })
            continue
        dedicated_diagnostics["providers_queried"] = list(dict.fromkeys(
            dedicated_diagnostics["providers_queried"] + list(multi.get("providers_queried") or [])
        ))
        for provider_id, count in dict(multi.get("provider_result_counts") or {}).items():
            dedicated_diagnostics["provider_result_counts"][provider_id] = (
                int(dedicated_diagnostics["provider_result_counts"].get(provider_id, 0)) + int(count)
            )
        for provider_id, count in dict(multi.get("provider_screened_counts") or {}).items():
            dedicated_diagnostics["provider_screened_counts"][provider_id] = (
                int(dedicated_diagnostics["provider_screened_counts"].get(provider_id, 0)) + int(count)
            )
        dedicated_diagnostics["provider_errors"].extend(list(multi.get("provider_errors") or []))
        planned = next((row for row in capability_plan if str(row.get("query") or "") == query), {})
        for raw in multi.get("jobs") or []:
            item = dict(raw)
            item["search_family"] = str(planned.get("search_family") or "nova_anonymous_clients")
            item["search_family_label"] = str(planned.get("search_family_label") or "Nova Anonymous client acquisition")
            item["why_searched"] = str(planned.get("why_searched") or question)
            item["capability_registry_matches"] = list(planned.get("capability_registry_matches") or [])
            collected.append(item)

    integrity_stage = "qualify_live_jobs"
    ranked = qualify_and_rank_live_jobs(question, collected)
    qualified = []
    reviewable = []
    qualification_diagnostics = {
        "status_counts": {},
        "customer_type_counts": {},
        "blocker_counts": {},
        "work_type_counts": {},
        "discovery_band_counts": {},
        "capability_classification_counts": {},
        "provider_status_counts": {},
    }
    for row in ranked:
        qual = dict(row.get("live_qualification") or {})
        status = str(qual.get("qualification_status") or row.get("qualification_status") or "UNKNOWN")
        customer_type = str(qual.get("customer_type") or row.get("customer_type") or "UNKNOWN")
        revenue_ready = bool(qual.get("revenue_ready", row.get("revenue_ready")))
        blockers = list(qual.get("blockers") or [])
        work_type = str(qual.get("work_type") or row.get("work_type") or "unknown")
        discovery_band = str(qual.get("discovery_band") or row.get("discovery_band") or "UNKNOWN")
        classification = str(qual.get("capability_classification") or "UNKNOWN")
        provider_id = str(row.get("provider_id") or "unknown")

        for bucket, key in (
            ("status_counts", status),
            ("customer_type_counts", customer_type),
            ("work_type_counts", work_type),
            ("discovery_band_counts", discovery_band),
            ("capability_classification_counts", classification),
            ("provider_status_counts", f"{provider_id}:{status}"),
        ):
            qualification_diagnostics[bucket][key] = int(
                qualification_diagnostics[bucket].get(key, 0)
            ) + 1
        for blocker in blockers:
            key = str(blocker or "unknown")
            qualification_diagnostics["blocker_counts"][key] = int(
                qualification_diagnostics["blocker_counts"].get(key, 0)
            ) + 1

        if customer_type != "NOVA_ANONYMOUS_CUSTOMER":
            continue
        if status == OUTCOME_QUALIFIED and revenue_ready:
            qualified.append(row)
        elif status == "NEEDS_OWNER_REVIEW" and not blockers:
            reviewable.append(row)

    candidates = (qualified + reviewable)[:10]
    # Do not fall back to broad public-web discovery for this workflow.
    # Dedicated providers may return zero; that is safer and more actionable
    # than promoting search portals or general pages as buyer opportunities.
    web_reviewable: list[dict] = []
    web_diagnostics = {"queries_run": 0, "sources_seen": 0, "provider_statuses": [], "skipped": True}

    reset = reset_live_discovery_opportunities(
        db,
        organization_id=organization_id,
        user=user,
    )
    integrity_stage = "persist_ranked_jobs"
    try:
        persisted = persist_ranked_jobs(
            db,
            candidates,
            organization_id=organization_id,
            user=user,
            prepare_applications=True,
            prepare_limit=3,
        )
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(constraint, "constraint_name", None) or "unknown"
        raise NovaTodayError(
            f"integrity_stage=persist_ranked_jobs; constraint={constraint_name}",
            status_code=500,
        ) from exc

    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in candidates:
        url = str(row.get("source_url") or row.get("application_url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append({
            "title": str(row.get("company_name") or row.get("client") or row.get("title") or "Buyer"),
            "url": url,
            "label": str(row.get("title") or "Nova Anonymous client opportunity"),
        })

    ready = [row for row in persisted if row.get("ready_for_owner_review")]
    held = [row for row in persisted if row.get("package_review_status") == "HELD_FOR_OWNER_REVIEW"]

    # Surface held Work & Revenue opportunities in Nova Today's Approval Queue.
    # Approval only opens the stored opportunity for owner review; it does not
    # contact the buyer, submit a proposal, accept a contract, or move money.
    candidate_by_id = {}
    for candidate, stored in zip(candidates, persisted):
        opp_id = str(stored.get("work_opportunity_id") or "").strip()
        if opp_id:
            candidate_by_id[opp_id] = candidate
    for stored in held:
        opp_id = str(stored.get("work_opportunity_id") or "").strip()
        if not opp_id:
            continue
        candidate = candidate_by_id.get(opp_id) or {}
        title = str(candidate.get("title") or "Work & Revenue opportunity").strip()
        company = str(candidate.get("company_name") or candidate.get("client") or "").strip()
        source_url = str(candidate.get("source_url") or candidate.get("application_url") or "").strip()
        detail_parts = [part for part in (
            f"Buyer: {company}" if company else "",
            f"Opportunity: {title}" if title else "",
            f"Source: {source_url}" if source_url else "",
            str(candidate.get("description") or "").strip(),
            "Owner review required before any proposal, contact, contract acceptance, or financial action.",
        ) if part]
        integrity_stage = "today_approval_upsert"
        _upsert_proposed(
            db,
            _card(
                source_module="work_revenue",
                source_ref_id=opp_id,
                title=f"Review Work & Revenue opportunity: {title}",
                detail="\n".join(detail_parts)[:4000],
                href="/nova/work",
                trust_label="ACTION REQUIRES APPROVAL",
                priority=70,
                recommended_action="open_link",
                explanation="A live buyer opportunity was saved and is waiting for owner review.",
            ),
            organization_id=organization_id,
            user=user,
        )
    if held:
        integrity_stage = "today_approval_commit"
        db.commit()
    answer = (
        f"Nova Anonymous client search completed. I replaced {reset.get('archived_count', 0)} prior "
        f"unprotected live-search opportunities and found {len(qualified)} revenue-ready client "
        f"opportunit{'y' if len(qualified) == 1 else 'ies'} plus {len(reviewable)} legitimate "
        f"opportunit{'y' if len(reviewable) == 1 else 'ies'} that need owner review "
        f"({len(web_reviewable)} from public buyer-intent web discovery). "
        f"{len(ready)} client package{' is' if len(ready) == 1 else 's are'} ready for owner review, "
        f"and {len(held)} opportunit{'y is' if len(held) == 1 else 'ies are'} held for owner review. "
        "No client was contacted, no proposal was submitted, no contract was accepted, and no money moved."
    )
    if not candidates:
        counts = dict(dedicated_diagnostics.get("provider_result_counts") or {})
        screened = dict(dedicated_diagnostics.get("provider_screened_counts") or {})
        errors = list(dedicated_diagnostics.get("provider_errors") or [])
        providers = ", ".join(dedicated_diagnostics.get("providers_queried") or []) or "none"
        count_text = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
        screened_text = ", ".join(f"{k}={v}" for k, v in sorted(screened.items())) or "none"
        error_text = "; ".join(
            f"{item.get('provider_id')}: {item.get('error')}" for item in errors
        )[:800] or "none"
        def _fmt_counts(values):
            return ", ".join(
                f"{k}={v}" for k, v in sorted(
                    dict(values or {}).items(),
                    key=lambda item: (-int(item[1]), str(item[0])),
                )
            ) or "none"

        answer = (
            f"Nova Anonymous dedicated-source search completed. I replaced {reset.get('archived_count', 0)} prior "
            "unprotected live-search opportunities. "
            f"Dedicated providers queried: {providers}. "
            f"Provider accepted-result counts: {count_text}. Provider screened counts: {screened_text}. "
            f"Provider errors: {error_text}. "
            f"Qualification statuses: {_fmt_counts(qualification_diagnostics['status_counts'])}. "
            f"Customer types: {_fmt_counts(qualification_diagnostics['customer_type_counts'])}. "
            f"Top blockers: {_fmt_counts(qualification_diagnostics['blocker_counts'])}. "
            f"Work types: {_fmt_counts(qualification_diagnostics['work_type_counts'])}. "
            f"Discovery bands: {_fmt_counts(qualification_diagnostics['discovery_band_counts'])}. "
            f"Capability classifications: {_fmt_counts(qualification_diagnostics['capability_classification_counts'])}. "
            f"Provider qualification outcomes: {_fmt_counts(qualification_diagnostics['provider_status_counts'])}. "
            "No qualified buyer opportunity passed Nova's capability and safety gates. "
            "Public-web fallback was intentionally not used. "
            "No client was contacted and nothing was submitted."
        )

    return NovaTodayBrainOut(
        answer=answer,
        fact_label="VERIFIED DATA",
        next_actions=["Review Nova Work & Revenue client files"] if candidates else [],
        generated_at=now().isoformat(),
        source_href="/nova/work",
        sources=sources[:10],
        verification_status="verified",
    )


def _today_live_or_memory_answer(
    db: Session,
    payload: NovaTodayBrainRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaTodayBrainOut | None:
    question = str(payload.question or "").strip()
    if not question:
        return None

    if _is_nova_anonymous_client_request(question):
        try:
            return _find_nova_anonymous_clients(
                db,
                question=question,
                organization_id=organization_id,
                user=user,
            )
        except NovaTodayError as exc:
            logger.exception("Nova Anonymous client search failed")
            safe_detail = str(exc)
            if not safe_detail.startswith("integrity_stage="):
                safe_detail = "pipeline_error=NovaTodayError"
            return NovaTodayBrainOut(
                answer=(
                    "I couldn't complete the Nova Anonymous client search right now. "
                    f"Safe diagnostic: {safe_detail}. "
                    "I did not contact any client or submit anything. "
                    "The failure was recorded in server logs for diagnosis."
                ),
                fact_label="AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
                source_href="/nova/work",
                sources=[],
                verification_status="proposed",
            )
        except Exception as exc:
            logger.exception("Nova Anonymous client search failed")
            safe_error = type(exc).__name__
            return NovaTodayBrainOut(
                answer=(
                    "I couldn't complete the Nova Anonymous client search right now. "
                    f"Safe diagnostic: pipeline_error={safe_error}. "
                    "I did not contact any client or submit anything. "
                    "The failure was recorded in server logs for diagnosis."
                ),
                fact_label="AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
                source_href="/nova/work",
                verification_status="unavailable",
            )

    if _is_work_revenue_job_request(question):
        try:
            return _run_work_revenue_job_search(
                db,
                organization_id=organization_id,
                user=user,
            )
        except Exception:
            return NovaTodayBrainOut(
                answer=(
                    "I couldn't complete the Work & Revenue job search right now. "
                    "I did not submit an application or contact an employer. Please try the search again."
                ),
                fact_label="AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
                source_href="/nova/work",
                verification_status="unavailable",
            )

    profile = read_user_profile(organization_id, user.user_id)
    account = db.query(PlatformUser).filter(PlatformUser.id == user.user_id).first()
    account_name = str(getattr(account, "display_name", "") or "").strip()

    stated_name = extract_name_statement(question)
    if stated_name:
        update_user_profile(organization_id, user.user_id, {"preferred_name": stated_name})
        if account is not None and account.display_name != stated_name:
            account.display_name = stated_name
            db.add(account)
            db.commit()
            db.refresh(account)
        return NovaTodayBrainOut(
            answer=f"Got it. I’ll remember your name as {stated_name}.",
            fact_label="USER-SAVED INFORMATION",
            next_actions=[],
            generated_at=now().isoformat(),
        )

    stated_location = extract_location_statement(question)
    if stated_location:
        update_user_profile(organization_id, user.user_id, {"preferred_location": stated_location})
        return NovaTodayBrainOut(
            answer=f"Got it. I’ll remember your location as {stated_location}.",
            fact_label="USER-SAVED INFORMATION",
            next_actions=[],
            generated_at=now().isoformat(),
        )

    if asks_for_name(question):
        remembered = str(profile.get("preferred_name") or account_name or "").strip()
        if remembered:
            return NovaTodayBrainOut(
                answer=f"Your name is {remembered}.",
                fact_label="USER-SAVED INFORMATION",
                next_actions=[],
                generated_at=now().isoformat(),
            )
        return NovaTodayBrainOut(
            answer="You haven’t told me a name to remember yet.",
            fact_label="USER-SAVED INFORMATION",
            next_actions=[],
            generated_at=now().isoformat(),
        )

    if is_web_search_capability_question(question):
        return NovaTodayBrainOut(
            answer=(
                "Yes. I can search the live web, look up current information, and return clickable source links. "
                "You can ask me to look up movies playing today, websites, products, businesses, YouTube, social media, "
                "or other current information."
            ),
            fact_label="VERIFIED DATA",
            next_actions=[],
            generated_at=now().isoformat(),
        )

    known_site = extract_known_site(question)
    if known_site:
        title, url = known_site
        return NovaTodayBrainOut(
            answer=f"Here is {title}. You can open it from the source link below.",
            fact_label="VERIFIED DATA",
            next_actions=[],
            generated_at=now().isoformat(),
            source_href=url,
            sources=[{"title": title, "url": url, "label": title}],
        )

    if is_web_search_request(question):
        preferred_location = str(profile.get("preferred_location") or "").strip()
        query = extract_web_query(question, preferred_location)
        try:
            result = fetch_web_search(query, max_results=5)
            sources = result.get("sources") or []
            source_rows = [
                {
                    "title": str(item.get("title") or item.get("label") or item.get("url") or "Source"),
                    "url": str(item.get("url") or ""),
                    "label": str(item.get("label") or ""),
                }
                for item in sources
                if isinstance(item, dict) and str(item.get("url") or "").startswith(("http://", "https://"))
            ]
            return NovaTodayBrainOut(
                answer=format_web_search(result, query),
                fact_label="VERIFIED DATA" if source_rows else "AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
                source_href=source_rows[0]["url"] if source_rows else None,
                sources=source_rows,
                verification_status="verified" if source_rows else "unavailable",
            )
        except Exception:
            return NovaTodayBrainOut(
                answer="I couldn’t complete the live web search right now. Please try again in a moment.",
                fact_label="AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
                verification_status="unavailable",
            )

    if is_weather_request(question):
        location = extract_weather_location(question) or str(profile.get("preferred_location") or "").strip()
        if not location:
            return NovaTodayBrainOut(
                answer="Tell me the city or place you want the weather for, for example: “What’s the weather in Minneapolis?”",
                fact_label="AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
            )
        try:
            result = fetch_weather(location)
            update_user_profile(organization_id, user.user_id, {"preferred_location": result.get("location") or location})
            return NovaTodayBrainOut(
                answer=format_weather(result),
                fact_label="VERIFIED DATA",
                next_actions=[],
                generated_at=now().isoformat(),
                source_href="https://open-meteo.com/",
            )
        except Exception:
            return NovaTodayBrainOut(
                answer=f"I couldn’t retrieve live weather for {location} right now. Please try again in a moment.",
                fact_label="AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
            )

    if is_news_request(question):
        query = extract_news_query(question)
        try:
            items = fetch_news(query, limit=5)
            return NovaTodayBrainOut(
                answer=format_news(items, query),
                fact_label="VERIFIED DATA",
                next_actions=[],
                generated_at=now().isoformat(),
                source_href=items[0]["link"] if items else None,
            )
        except Exception:
            return NovaTodayBrainOut(
                answer="I couldn’t retrieve live news right now. Please try again in a moment.",
                fact_label="AI SUGGESTION",
                next_actions=[],
                generated_at=now().isoformat(),
            )

    return None


def ask_today(
    db: Session,
    payload: NovaTodayBrainRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaTodayBrainOut:
    direct = _today_live_or_memory_answer(
        db,
        payload,
        organization_id=organization_id,
        user=user,
    )
    if direct is not None:
        return direct

    include_supporting = today_supporting_context_relevant(
        payload.question,
        selected_item=bool(payload.action_id or payload.source_ref_id),
    )
    dash = (
        dashboard(db, organization_id=organization_id, user=user)
        if include_supporting
        else None
    )
    history = dash.recent_activity if dash is not None else []
    selected = ""
    referenced_action_id = None
    referenced_source_ref_id = payload.source_ref_id
    resolved = None
    reviewed = None
    if payload.action_id:
        try:
            reviewed = get_action(db, payload.action_id, organization_id=organization_id, user=user)
            referenced_action_id = reviewed.action_id
            referenced_source_ref_id = reviewed.source_ref_id
            resolved = reviewed.source_href
            selected = (
                f" Owner is reviewing action {reviewed.action_id}: {reviewed.title}. "
                f"Recommended {reviewed.recommended_action}. Source {reviewed.source_module}/{reviewed.source_ref_id}. "
                f"Status {reviewed.status}. Result type {reviewed.result_type}. "
                f"Source link: {reviewed.source_href or 'none'}."
            )
            if reviewed.source_details:
                selected += f" Source details: {reviewed.source_details}."
            if reviewed.verification_status:
                selected += f" Result verification: {reviewed.verification_label or reviewed.verification_status}."
            if reviewed.verification_status == "missing":
                selected += " Draft or task reference is missing. You can re-check the source."
            if reviewed.related_history:
                selected += " Related history: " + "; ".join(
                    f"{item.verification_label or item.result_type} {item.title}" for item in reviewed.related_history[:4]
                )
        except NovaTodayError:
            selected = " The requested action was not visible to this owner."
    elif payload.source_ref_id:
        cards = dash.attention_now if dash is not None else []
        match = next((card for card in cards if card.source_ref_id == payload.source_ref_id), None)
        if match:
            resolved = match.source_href
            selected = (
                f" Owner is reviewing {match.trust_label} item {match.title} "
                f"({match.source_module}/{match.source_ref_id}). Source link: {match.source_href or 'none'}."
            )
        else:
            selected = " The requested source record is not visible on Today."
    mailbox_line = ""
    comms_line = ""
    history_line = ""
    if include_supporting and dash is not None:
        mailbox_line = _mailbox_supporting_line(dash.connector_health)
        rechecks = list_recheck_events(db, organization_id=organization_id, user=user, limit=4)
        if rechecks:
            mailbox_line += " Recent re-checks: " + "; ".join(
                f"{row.detail} ({row.prior_verification or 'unknown'} → {row.new_verification or 'unknown'})"
                for row in rechecks
            )
        if dash.communications:
            comms_line = " Recent mailbox/communications: " + "; ".join(
                f"{card.sender or ''} {card.subject or card.title}" for card in dash.communications[:5]
            )
        if history:
            history_line = " Recent owner results: " + "; ".join(
                f"{item.verification_label or item.result_type} {item.title}" for item in history[:6]
            )
    context = _build_today_ask_prompt(
        question=payload.question,
        selected=selected if include_supporting else "",
        include_supporting=include_supporting,
        dash=dash if include_supporting else None,
        mailbox_line=mailbox_line,
        comms_line=comms_line,
        history_line=history_line,
    )
    asked = NovaCoreService.ask(
        db,
        organization_id=organization_id,
        mode="founder_advisor",
        question=context,
        require_operational_next_actions=False,
    )
    next_actions: list[str] = []
    if resolved:
        next_actions.append(f"Open existing source: {resolved}")
    if include_supporting and dash is not None and (
        (dash.connector_health or {}).get("recheck_available") == "yes"
        or (reviewed is not None and reviewed.verification_status in {"missing", "unavailable", "unknown"})
    ):
        next_actions = ["Re-check the source"] + next_actions
    next_actions = [item for item in next_actions if "send" not in item.lower() and "file" not in item.lower()][:6]
    return NovaTodayBrainOut(
        answer=asked.answer,
        fact_label="AI SUGGESTION unless the answer cites USER-SAVED INFORMATION or VERIFIED DATA. ACTION REQUIRES APPROVAL before any write. Ask Nova does not execute external actions.",
        next_actions=next_actions,
        generated_at=asked.generated_at,
        source_href=resolved,
        referenced_action_id=referenced_action_id,
        referenced_source_ref_id=referenced_source_ref_id,
        verification_status=reviewed.verification_status if reviewed is not None else None,
    )


def list_mailbox(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    connector_account_id: str | None = None,
) -> NovaTodayMailboxOut:
    try:
        items, health = read_mailbox(
            db,
            organization_id=organization_id,
            user=user,
            connector_account_id=connector_account_id,
            persist=True,
        )
    except PermissionError as exc:
        raise NovaTodayError(str(exc), status_code=403) from exc
    except Exception:
        recover_today_session(db)
        items, health = [], ConnectorHealth(
            status="unavailable",
            detail="Mailbox connector is unavailable. Today did not invent messages.",
        )
    return NovaTodayMailboxOut(
        items=[
            NovaTodayMailboxItemOut(
                external_message_id=item.external_message_id,
                provider=item.provider,
                sender=item.sender,
                recipients=item.recipients,
                subject=item.subject,
                received_at=item.received_at,
                unread=item.unread,
                important=item.important,
                snippet=item.snippet,
                connector_account_id=item.connector_account_id,
                source_href=item.source_href,
                source_health=item.source_health,
                message_id=item.message_id,
            )
            for item in items
        ],
        connector_health=health.as_dict(),
    )


def list_recheck_events(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int = 20,
) -> list[NovaV2RecheckEvent]:
    query = db.query(NovaV2RecheckEvent).filter(NovaV2RecheckEvent.organization_id == organization_id)
    if not _can_see_org_wide(user):
        query = query.filter(NovaV2RecheckEvent.owner_user_id == user.user_id)
    return query.order_by(NovaV2RecheckEvent.created_at.desc()).limit(limit).all()


def _recheck_history_item(event: NovaV2RecheckEvent) -> NovaTodayHistoryItem:
    return NovaTodayHistoryItem(
        action_id=event.action_id or event.recheck_id,
        source_module=event.source_module,
        source_ref_id=event.source_ref_id,
        title=event.detail,
        prior_status=event.prior_verification or "unknown",
        resulting_status=event.new_verification or "unknown",
        result_ref_id=event.result_ref_id,
        actor_user_id=event.actor_user_id,
        decided_at=event.created_at,
        trust_label="VERIFIED DATA",
        recommended_action="recheck_source",
        result_type="source_rechecked",
        source_href="/nova/communications" if event.source_module == "communications" else None,
        verification_status=event.new_verification,
        verification_label=verification_label("source_rechecked", event.new_verification) if event.new_verification else None,
        prior_verification_status=event.prior_verification,
    )


def recheck_source(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    action_id: str | None = None,
    connector_account_id: str | None = None,
) -> NovaTodayRecheckOut:
    row = None
    if action_id:
        row = _get_action(db, action_id, organization_id=organization_id, user=user)
    prior = None
    if row is not None:
        prior = verify_result(db, row, organization_id=organization_id, user=user)
    health = ConnectorHealth(status="n/a", detail="No connector re-read was required.", recheck_available=False)
    read_connector = bool(connector_account_id) or row is None or (row.source_module == "communications")
    if read_connector:
        try:
            _items, health = read_mailbox(
                db,
                organization_id=organization_id,
                user=user,
                connector_account_id=connector_account_id,
                persist=True,
            )
        except PermissionError as exc:
            raise NovaTodayError(str(exc), status_code=403) from exc
        except Exception:
            recover_today_session(db)
            health = ConnectorHealth(
                status="unavailable",
                detail="Mailbox connector is unavailable. Today did not invent messages.",
            )
    new_state = prior
    if row is not None:
        new_state = verify_result(db, row, organization_id=organization_id, user=user)
    elif read_connector:
        new_state = "unknown"
    source_ref = (row.source_ref_id if row else None) or health.connector_account_id or "mailbox"
    if row and row.result_ref_id:
        detail = (
            f"Owner re-checked {row.recommended_action} result {row.result_ref_id}. "
            f"Verification {prior or 'unknown'} → {new_state or 'unknown'}. Nothing was recreated."
        )
    else:
        detail = (
            f"Owner re-checked mailbox connector {health.status}. "
            f"Last successful read {health.last_success_at.isoformat() if health.last_success_at else 'unknown'}. "
            "Nothing was sent."
        )
    event = NovaV2RecheckEvent(
        recheck_id=f"NVR-{uuid4().replace('-', '')[:12].upper()}",
        organization_id=organization_id,
        owner_user_id=row.owner_user_id if row else user.user_id,
        actor_user_id=user.user_id,
        action_id=row.action_id if row else None,
        source_module=row.source_module if row else "communications",
        source_ref_id=source_ref,
        result_ref_id=row.result_ref_id if row else None,
        connector_account_id=health.connector_account_id or connector_account_id,
        prior_verification=prior,
        new_verification=new_state,
        connector_status=health.status,
        source_health=health.freshness,
        detail=detail,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return NovaTodayRecheckOut(
        recheck_id=event.recheck_id,
        action_id=event.action_id,
        source_ref_id=event.source_ref_id,
        result_ref_id=event.result_ref_id,
        prior_verification=prior,
        verification_status=new_state,
        verification_label=verification_label(
            "source_rechecked" if not row else result_type_for(row),
            new_state,
        )
        if new_state
        else None,
        connector_health=health.as_dict(),
        source_health=health.freshness,
        mutated_external=False,
        message=detail,
        fact_label="VERIFIED DATA",
    )


def readiness_checklist() -> NovaTodayReadinessOut:
    return NovaTodayReadinessOut(items=beta_readiness_checklist(), fact_label="VERIFIED DATA")


def refuse_send() -> None:
    raise NovaTodayError("Nova Today does not send external email. Use a Communications draft after approval.", status_code=403)


def refuse_file() -> None:
    raise NovaTodayError("Nova Today does not submit government filings or pay government fees.", status_code=403)


def refuse_ledger() -> None:
    raise NovaTodayError("Nova Today does not create ledgers, payroll, tax filings, or LIVE charges.", status_code=403)


def refuse_call() -> None:
    raise NovaTodayError("Nova Today does not place calls.", status_code=403)
