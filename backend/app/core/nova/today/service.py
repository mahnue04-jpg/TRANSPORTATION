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
from app.core.nova.today.links import (
    prior_status_for,
    result_type_for,
    source_details,
    source_href,
)
from app.core.nova.today.mailbox import ConnectorHealth, MailboxItem, read_mailbox
from app.core.nova.today.verify import verification_label, verify_result
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
    NovaTodayHistoryItem,
    NovaTodayMailboxItemOut,
    NovaTodayMailboxOut,
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
    return items


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
            connector="unavailable" if mailbox_status == "unavailable" else ("n/a" if connector == "n/a" else "disconnected"),
            last_sync_at=last_sync_at,
        )
    if source == "communications" and email_connected is not None:
        if mailbox_status in {"connected", "degraded", "stale", "unavailable"}:
            connector_value = mailbox_status
        else:
            connector_value = "connected" if email_connected else "disconnected"
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
            return NovaTodaySourceHealth(
                source=source,
                status="partial",
                detail="Local saved messages only. No mailbox connector is connected.",
                connector=connector_value if connector_value != "n/a" else "disconnected",
                last_sync_at=last_sync_at,
            )
        return NovaTodaySourceHealth(
            source=source,
            status="empty",
            detail="No mailbox connector. No saved messages were invented.",
            connector=connector_value if connector_value != "n/a" else "disconnected",
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
        mailbox_health = ConnectorHealth(
            status="unavailable",
            detail="Cross-owner or cross-org connector access is denied.",
        )
    except Exception:
        mailbox_health = ConnectorHealth(
            status="unavailable",
            detail="Mailbox connector is unavailable. Today did not invent messages.",
        )
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
    approval_queue = [
        action_out(
            row,
            resolved_href=_resolved_source_href(db, row, organization_id=organization_id, user=user),
            use_resolved=True,
        )
        for row in rows
        if row.status == "proposed"
    ]
    recent_activity = list_history(db, organization_id=organization_id, user=user)
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
        verified = verify_result(db, row, organization_id=organization_id, user=user)
        return NovaTodayApproveOut(
            action=action_out(row, verification_status=verified),
            href="/nova/communications",
            draft_id=draft.id,
            message="Communications draft saved. External send was not performed.",
            fact_label="USER-SAVED INFORMATION",
            verification_status=verified,
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
        return NovaTodayApproveOut(
            action=action_out(row, verification_status=verified),
            href="/nova/business",
            task_id=task.task_id,
            message="Business task created. This is not accounting, payroll, or a filing.",
            fact_label="USER-SAVED INFORMATION",
            verification_status=verified,
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
    history = dash.recent_activity
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
            if reviewed.related_history:
                selected += " Related history: " + "; ".join(
                    f"{item.verification_label or item.result_type} {item.title}" for item in reviewed.related_history[:4]
                )
        except NovaTodayError:
            selected = " The requested action was not visible to this owner."
    elif payload.source_ref_id:
        match = next((card for card in dash.attention_now if card.source_ref_id == payload.source_ref_id), None)
        if match:
            resolved = match.source_href
            selected = (
                f" Owner is reviewing {match.trust_label} item {match.title} "
                f"({match.source_module}/{match.source_ref_id}). Source link: {match.source_href or 'none'}."
            )
        else:
            selected = " The requested source record is not visible on Today."
    mailbox_line = ""
    if dash.connector_health:
        mailbox_line = (
            f" Mailbox connector {dash.connector_health.get('status') or 'n/a'}."
            f" Provider {dash.connector_health.get('provider') or 'none'}."
        )
    comms_line = ""
    if dash.communications:
        comms_line = " Recent mailbox/communications: " + "; ".join(
            f"{card.sender or ''} {card.subject or card.title}" for card in dash.communications[:5]
        )
    history_line = ""
    if history:
        history_line = " Recent owner results: " + "; ".join(
            f"{item.verification_label or item.result_type} {item.title}" for item in history[:6]
        )
    context = (
        "You are Mrs. Nova Brain on Nova Today. Use VERIFIED DATA, USER-SAVED INFORMATION, "
        "AI SUGGESTION, and ACTION REQUIRES APPROVAL. Explain, summarize, recommend, and point "
        "to existing source links only. Do not send email, file with an agency, charge a card, "
        "create a ledger, place a call, or execute any external action.\n\n"
        f"Attention items: {len(dash.attention_now)}. "
        f"Communications: {len(dash.communications)}. "
        f"Government: {len(dash.government)}. "
        f"Business: {len(dash.business)}. "
        f"Workspace: {len(dash.workspace)}. "
        f"Approval queue: {len(dash.approval_queue)}. "
        f"Recent activity: {len(history)}.\n"
        "Top attention: "
        + "; ".join(f"{card.trust_label} {card.title}" for card in dash.attention_now[:8])
        + mailbox_line
        + comms_line
        + history_line
        + selected
        + f"\n\n{payload.question.strip()}"
    )
    asked = NovaCoreService.ask(db, organization_id=organization_id, mode="founder_advisor", question=context)
    next_actions = list(asked.next_actions or [])
    if resolved:
        next_actions = [f"Open existing source: {resolved}"] + next_actions
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


def refuse_send() -> None:
    raise NovaTodayError("Nova Today does not send external email. Use a Communications draft after approval.", status_code=403)


def refuse_file() -> None:
    raise NovaTodayError("Nova Today does not submit government filings or pay government fees.", status_code=403)


def refuse_ledger() -> None:
    raise NovaTodayError("Nova Today does not create ledgers, payroll, tax filings, or LIVE charges.", status_code=403)


def refuse_call() -> None:
    raise NovaTodayError("Nova Today does not place calls.", status_code=403)
