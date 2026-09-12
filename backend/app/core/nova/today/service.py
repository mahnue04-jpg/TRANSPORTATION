"""Nova V2 Today aggregator. Reads V1 dashboards. Writes only nova_v2_command_actions."""
from __future__ import annotations

from datetime import timedelta

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
from app.core.nova.today.models import NovaV2CommandAction
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
    NovaTodayProductCount,
    NovaTodaySourceHealth,
)
from app.core.nova.workspace.service import dashboard as workspace_dashboard
from app.helpers import now, uuid4
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
        return _product_count_card(spec, count=None, status="unavailable")


def product_counts(db: Session, *, organization_id: str, user: UserContext) -> list[NovaTodayProductCount]:
    return [
        _read_one_product_count(db, organization_id=organization_id, user=user, spec=spec)
        for spec in _PRODUCT_COUNT_SPECS
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
    return (
        "This action is not supported on Nova Today.",
        "Nothing will be executed.",
        "No email send, filing, payment, Stripe charge, ledger post, or phone call.",
    )


def action_out(row: NovaV2CommandAction) -> NovaTodayActionOut:
    why, if_approved, will_not = action_consequences(row.recommended_action)
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
        href=row.href,
        trust_label=row.trust_label,
        priority=row.priority,
        priority_band=priority_band(row.priority),
        status=row.status,
        recommended_action=row.recommended_action,
        why_recommended=why,
        if_approved=if_approved,
        will_not_happen=will_not,
        result_ref_id=row.result_ref_id,
        created_at=row.created_at,
        decided_at=row.decided_at,
        snoozed_until=row.snoozed_until,
    )


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
    href: str,
    trust_label: str,
    priority: int,
    recommended_action: str,
    explanation: str | None = None,
    sender: str | None = None,
    subject: str | None = None,
) -> NovaTodayCard:
    why, if_approved, will_not = action_consequences(recommended_action)
    return NovaTodayCard(
        source_module=source_module,
        source_ref_id=source_ref_id,
        title=title,
        detail=detail,
        explanation=explanation or detail,
        source_label=_SOURCE_LABELS.get(source_module, source_module),
        sender=sender,
        subject=subject,
        href=href,
        trust_label=trust_label,
        priority=priority,
        priority_band=priority_band(priority),
        recommended_action=recommended_action,
        why_recommended=why,
        if_approved=if_approved,
        will_not_happen=will_not,
    )


def _list_actions(db: Session, *, organization_id: str, user: UserContext) -> list[NovaV2CommandAction]:
    query = db.query(NovaV2CommandAction).filter(NovaV2CommandAction.organization_id == organization_id)
    return _owner_filter(query, user).order_by(NovaV2CommandAction.priority.desc(), NovaV2CommandAction.created_at.desc()).all()


def _get_action(db: Session, action_id: str, *, organization_id: str, user: UserContext) -> NovaV2CommandAction:
    query = db.query(NovaV2CommandAction).filter(
        NovaV2CommandAction.action_id == action_id,
        NovaV2CommandAction.organization_id == organization_id,
    )
    row = _owner_filter(query, user).first()
    if row is None:
        raise NovaTodayError("Today action not found", status_code=404)
    return row


def _upsert_proposed(
    db: Session,
    card: NovaTodayCard,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaV2CommandAction:
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


def _safe_source(loader):
    try:
        return loader(), "ok"
    except Exception:
        return None, "unavailable"


def _health(source: str, status: str, *, count: int = 0) -> NovaTodaySourceHealth:
    if status == "unavailable":
        return NovaTodaySourceHealth(
            source=source,
            status="unavailable",
            detail="This Nova source is unavailable. Today did not invent records.",
        )
    if count == 0:
        return NovaTodaySourceHealth(
            source=source,
            status="empty",
            detail="No real records in this source today.",
        )
    return NovaTodaySourceHealth(source=source, status="ok", detail=f"{count} real items.")


def _collect_v1_cards(db: Session, *, organization_id: str, user: UserContext) -> dict[str, list[NovaTodayCard]]:
    workspace, workspace_status = _safe_source(
        lambda: workspace_dashboard(db, organization_id=organization_id, user=user)
    )
    communications, comms_status = _safe_source(
        lambda: communications_dashboard(db, organization_id=organization_id, user=user)
    )
    government, gov_status = _safe_source(
        lambda: government_dashboard(db, organization_id=organization_id, user=user)
    )
    business, biz_status = _safe_source(
        lambda: business_dashboard(db, organization_id=organization_id, user=user)
    )

    comms_cards: list[NovaTodayCard] = []
    seen_messages: set[str] = set()
    if communications is not None:
        for row in list(communications.important) + list(communications.inbox):
            if row.message_id in seen_messages:
                continue
            if not row.important and row.read:
                continue
            seen_messages.add(row.message_id)
            label = "Important" if row.important else "Unread"
            comms_cards.append(
                _card(
                    source_module="communications",
                    source_ref_id=row.message_id,
                    title=f"{label}: {row.subject}",
                    detail=row.snippet or row.sender,
                    explanation=f"From {row.sender}. {row.snippet or 'Saved message. Prepare a draft only.'}",
                    href="/nova/communications",
                    trust_label="USER-SAVED INFORMATION",
                    priority=82 if row.important else 75,
                    recommended_action="create_draft",
                    sender=row.sender,
                    subject=row.subject,
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
                    trust_label="USER-SAVED INFORMATION",
                    priority=60,
                    recommended_action="open_link",
                    subject=row.title,
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
                    trust_label="USER-SAVED INFORMATION",
                    priority=55,
                    recommended_action="open_link",
                    subject=row.subject,
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
            trust_label="VERIFIED DATA",
            priority=10,
            recommended_action="open_link",
        ),
    ]

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
            _health("communications", comms_status, count=len(comms_cards)),
            _health("government", gov_status, count=len(gov_cards)),
            _health("business", biz_status, count=len(biz_cards)),
            _health("workspace", workspace_status, count=len(workspace_cards)),
        ],
    }


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> NovaTodayDashboardOut:
    groups = _collect_v1_cards(db, organization_id=organization_id, user=user)
    persistable = groups["communications"] + groups["government"] + groups["business"] + groups["recommendations"]
    for card in persistable:
        _upsert_proposed(db, card, organization_id=organization_id, user=user)
    db.commit()

    rows = _list_actions(db, organization_id=organization_id, user=user)
    keyed = {(row.source_module, row.source_ref_id, row.recommended_action): row for row in rows}
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
            kept.append(_attach_action(card, keyed))
        return sorted(kept, key=rank_score, reverse=True)

    communications = visible(groups["communications"])
    government = visible(groups["government"])
    business = visible(groups["business"])
    workspace = visible(groups["workspace"])
    product_links = visible(groups["product_links"])
    recommendations = visible(groups["recommendations"])
    attention_now = sorted(
        communications + government + business + workspace,
        key=rank_score,
        reverse=True,
    )[:16]
    approval_queue = [action_out(row) for row in rows if row.status == "proposed"]
    try:
        counts = product_counts(db, organization_id=organization_id, user=user)
    except Exception:
        counts = [_product_count_card(spec, count=None, status="unavailable") for spec in _PRODUCT_COUNT_SPECS]
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
        source_health=list(groups.get("source_health") or []),
        trust_labels=list(TRUST_LABELS),
    )


def list_actions(db: Session, *, organization_id: str, user: UserContext) -> list[NovaTodayActionOut]:
    return [action_out(row) for row in _list_actions(db, organization_id=organization_id, user=user)]


def get_action(db: Session, action_id: str, *, organization_id: str, user: UserContext) -> NovaTodayActionOut:
    return action_out(_get_action(db, action_id, organization_id=organization_id, user=user))


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
    return action_out(row)


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
    return action_out(row)


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
            action=action_out(row),
            href=row.href,
            draft_id=row.result_ref_id if row.recommended_action == "create_draft" else None,
            task_id=row.result_ref_id if row.recommended_action == "create_task" else None,
            message="Already approved. Nothing else was sent or filed.",
            fact_label="USER-SAVED INFORMATION",
        )
    if row.recommended_action == "open_link":
        row.status = "done"
        row.decided_at = now()
        db.commit()
        db.refresh(row)
        return NovaTodayApproveOut(
            action=action_out(row),
            href=row.href,
            message="Open the existing V1 record. No new product data was created.",
            fact_label="VERIFIED DATA",
        )
    if row.recommended_action == "acknowledge":
        row.status = "done"
        row.decided_at = now()
        db.commit()
        db.refresh(row)
        return NovaTodayApproveOut(
            action=action_out(row),
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
        return NovaTodayApproveOut(
            action=action_out(row),
            href="/nova/communications",
            draft_id=draft.id,
            message="Communications draft saved. External send was not performed.",
            fact_label="USER-SAVED INFORMATION",
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
        return NovaTodayApproveOut(
            action=action_out(row),
            href="/nova/business",
            task_id=task.task_id,
            message="Business task created. This is not accounting, payroll, or a filing.",
            fact_label="USER-SAVED INFORMATION",
        )
    raise NovaTodayError("Unsupported Today action", status_code=422)


def ask_today(
    db: Session,
    payload: NovaTodayBrainRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaTodayBrainOut:
    dash = dashboard(db, organization_id=organization_id, user=user)
    selected = ""
    if payload.action_id:
        try:
            row = _get_action(db, payload.action_id, organization_id=organization_id, user=user)
            selected = (
                f" Owner is reviewing action {row.action_id}: {row.title}. "
                f"Recommended {row.recommended_action}. Source {row.source_module}/{row.source_ref_id}."
            )
        except NovaTodayError:
            selected = " The requested action was not visible to this owner."
    elif payload.source_ref_id:
        match = next((card for card in dash.attention_now if card.source_ref_id == payload.source_ref_id), None)
        if match:
            selected = f" Owner is reviewing {match.trust_label} item {match.title}."
    context = (
        "You are Mrs. Nova Brain on Nova Today. Use VERIFIED DATA, USER-SAVED INFORMATION, "
        "AI SUGGESTION, and ACTION REQUIRES APPROVAL. Do not send email, file with an agency, "
        "charge a card, or create a ledger.\n\n"
        f"Attention items: {len(dash.attention_now)}. "
        f"Communications: {len(dash.communications)}. "
        f"Government: {len(dash.government)}. "
        f"Business: {len(dash.business)}. "
        f"Workspace: {len(dash.workspace)}. "
        f"Approval queue: {len(dash.approval_queue)}.\n"
        "Top attention: "
        + "; ".join(f"{card.trust_label} {card.title}" for card in dash.attention_now[:8])
        + selected
        + f"\n\n{payload.question.strip()}"
    )
    asked = NovaCoreService.ask(db, organization_id=organization_id, mode="founder_advisor", question=context)
    return NovaTodayBrainOut(
        answer=asked.answer,
        fact_label="AI SUGGESTION unless the answer cites USER-SAVED INFORMATION or VERIFIED DATA. ACTION REQUIRES APPROVAL before any write.",
        next_actions=asked.next_actions,
        generated_at=asked.generated_at,
    )


def refuse_send() -> None:
    raise NovaTodayError("Nova Today does not send external email. Use a Communications draft after approval.", status_code=403)


def refuse_file() -> None:
    raise NovaTodayError("Nova Today does not submit government filings or pay government fees.", status_code=403)


def refuse_ledger() -> None:
    raise NovaTodayError("Nova Today does not create ledgers, payroll, tax filings, or LIVE charges.", status_code=403)


def refuse_call() -> None:
    raise NovaTodayError("Nova Today does not place calls.", status_code=403)
