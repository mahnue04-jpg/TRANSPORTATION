"""Nova V2 Today aggregator. Reads V1 dashboards. Writes only nova_v2_command_actions."""
from __future__ import annotations

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
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
    TRUST_LABELS,
    NovaTodayActionCreate,
    NovaTodayActionOut,
    NovaTodayApproveOut,
    NovaTodayApproveRequest,
    NovaTodayBrainOut,
    NovaTodayBrainRequest,
    NovaTodayCard,
    NovaTodayDashboardOut,
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


def _owner_filter(query, user: UserContext):
    if _can_see_org_wide(user):
        return query
    return query.filter(NovaV2CommandAction.owner_user_id == user.user_id)


def action_out(row: NovaV2CommandAction) -> NovaTodayActionOut:
    return NovaTodayActionOut(
        action_id=row.action_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        source_module=row.source_module,
        source_ref_id=row.source_ref_id,
        title=row.title,
        detail=row.detail,
        href=row.href,
        trust_label=row.trust_label,
        priority=row.priority,
        status=row.status,
        recommended_action=row.recommended_action,
        result_ref_id=row.result_ref_id,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


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
) -> NovaTodayCard:
    return NovaTodayCard(
        source_module=source_module,
        source_ref_id=source_ref_id,
        title=title,
        detail=detail,
        href=href,
        trust_label=trust_label,
        priority=priority,
        recommended_action=recommended_action,
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


def _collect_v1_cards(db: Session, *, organization_id: str, user: UserContext) -> dict[str, list[NovaTodayCard]]:
    workspace = workspace_dashboard(db, organization_id=organization_id, user=user)
    communications = communications_dashboard(db, organization_id=organization_id, user=user)
    government = government_dashboard(db, organization_id=organization_id, user=user)
    business = business_dashboard(db, organization_id=organization_id, user=user)

    comms_cards: list[NovaTodayCard] = []
    for row in communications.important:
        comms_cards.append(
            _card(
                source_module="communications",
                source_ref_id=row.message_id,
                title=f"Important: {row.subject}",
                detail=row.snippet or row.sender,
                href="/nova/communications",
                trust_label="USER-SAVED INFORMATION",
                priority=82,
                recommended_action="create_draft",
            )
        )
    for row in communications.today:
        comms_cards.append(
            _card(
                source_module="communications",
                source_ref_id=row.event_id,
                title=f"Today: {row.title}",
                detail=row.location,
                href="/nova/communications",
                trust_label="USER-SAVED INFORMATION",
                priority=60,
                recommended_action="open_link",
            )
        )
    for row in communications.drafts[:6]:
        comms_cards.append(
            _card(
                source_module="communications",
                source_ref_id=row.draft_id,
                title=f"Draft: {row.subject}",
                detail="Saved draft. Nothing was sent.",
                href="/nova/communications",
                trust_label="USER-SAVED INFORMATION",
                priority=55,
                recommended_action="open_link",
            )
        )

    gov_cards: list[NovaTodayCard] = []
    for row in government.overdue:
        gov_cards.append(
            _card(
                source_module="government",
                source_ref_id=row.item_id,
                title=f"Overdue: {row.title}",
                detail=row.agency,
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
                    href="/nova/government",
                    trust_label="USER-SAVED INFORMATION",
                    priority=76,
                    recommended_action="open_link",
                )
            )

    biz_cards: list[NovaTodayCard] = []
    for row in business.overdue_tasks:
        biz_cards.append(
            _card(
                source_module="business",
                source_ref_id=row.task_id,
                title=f"Overdue task: {row.title}",
                detail=None,
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
                href="/nova/business",
                trust_label="USER-SAVED INFORMATION",
                priority=70,
                recommended_action="create_draft",
            )
        )
    for row in business.open_opportunities[:8]:
        biz_cards.append(
            _card(
                source_module="business",
                source_ref_id=row.opportunity_id,
                title=f"Opportunity: {row.title}",
                detail=row.next_action,
                href="/nova/business",
                trust_label="USER-SAVED INFORMATION",
                priority=58,
                recommended_action="create_task",
            )
        )

    workspace_cards: list[NovaTodayCard] = []
    for row in workspace.recent_work[:8]:
        workspace_cards.append(
            _card(
                source_module="workspace",
                source_ref_id=row.activity_id,
                title=row.title,
                detail=row.kind,
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

    recommendations = [
        _card(
            source_module="business",
            source_ref_id="rec-attention",
            title="Review today's follow-ups and overdue work",
            detail="Mrs. Nova Brain suggestion from existing Business and Government records.",
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
    }


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> NovaTodayDashboardOut:
    groups = _collect_v1_cards(db, organization_id=organization_id, user=user)
    persistable = (
        groups["communications"]
        + groups["government"]
        + groups["business"]
        + groups["workspace"]
        + groups["product_links"]
        + groups["recommendations"]
    )
    for card in persistable:
        _upsert_proposed(db, card, organization_id=organization_id, user=user)
    db.commit()

    rows = _list_actions(db, organization_id=organization_id, user=user)
    keyed = {(row.source_module, row.source_ref_id, row.recommended_action): row for row in rows}
    dismissed = {
        (row.source_module, row.source_ref_id, row.recommended_action)
        for row in rows
        if row.status == "dismissed"
    }

    def visible(cards: list[NovaTodayCard]) -> list[NovaTodayCard]:
        kept: list[NovaTodayCard] = []
        for card in cards:
            key = (card.source_module, card.source_ref_id, card.recommended_action)
            if key in dismissed:
                continue
            kept.append(_attach_action(card, keyed))
        return sorted(kept, key=lambda item: item.priority, reverse=True)

    communications = visible(groups["communications"])
    government = visible(groups["government"])
    business = visible(groups["business"])
    workspace = visible(groups["workspace"])
    product_links = visible(groups["product_links"])
    recommendations = visible(groups["recommendations"])
    attention_now = sorted(
        communications + government + business + workspace,
        key=lambda item: item.priority,
        reverse=True,
    )[:16]
    approval_queue = [action_out(row) for row in rows if row.status == "proposed"]
    return NovaTodayDashboardOut(
        attention_now=attention_now,
        communications=communications,
        government=government,
        business=business,
        workspace=workspace,
        product_links=product_links,
        recommendations=recommendations,
        approval_queue=approval_queue,
        trust_labels=list(TRUST_LABELS),
    )


def list_actions(db: Session, *, organization_id: str, user: UserContext) -> list[NovaTodayActionOut]:
    return [action_out(row) for row in _list_actions(db, organization_id=organization_id, user=user)]


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
