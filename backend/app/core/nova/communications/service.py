"""Nova Communications service. Wraps existing email/calendar tables. No Freight/Health writes."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.communications.models import (
    NovaCommunicationsMessage,
    NovaCommunicationsNotification,
)
from app.core.nova.communications.schemas import (
    NovaCommsBrainOut,
    NovaCommsBrainRequest,
    NovaCommsContactOut,
    NovaCommsDashboardOut,
    NovaCommsDraftCreate,
    NovaCommsDraftOut,
    NovaCommsEventCreate,
    NovaCommsEventOut,
    NovaCommsMessageCreate,
    NovaCommsMessageOut,
    NovaCommsMessageUpdate,
    NovaCommsNotificationOut,
    NovaCommsSendRequest,
)
from app.core.nova.service import NovaCoreService
from app.core.nova.workspace.models import NovaWorkspaceActivity
from app.db.models import CalendarEventRecord, EmailDraftRecord, IntegrationAccount
from app.helpers import json_dumps, json_loads_or, now, uuid4


class NovaCommunicationsError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _new_id(prefix: str) -> str:
    return prefix + uuid4().replace("-", "")[:12].upper()


def send_allowed() -> bool:
    return os.getenv("NOVA_COMMUNICATIONS_ALLOW_SEND", "").strip() == "1"


def _can_see_org_wide(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}


def _owner_filter(query, model, user: UserContext):
    if _can_see_org_wide(user):
        return query
    return query.filter(model.owner_user_id == user.user_id)


def _parse_iso(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _location_from_description(description: str | None) -> tuple[str | None, str | None]:
    text = description or ""
    if text.startswith("Location: "):
        first, _, rest = text.partition("\n")
        return first.replace("Location: ", "", 1).strip() or None, rest or None
    return None, description


def _notify(
    db: Session,
    *,
    organization_id: str,
    owner_user_id: str,
    kind: str,
    title: str,
    detail: str | None = None,
    link: str | None = "/nova/communications",
) -> None:
    db.add(
        NovaCommunicationsNotification(
            notification_id=_new_id("NCN-"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            kind=kind,
            title=title[:240],
            detail=detail,
            link=link,
        )
    )


def message_out(row: NovaCommunicationsMessage, include_body: bool = False) -> NovaCommsMessageOut:
    return NovaCommsMessageOut(
        message_id=row.message_id,
        sender=row.sender,
        subject=row.subject,
        snippet=row.snippet,
        body=row.body if include_body else None,
        read=row.read,
        important=row.important,
        source=row.source,
        created_at=row.created_at,
    )


def draft_out(row: EmailDraftRecord) -> NovaCommsDraftOut:
    return NovaCommsDraftOut(
        draft_id=row.id,
        to=json_loads_or(row.to_recipients, []),
        cc=json_loads_or(row.cc_recipients, []),
        bcc=json_loads_or(row.bcc_recipients, []),
        subject=row.subject,
        body=row.body,
        status=row.status,
        updated_at=row.updated_at,
    )


def event_out(row: CalendarEventRecord) -> NovaCommsEventOut:
    location, description = _location_from_description(row.description)
    return NovaCommsEventOut(
        event_id=row.id,
        title=row.title,
        description=description,
        start_time=row.start_time,
        end_time=row.end_time,
        timezone=row.timezone,
        location=location,
        attendees=json_loads_or(row.attendees_json, []),
        status=row.status,
        provider=row.provider,
    )


def create_message(
    db: Session,
    payload: NovaCommsMessageCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaCommunicationsMessage:
    row = None
    for _ in range(5):
        row = NovaCommunicationsMessage(
            message_id=_new_id("NCM-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            sender=payload.sender.strip(),
            subject=payload.subject.strip(),
            body=payload.body or "",
            snippet=(payload.body or payload.subject)[:180],
            important=payload.important,
            source="local",
        )
        db.add(row)
        try:
            _notify(
                db,
                organization_id=organization_id,
                owner_user_id=user.user_id,
                kind="message_received",
                title=f"New message: {row.subject}",
                detail=f"From {row.sender}",
            )
            db.commit()
            db.refresh(row)
            return row
        except IntegrityError:
            db.rollback()
            row = None
    raise NovaCommunicationsError("Could not allocate a message ID", status_code=409)


def list_messages(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    important_only: bool = False,
    unread_only: bool = False,
) -> list[NovaCommunicationsMessage]:
    query = db.query(NovaCommunicationsMessage).filter(
        NovaCommunicationsMessage.organization_id == organization_id
    )
    query = _owner_filter(query, NovaCommunicationsMessage, user)
    if important_only:
        query = query.filter(NovaCommunicationsMessage.important.is_(True))
    if unread_only:
        query = query.filter(NovaCommunicationsMessage.read.is_(False))
    return query.order_by(NovaCommunicationsMessage.created_at.desc()).all()


def get_message(
    db: Session,
    message_id: str,
    *,
    organization_id: str,
    user: UserContext,
    mark_read: bool = True,
) -> NovaCommunicationsMessage:
    query = db.query(NovaCommunicationsMessage).filter(
        NovaCommunicationsMessage.message_id == message_id,
        NovaCommunicationsMessage.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaCommunicationsMessage, user)
    row = query.first()
    if row is None:
        raise NovaCommunicationsError("Message not found", status_code=404)
    if mark_read and not row.read:
        row.read = True
        db.commit()
        db.refresh(row)
    return row


def update_message(
    db: Session,
    message_id: str,
    payload: NovaCommsMessageUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaCommunicationsMessage:
    row = get_message(db, message_id, organization_id=organization_id, user=user, mark_read=False)
    if payload.read is not None:
        row.read = payload.read
    if payload.important is not None:
        row.important = payload.important
    db.commit()
    db.refresh(row)
    return row


def list_drafts(db: Session, *, user: UserContext) -> list[EmailDraftRecord]:
    return (
        db.query(EmailDraftRecord)
        .filter(EmailDraftRecord.user_id == user.user_id)
        .order_by(EmailDraftRecord.updated_at.desc())
        .limit(100)
        .all()
    )


def create_draft(
    db: Session,
    payload: NovaCommsDraftCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> EmailDraftRecord:
    row = EmailDraftRecord(
        id=uuid4(),
        user_id=user.user_id,
        provider="smtp",
        to_recipients=json_dumps(payload.to),
        cc_recipients=json_dumps(payload.cc),
        bcc_recipients=json_dumps(payload.bcc),
        subject=payload.subject.strip(),
        body=payload.body or "",
        attachments_json=json_dumps([]),
        status="draft",
        created_at=now(),
        updated_at=now(),
    )
    db.add(row)
    _notify(
        db,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        kind="draft_saved",
        title=f"Draft saved: {row.subject}",
        detail="External send was not performed.",
    )
    db.commit()
    db.refresh(row)
    return row


def send_blocked(payload: NovaCommsSendRequest) -> None:
    if not payload.confirm_send:
        raise NovaCommunicationsError(
            "Sending requires an explicit confirm_send action by the signed-in user.",
            status_code=400,
        )
    if not send_allowed():
        raise NovaCommunicationsError(
            "External email send is disabled. Save a draft instead. Stripe LIVE and autonomous send remain off.",
            status_code=403,
        )
    raise NovaCommunicationsError(
        "External send is not enabled in this Nova Communications phase. Use drafts.",
        status_code=403,
    )


def list_events(db: Session, *, user: UserContext) -> list[CalendarEventRecord]:
    return (
        db.query(CalendarEventRecord)
        .filter(CalendarEventRecord.user_id == user.user_id)
        .order_by(CalendarEventRecord.start_time.asc())
        .limit(200)
        .all()
    )


def create_event(
    db: Session,
    payload: NovaCommsEventCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> CalendarEventRecord:
    start_dt = _parse_iso(payload.start_time)
    end_dt = _parse_iso(payload.end_time)
    if end_dt <= start_dt:
        raise NovaCommunicationsError("end_time must be after start_time", status_code=422)
    description = payload.description or ""
    if payload.location:
        description = f"Location: {payload.location.strip()}\n{description}".strip()
    row = CalendarEventRecord(
        id=uuid4(),
        user_id=user.user_id,
        provider="local",
        title=payload.title.strip(),
        description=description or None,
        start_time=start_dt,
        end_time=end_dt,
        timezone=payload.timezone or "UTC",
        attendees_json=json_dumps(payload.attendees),
        reminder_minutes=15,
        status="confirmed",
        created_at=now(),
    )
    db.add(row)
    _notify(
        db,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        kind="calendar_created",
        title=f"Calendar event: {row.title}",
        detail="Created through existing local calendar records only.",
    )
    db.commit()
    db.refresh(row)
    return row


def list_notifications(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
) -> list[NovaCommsNotificationOut]:
    query = db.query(NovaCommunicationsNotification).filter(
        NovaCommunicationsNotification.organization_id == organization_id
    )
    query = _owner_filter(query, NovaCommunicationsNotification, user)
    rows = query.order_by(NovaCommunicationsNotification.created_at.desc()).limit(40).all()
    notices = [
        NovaCommsNotificationOut(
            notification_id=row.notification_id,
            kind=row.kind,
            title=row.title,
            detail=row.detail,
            link=row.link,
            read=row.read,
            created_at=row.created_at,
        )
        for row in rows
    ]
    activities = (
        db.query(NovaWorkspaceActivity)
        .filter(
            NovaWorkspaceActivity.organization_id == organization_id,
            NovaWorkspaceActivity.owner_user_id == user.user_id,
        )
        .order_by(NovaWorkspaceActivity.created_at.desc())
        .limit(8)
        .all()
    )
    for item in activities:
        notices.append(
            NovaCommsNotificationOut(
                notification_id=f"WS-{item.activity_id}",
                kind="workspace_activity",
                title=item.title,
                detail="Nova Workspace activity. Open Workspace for details.",
                link="/nova/workspace",
                read=True,
                created_at=item.created_at,
            )
        )
    notices.sort(key=lambda row: row.created_at, reverse=True)
    return notices[:40]


def mark_notification_read(
    db: Session,
    notification_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaCommunicationsNotification:
    query = db.query(NovaCommunicationsNotification).filter(
        NovaCommunicationsNotification.notification_id == notification_id,
        NovaCommunicationsNotification.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaCommunicationsNotification, user)
    row = query.first()
    if row is None:
        raise NovaCommunicationsError("Notification not found", status_code=404)
    row.read = True
    db.commit()
    db.refresh(row)
    return row


def derive_contacts(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
) -> list[NovaCommsContactOut]:
    seen: dict[str, NovaCommsContactOut] = {}
    for message in list_messages(db, organization_id=organization_id, user=user):
        key = message.sender.lower()
        seen[key] = NovaCommsContactOut(
            name=message.sender,
            email=message.sender if "@" in message.sender else None,
            recent_interaction=f"Message: {message.subject}",
        )
    for draft in list_drafts(db, user=user):
        for address in json_loads_or(draft.to_recipients, []):
            key = str(address).lower()
            seen.setdefault(
                key,
                NovaCommsContactOut(
                    name=str(address),
                    email=str(address) if "@" in str(address) else None,
                    recent_interaction=f"Draft: {draft.subject}",
                ),
            )
    for event in list_events(db, user=user):
        for address in json_loads_or(event.attendees_json, []):
            key = str(address).lower()
            seen.setdefault(
                key,
                NovaCommsContactOut(
                    name=str(address),
                    email=str(address) if "@" in str(address) else None,
                    recent_interaction=f"Calendar: {event.title}",
                ),
            )
    return list(seen.values())[:40]


def _connected(db: Session, user: UserContext, service: str) -> bool:
    row = (
        db.query(IntegrationAccount)
        .filter(IntegrationAccount.user_id == user.user_id, IntegrationAccount.service == service)
        .first()
    )
    return bool(row and row.account_email)


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> NovaCommsDashboardOut:
    messages = list_messages(db, organization_id=organization_id, user=user)
    drafts = [draft_out(row) for row in list_drafts(db, user=user) if row.status == "draft"]
    events = [event_out(row) for row in list_events(db, user=user)]
    current = now()
    today = [
        event
        for event in events
        if _as_utc(event.start_time).date() == current.date()
    ]
    upcoming = [event for event in events if _as_utc(event.start_time) >= current][:12]
    return NovaCommsDashboardOut(
        inbox=[message_out(row) for row in messages[:20]],
        important=[message_out(row) for row in messages if row.important][:12],
        drafts=drafts[:12],
        today=today,
        upcoming=upcoming,
        contacts=derive_contacts(db, organization_id=organization_id, user=user)[:12],
        notifications=list_notifications(db, organization_id=organization_id, user=user)[:16],
        recent=[{"kind": "message", "title": row.subject, "at": row.created_at.isoformat()} for row in messages[:8]],
        email_connected=_connected(db, user, "email"),
        calendar_connected=_connected(db, user, "calendar"),
        send_enabled=send_allowed(),
    )


def _context(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    message_id: str | None = None,
    notification_id: str | None = None,
) -> str:
    dash = dashboard(db, organization_id=organization_id, user=user)
    parts = [
        f"Inbox count {len(dash.inbox)}. Unread {sum(1 for row in dash.inbox if not row.read)}.",
        f"Drafts {len(dash.drafts)}. Today events {len(dash.today)}. Upcoming {len(dash.upcoming)}.",
    ]
    if dash.inbox:
        parts.append("Recent subjects: " + ", ".join(row.subject for row in dash.inbox[:5]))
    if dash.today or dash.upcoming:
        parts.append(
            "Calendar: "
            + ", ".join(row.title for row in (dash.today + dash.upcoming)[:6])
        )
    if message_id:
        row = get_message(db, message_id, organization_id=organization_id, user=user, mark_read=False)
        parts.append(f"Focused message from {row.sender}: {row.subject}. {row.body[:800]}")
    if notification_id and not notification_id.startswith("WS-"):
        query = db.query(NovaCommunicationsNotification).filter(
            NovaCommunicationsNotification.notification_id == notification_id,
            NovaCommunicationsNotification.organization_id == organization_id,
        )
        query = _owner_filter(query, NovaCommunicationsNotification, user)
        note = query.first()
        if note:
            parts.append(f"Notification {note.kind}: {note.title}. {note.detail or ''}")
    return " ".join(parts)


def ask_communications(
    db: Session,
    payload: NovaCommsBrainRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaCommsBrainOut:
    context = _context(
        db,
        organization_id=organization_id,
        user=user,
        message_id=payload.message_id,
        notification_id=payload.notification_id,
    )
    prompts = {
        "summarize_recent": "Summarize recent Nova Communications for the signed-in user.",
        "needs_attention": "Identify messages or drafts that need attention.",
        "draft_reply": "Draft a professional reply. Do not send it.",
        "summarize_thread": "Summarize the focused email or message thread.",
        "meeting_notes": "Prepare meeting notes from today's and upcoming calendar items.",
        "summarize_calendar": "Summarize today's and upcoming Nova calendar.",
        "follow_up": "Suggest follow-up actions from communications and calendar.",
        "locate_contact": payload.question or "Locate the requested person from communication history.",
        "explain_notification": "Explain the selected Nova notification without exposing secrets.",
        "ask": payload.question or "Help with Nova Communications.",
    }
    question = (
        "You are Mrs. Nova Brain. Separate VERIFIED DATA, USER-SAVED INFORMATION, and AI SUGGESTION. "
        "Do not send email.\n\n"
        + f"{prompts[payload.action]}\n\n{context}\n\n{payload.question or ''}"
    ).strip()
    asked = NovaCoreService.ask(
        db,
        organization_id=organization_id,
        mode="founder_advisor",
        question=question[:4000],
    )
    draft = None
    if payload.action == "draft_reply" and payload.message_id:
        source = get_message(
            db, payload.message_id, organization_id=organization_id, user=user, mark_read=False
        )
        draft = create_draft(
            db,
            NovaCommsDraftCreate(
                to=[source.sender] if "@" in source.sender else [],
                subject=f"Re: {source.subject}",
                body=asked.answer,
            ),
            organization_id=organization_id,
            user=user,
        )
    return NovaCommsBrainOut(
        action=payload.action,
        answer=asked.answer,
        fact_label="AI SUGGESTION unless the answer cites USER-SAVED INFORMATION or VERIFIED DATA. Nothing was sent.",
        draft=draft_out(draft) if draft else None,
        next_actions=asked.next_actions,
        generated_at=asked.generated_at,
    )
