"""Snap conversations, calls, and private captures.

Signaling stores SDP and ICE for participants of one call only.
Media bytes are never placed on a public path. Synapse and Casting are untouched.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.service import NovaCoreService

from . import media as media_store
from . import policy
from .models import (
    SnapBlock,
    SnapCall,
    SnapCallParticipant,
    SnapCapture,
    SnapContact,
    SnapConversation,
    SnapMember,
    SnapMessage,
    SnapReceipt,
    SnapReport,
    SnapSignal,
)

_buckets: dict[tuple[str, str], list[float]] = {}
_seq_indexes_ready = False
_NOT_FOUND = "Not found."
_QUALITIES = {"excellent", "good", "fair", "poor", "disconnected", "unknown"}
_SIGNAL_KINDS = {"offer", "answer", "ice", "quality", "renego", "media"}
_DESCRIPTION_KINDS = ("offer", "answer", "renego")


def reset_limits() -> None:
    _buckets.clear()


def _ensure_seq_indexes(db: Session) -> None:
    """Create the seq unique indexes when tables already exist from an older create_all.

    Run on this session's connection. A second connection can fail while the request
    already holds a SQLite transaction, and a failed attempt must stay retryable.
    """
    global _seq_indexes_ready
    if _seq_indexes_ready:
        return
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_snap_message_seq ON nova_snap_messages (conversation_id, seq)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_snap_signal_seq ON nova_snap_signals (call_id, seq)",
    )
    try:
        for statement in statements:
            db.execute(text(statement))
        db.commit()
    except Exception:
        db.rollback()
        return
    _seq_indexes_ready = True


def organization_id(user: UserContext) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, None)
    except ValueError as exc:
        raise HTTPException(403, "Organization access required.") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _pair(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def _rate(user_id: str, action: str, limit: int, window_s: int) -> None:
    now = time.monotonic()
    key = (user_id, action)
    bucket = [stamp for stamp in _buckets.get(key, []) if now - stamp < window_s]
    if len(bucket) >= limit:
        _buckets[key] = bucket
        raise HTTPException(429, "Too many Snap requests. Wait a moment and retry.")
    bucket.append(now)
    _buckets[key] = bucket


def _label(db: Session, user_id: str) -> str:
    try:
        from app.db.models import User as PlatformUser

        row = db.query(PlatformUser).filter(PlatformUser.id == user_id).one_or_none()
    except Exception:
        return "Member"
    if row is None:
        return "Member"
    name = (getattr(row, "display_name", None) or "").strip()
    if name:
        return name[:80]
    email = getattr(row, "email", "") or ""
    local = email.split("@", 1)[0].strip()
    return (local or "Member")[:80]


def _blocked(db: Session, org: str, a: str, b: str) -> bool:
    if a == b:
        return False
    return (
        db.query(SnapBlock)
        .filter(
            SnapBlock.organization_id == org,
            or_(
                and_(SnapBlock.blocker_user_id == a, SnapBlock.blocked_user_id == b),
                and_(SnapBlock.blocker_user_id == b, SnapBlock.blocked_user_id == a),
            ),
        )
        .first()
        is not None
    )


def _contact_row(db: Session, org: str, a: str, b: str) -> SnapContact | None:
    return (
        db.query(SnapContact)
        .filter(SnapContact.organization_id == org, SnapContact.pair_key == _pair(a, b))
        .one_or_none()
    )


def _accepted(db: Session, org: str, a: str, b: str) -> bool:
    row = _contact_row(db, org, a, b)
    return bool(row and row.status == "accepted" and not _blocked(db, org, a, b))


def _contact_out(db: Session, row: SnapContact, viewer: str) -> dict:
    peer = row.target_user_id if row.requester_user_id == viewer else row.requester_user_id
    return {
        "contact_id": row.contact_id,
        "peer_user_id": peer,
        "peer_label": _label(db, peer),
        "direction": "outgoing" if row.requester_user_id == viewer else "incoming",
        "status": row.status,
        "created_at": _aware(row.created_at).isoformat(),
    }


def profile(user: UserContext) -> dict:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "organization_id": organization_id(user),
        "product": "Nova Snap",
        "signed_in": True,
    }


def ice_for_member(user: UserContext) -> dict:
    organization_id(user)
    ice = policy.ice_config()
    return {
        "ice_servers": ice["ice_servers"],
        "stun_configured": ice["stun_configured"],
        "turn_configured": ice["turn_configured"],
        "quality_guarantee": False,
        "calling_mode": ice["calling_mode"],
        "calling_blocker": policy.public_status()["calling_blocker"],
    }


def request_contact(db: Session, user: UserContext, target_user_id: str) -> dict:
    org = organization_id(user)
    target = (target_user_id or "").strip()
    if not target or target == user.user_id:
        raise HTTPException(422, "Choose another person in your organization.")
    if _blocked(db, org, user.user_id, target):
        raise HTTPException(403, "Messaging is blocked between these accounts.")
    row = _contact_row(db, org, user.user_id, target)
    if row and row.status == "accepted":
        return _contact_out(db, row, user.user_id)
    _rate(user.user_id, "contact", *policy.CONTACT_RATE)
    now = _now()
    if row:
        row.requester_user_id = user.user_id
        row.target_user_id = target
        row.status = "pending"
        row.updated_at = now
    else:
        row = SnapContact(
            contact_id=str(uuid4()),
            organization_id=org,
            pair_key=_pair(user.user_id, target),
            requester_user_id=user.user_id,
            target_user_id=target,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = _contact_row(db, org, user.user_id, target)
        if not row:
            raise HTTPException(409, "Contact request could not be saved. Retry.")
    return _contact_out(db, row, user.user_id)


def respond_contact(db: Session, user: UserContext, contact_id: str, accept: bool) -> dict:
    org = organization_id(user)
    row = db.get(SnapContact, contact_id)
    if not row or row.organization_id != org or row.target_user_id != user.user_id or row.status != "pending":
        raise HTTPException(404, _NOT_FOUND)
    if _blocked(db, org, user.user_id, row.requester_user_id):
        raise HTTPException(403, "Messaging is blocked between these accounts.")
    row.status = "accepted" if accept else "declined"
    row.updated_at = _now()
    db.commit()
    return _contact_out(db, row, user.user_id)


def list_contacts(db: Session, user: UserContext) -> list[dict]:
    org = organization_id(user)
    rows = (
        db.query(SnapContact)
        .filter(
            SnapContact.organization_id == org,
            or_(SnapContact.requester_user_id == user.user_id, SnapContact.target_user_id == user.user_id),
        )
        .order_by(SnapContact.updated_at.desc())
        .all()
    )
    return [_contact_out(db, row, user.user_id) for row in rows]


def block_user(db: Session, user: UserContext, other_user_id: str) -> dict:
    org = organization_id(user)
    other = (other_user_id or "").strip()
    if not other or other == user.user_id:
        raise HTTPException(422, "Choose another person to block.")
    if not _blocked(db, org, user.user_id, other):
        db.add(
            SnapBlock(
                block_id=str(uuid4()),
                organization_id=org,
                blocker_user_id=user.user_id,
                blocked_user_id=other,
                created_at=_now(),
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"blocked_user_id": other, "blocked": True}


def unblock_user(db: Session, user: UserContext, other_user_id: str) -> dict:
    org = organization_id(user)
    db.query(SnapBlock).filter_by(
        organization_id=org, blocker_user_id=user.user_id, blocked_user_id=other_user_id
    ).delete()
    db.commit()
    return {"blocked_user_id": other_user_id, "blocked": False}


def _member(db: Session, conversation_id: str, user_id: str) -> SnapMember | None:
    return (
        db.query(SnapMember)
        .filter_by(conversation_id=conversation_id, user_id=user_id)
        .one_or_none()
    )


def _require_conversation(db: Session, user: UserContext, conversation_id: str) -> tuple[SnapConversation, SnapMember]:
    org = organization_id(user)
    row = db.get(SnapConversation, conversation_id)
    member = _member(db, conversation_id, user.user_id) if row else None
    if not row or row.organization_id != org or not member:
        raise HTTPException(404, _NOT_FOUND)
    others = db.query(SnapMember).filter_by(conversation_id=conversation_id).all()
    for other in others:
        if other.user_id != user.user_id and _blocked(db, org, user.user_id, other.user_id):
            raise HTTPException(404, _NOT_FOUND)
    return row, member


def _active_member(member: SnapMember) -> bool:
    return member.left_at is None


def _add_member(db: Session, conversation_id: str, user_id: str, role: str, when: datetime) -> None:
    db.add(
        SnapMember(
            member_id=str(uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            joined_at=when,
            left_at=None,
            last_read_seq=0,
        )
    )


def create_direct(db: Session, user: UserContext, peer_user_id: str) -> dict:
    org = organization_id(user)
    peer = (peer_user_id or "").strip()
    if not peer or peer == user.user_id:
        raise HTTPException(422, "Choose a contact.")
    if not _accepted(db, org, user.user_id, peer):
        raise HTTPException(403, "Both people have to accept the contact before messaging.")
    key = _pair(user.user_id, peer)
    existing = (
        db.query(SnapConversation)
        .filter_by(organization_id=org, kind="direct", pair_key=key)
        .one_or_none()
    )
    if existing:
        return _conversation_out(db, existing, user.user_id)
    now = _now()
    row = SnapConversation(
        conversation_id=str(uuid4()),
        organization_id=org,
        kind="direct",
        title="Direct message",
        pair_key=key,
        created_by=user.user_id,
        next_seq=0,
        created_at=now,
    )
    db.add(row)
    _add_member(db, row.conversation_id, user.user_id, "owner", now)
    _add_member(db, row.conversation_id, peer, "member", now)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(SnapConversation)
            .filter_by(organization_id=org, kind="direct", pair_key=key)
            .one_or_none()
        )
        if not existing:
            raise HTTPException(409, "Conversation could not be opened. Retry.")
        return _conversation_out(db, existing, user.user_id)
    return _conversation_out(db, row, user.user_id)


def create_group(db: Session, user: UserContext, title: str, user_ids: list[str]) -> dict:
    org = organization_id(user)
    try:
        clean_title = policy.title_text(title)
    except ValueError:
        raise HTTPException(422, "Enter a group name up to 80 characters.")
    peers = []
    for raw in user_ids or []:
        peer = (raw or "").strip()
        if peer and peer != user.user_id and peer not in peers:
            peers.append(peer)
    if not peers:
        raise HTTPException(422, "Add at least one accepted contact.")
    if len(peers) + 1 > policy.MAX_GROUP_MEMBERS:
        raise HTTPException(422, f"Groups can include up to {policy.MAX_GROUP_MEMBERS} people.")
    for peer in peers:
        if not _accepted(db, org, user.user_id, peer):
            raise HTTPException(403, "Every group member must be an accepted contact.")
    now = _now()
    row = SnapConversation(
        conversation_id=str(uuid4()),
        organization_id=org,
        kind="group",
        title=clean_title,
        pair_key=None,
        created_by=user.user_id,
        next_seq=0,
        created_at=now,
    )
    db.add(row)
    _add_member(db, row.conversation_id, user.user_id, "owner", now)
    for peer in peers:
        _add_member(db, row.conversation_id, peer, "member", now)
    db.commit()
    return _conversation_out(db, row, user.user_id)


def _unread(db: Session, conversation_id: str, member: SnapMember) -> int:
    return (
        db.query(SnapMessage)
        .filter(
            SnapMessage.conversation_id == conversation_id,
            SnapMessage.seq > member.last_read_seq,
            SnapMessage.sender_user_id != member.user_id,
            SnapMessage.deleted_at.is_(None),
        )
        .count()
    )


def _conversation_out(db: Session, row: SnapConversation, viewer: str) -> dict:
    member = _member(db, row.conversation_id, viewer)
    people = db.query(SnapMember).filter_by(conversation_id=row.conversation_id).all()
    return {
        "conversation_id": row.conversation_id,
        "kind": row.kind,
        "title": row.title,
        "left": bool(member and member.left_at),
        "unread": _unread(db, row.conversation_id, member) if member else 0,
        "members": [
            {"user_id": person.user_id, "label": _label(db, person.user_id), "left": person.left_at is not None}
            for person in people
        ],
    }


def list_conversations(db: Session, user: UserContext) -> list[dict]:
    org = organization_id(user)
    memberships = db.query(SnapMember).filter_by(user_id=user.user_id).all()
    rows = []
    for membership in memberships:
        conversation = db.get(SnapConversation, membership.conversation_id)
        if not conversation or conversation.organization_id != org:
            continue
        try:
            _require_conversation(db, user, conversation.conversation_id)
        except HTTPException:
            continue
        rows.append(conversation)
    rows.sort(key=lambda item: _aware(item.created_at) or _now(), reverse=True)
    return [_conversation_out(db, row, user.user_id) for row in rows]


def leave_conversation(db: Session, user: UserContext, conversation_id: str) -> dict:
    row, member = _require_conversation(db, user, conversation_id)
    if member.left_at is None:
        member.left_at = _now()
        db.commit()
    return _conversation_out(db, row, user.user_id)


def _visible(member: SnapMember, message: SnapMessage) -> bool:
    created = _aware(message.created_at)
    if created is None or created < _aware(member.joined_at):
        return False
    if member.left_at and created > _aware(member.left_at):
        return False
    return True


def _expire_message(message: SnapMessage, now: datetime) -> None:
    created = _aware(message.created_at)
    if message.deleted_at or created is None:
        return
    if created < now - timedelta(days=policy.MESSAGE_RETENTION_DAYS):
        message.body = ""
        message.deleted_at = now
        message.capture_id = None


def _delivery(db: Session, message: SnapMessage) -> str:
    if message.deleted_at:
        return "removed"
    receipts = db.query(SnapReceipt).filter_by(message_id=message.message_id).all()
    others = [row for row in receipts if row.user_id != message.sender_user_id]
    if others and all(row.read_at for row in others):
        return "read"
    if any(row.delivered_at for row in others):
        return "delivered"
    return "stored"


def _message_out(db: Session, message: SnapMessage, *, duplicate: bool = False) -> dict:
    removed = message.deleted_at is not None
    return {
        "message_id": message.message_id,
        "conversation_id": message.conversation_id,
        "seq": message.seq,
        "sender_user_id": message.sender_user_id,
        "sender_label": _label(db, message.sender_user_id),
        "kind": message.kind,
        "body": "" if removed else message.body,
        "removed": removed,
        "capture_id": None if removed else message.capture_id,
        "untrusted_links": False if removed else bool(message.untrusted_links),
        "delivery": _delivery(db, message),
        "client_message_id": message.client_message_id,
        "created_at": _aware(message.created_at).isoformat(),
        "duplicate": duplicate,
    }


def _find_client_message(db: Session, conversation_id: str, sender: str, client_message_id: str) -> SnapMessage | None:
    return (
        db.query(SnapMessage)
        .filter_by(conversation_id=conversation_id, sender_user_id=sender, client_message_id=client_message_id)
        .one_or_none()
    )


def _allocate_message_seq(db: Session, conversation_id: str) -> int:
    """Increment the conversation counter in one UPDATE so overlapping sends cannot share a seq."""
    stmt = (
        update(SnapConversation)
        .where(SnapConversation.conversation_id == conversation_id)
        .values(next_seq=func.coalesce(SnapConversation.next_seq, 0) + 1)
        .returning(SnapConversation.next_seq)
        .execution_options(synchronize_session=False)
    )
    return int(db.execute(stmt).scalar_one())


def _allocate_signal_seq(db: Session, call_id: str) -> int:
    """Serialize signal numbers on the call row, then take max(seq)+1."""
    query = db.query(SnapCall).filter(SnapCall.call_id == call_id)
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update()
    query.one()
    current = db.query(func.max(SnapSignal.seq)).filter(SnapSignal.call_id == call_id).scalar()
    return int(current or 0) + 1


def post_message(
    db: Session,
    user: UserContext,
    conversation_id: str,
    body: str,
    client_message_id: str,
    *,
    kind: str = "text",
    capture_id: str | None = None,
) -> dict:
    conversation, member = _require_conversation(db, user, conversation_id)
    if not _active_member(member):
        raise HTTPException(403, "You left this conversation.")
    try:
        client_key = policy.client_id(client_message_id)
    except ValueError:
        raise HTTPException(422, "A client message id must be 8 to 80 letters, numbers, dashes, or underscores.")
    existing = _find_client_message(db, conversation.conversation_id, user.user_id, client_key)
    if existing:
        return _message_out(db, existing, duplicate=True)
    if kind == "text":
        try:
            checked = policy.message_text(body)
        except ValueError as exc:
            code = str(exc)
            if code == "unsafe":
                raise HTTPException(400, "That message was blocked because it contains an unsafe link or script.")
            raise HTTPException(422, "Enter a message up to 2000 characters.")
        stored_body = checked["body"]
        untrusted = checked["untrusted_links"]
    else:
        stored_body = body
        untrusted = False
    _rate(user.user_id, "message", *policy.MESSAGE_RATE)
    _ensure_seq_indexes(db)
    conversation_id = conversation.conversation_id
    message = None
    for _attempt in range(4):
        seq = _allocate_message_seq(db, conversation_id)
        db.expire(conversation)
        message = SnapMessage(
            message_id=str(uuid4()),
            conversation_id=conversation_id,
            organization_id=conversation.organization_id,
            sender_user_id=user.user_id,
            client_message_id=client_key,
            seq=seq,
            kind=kind,
            body=stored_body,
            capture_id=capture_id,
            untrusted_links=untrusted,
            created_at=_now(),
            deleted_at=None,
        )
        db.add(message)
        try:
            db.commit()
            return _message_out(db, message)
        except IntegrityError:
            db.rollback()
            existing = _find_client_message(db, conversation_id, user.user_id, client_key)
            if existing:
                return _message_out(db, existing, duplicate=True)
    raise HTTPException(409, "Message could not be saved. Retry with the same client id.")


def list_messages(db: Session, user: UserContext, conversation_id: str, after_seq: int = 0) -> list[dict]:
    _conversation, member = _require_conversation(db, user, conversation_id)
    now = _now()
    rows = (
        db.query(SnapMessage)
        .filter(SnapMessage.conversation_id == conversation_id, SnapMessage.seq > after_seq)
        .order_by(SnapMessage.seq.asc())
        .limit(100)
        .all()
    )
    visible = []
    for message in rows:
        _expire_message(message, now)
        if not _visible(member, message):
            continue
        if message.sender_user_id != user.user_id and message.deleted_at is None:
            _mark_delivered(db, message.message_id, user.user_id, now)
        visible.append(message)
    db.commit()
    return [_message_out(db, message) for message in visible]


def _mark_delivered(db: Session, message_id: str, user_id: str, when: datetime) -> None:
    receipt = db.query(SnapReceipt).filter_by(message_id=message_id, user_id=user_id).one_or_none()
    if receipt is None:
        db.add(
            SnapReceipt(
                receipt_id=str(uuid4()),
                message_id=message_id,
                user_id=user_id,
                delivered_at=when,
                read_at=None,
            )
        )
    elif receipt.delivered_at is None:
        receipt.delivered_at = when


def mark_read(db: Session, user: UserContext, conversation_id: str, message_id: str) -> dict:
    _conversation, member = _require_conversation(db, user, conversation_id)
    message = db.get(SnapMessage, message_id)
    if not message or message.conversation_id != conversation_id or not _visible(member, message):
        raise HTTPException(404, _NOT_FOUND)
    if message.seq > member.last_read_seq:
        member.last_read_seq = message.seq
    now = _now()
    if message.sender_user_id != user.user_id:
        receipt = db.query(SnapReceipt).filter_by(message_id=message.message_id, user_id=user.user_id).one_or_none()
        if receipt is None:
            db.add(
                SnapReceipt(
                    receipt_id=str(uuid4()),
                    message_id=message.message_id,
                    user_id=user.user_id,
                    delivered_at=now,
                    read_at=now,
                )
            )
        else:
            receipt.delivered_at = receipt.delivered_at or now
            receipt.read_at = now
    db.commit()
    return {"conversation_id": conversation_id, "last_read_seq": member.last_read_seq}


def delete_message(db: Session, user: UserContext, message_id: str) -> dict:
    message = db.get(SnapMessage, message_id)
    if not message or message.sender_user_id != user.user_id:
        raise HTTPException(404, _NOT_FOUND)
    _require_conversation(db, user, message.conversation_id)
    if message.deleted_at is None:
        message.body = ""
        message.capture_id = None
        message.untrusted_links = False
        message.deleted_at = _now()
        db.commit()
    return _message_out(db, message)


def report_message(
    db: Session,
    user: UserContext,
    *,
    target_user_id: str,
    reason: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
) -> dict:
    org = organization_id(user)
    target = (target_user_id or "").strip()
    if not target or target == user.user_id:
        raise HTTPException(422, "Choose the account you are reporting.")
    try:
        clean = policy.reason_text(reason)
    except ValueError as exc:
        if str(exc) == "unsafe":
            raise HTTPException(400, "The report text was blocked because it contains an unsafe link or script.")
        raise HTTPException(422, "Enter a report reason between 3 and 500 characters.")
    if conversation_id:
        _require_conversation(db, user, conversation_id)
    if message_id:
        message = db.get(SnapMessage, message_id)
        if not message or (conversation_id and message.conversation_id != conversation_id):
            raise HTTPException(404, _NOT_FOUND)
        _require_conversation(db, user, message.conversation_id)
        conversation_id = message.conversation_id
    _rate(user.user_id, "report", 10, 3600)
    row = SnapReport(
        report_id=str(uuid4()),
        organization_id=org,
        reporter_user_id=user.user_id,
        target_user_id=target,
        conversation_id=conversation_id,
        message_id=message_id,
        reason=clean,
        created_at=_now(),
    )
    db.add(row)
    db.commit()
    return {
        "report_id": row.report_id,
        "stored": True,
        "moderator_delivery": False,
        "note": "Report saved for the account owner of this preview. It is not emailed and no moderator inbox is connected.",
    }


def list_reports(db: Session, user: UserContext) -> list[dict]:
    org = organization_id(user)
    rows = (
        db.query(SnapReport)
        .filter_by(organization_id=org, reporter_user_id=user.user_id)
        .order_by(SnapReport.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "report_id": row.report_id,
            "target_user_id": row.target_user_id,
            "conversation_id": row.conversation_id,
            "message_id": row.message_id,
            "reason": row.reason,
            "moderator_delivery": False,
        }
        for row in rows
    ]


def _call_participants(db: Session, call_id: str) -> list[SnapCallParticipant]:
    return db.query(SnapCallParticipant).filter_by(call_id=call_id).all()


def _participant_age(person: SnapCallParticipant, now: datetime) -> float:
    seen = _aware(person.last_seen)
    if seen is None:
        return float(policy.FAIL_AFTER_S + 1)
    return (now - seen).total_seconds()


def _media_senders(db: Session, call_id: str) -> set[str]:
    rows = (
        db.query(SnapSignal.sender_user_id)
        .filter(SnapSignal.call_id == call_id, SnapSignal.kind.in_(_DESCRIPTION_KINDS + ("ice",)))
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def _silence_limits(has_media: bool) -> tuple[float, float]:
    if has_media:
        return float(policy.RECONNECT_AFTER_S), float(policy.FAIL_AFTER_S)
    return float(policy.PERMISSION_GRACE_S), float(policy.PERMISSION_GRACE_S)


def _touch_liveness(db: Session, call: SnapCall) -> SnapCall:
    if call.state not in {"ringing", "active"}:
        return call
    people = _call_participants(db, call.call_id)
    if not people:
        return call
    now = _now()
    if call.state == "ringing":
        started = _aware(call.created_at)
        ring_age = (now - started).total_seconds() if started else 0
        if ring_age > policy.RING_TIMEOUT_S:
            call.state = "ended"
            call.ended_reason = "unanswered"
            call.ended_at = now
            db.commit()
        return call
    live = [person for person in people if person.state in {"accepted", "reconnecting"}]
    senders = _media_senders(db, call.call_id)
    limits = {person.user_id: _silence_limits(person.user_id in senders) for person in live}
    stale = [person for person in live if _participant_age(person, now) > limits[person.user_id][1]]
    stale_ids = {person.user_id for person in stale}
    remaining = [person for person in live if person.user_id not in stale_ids]
    # Count only people still in the call, so an invited or already-left row
    # cannot hide a 1:1 timeout. A quiet peer is marked left while two or more
    # people remain. Fewer than two remaining ends the call, including when
    # several peers go quiet in the same check.
    if stale and len(remaining) < 2:
        call.state = "failed"
        call.ended_reason = "network_timeout"
        call.ended_at = now
        for person in people:
            if person.state in {"accepted", "reconnecting", "invited"}:
                person.state = "left"
        _delete_signals(db, call.call_id)
        db.commit()
        return call
    changed = False
    for person in stale:
        person.state = "left"
        changed = True
    for person in live:
        reconnect_after = limits[person.user_id][0]
        if person.state == "accepted" and _participant_age(person, now) > reconnect_after:
            person.state = "reconnecting"
            changed = True
    if changed:
        db.commit()
    return call


def _session_hint(call: SnapCall, me: SnapCallParticipant | None) -> str:
    """Server phase. `active` means the invite was accepted, not that media flowed."""
    if me and me.state == "declined":
        return "declined"
    if call.state == "declined":
        return "declined"
    if call.state == "failed":
        return "failed"
    if (me and me.state == "left") or call.state == "ended":
        return "ended"
    if me and me.state == "reconnecting":
        return "reconnecting"
    if me and me.state == "invited" and call.state == "ringing":
        return "ringing_in"
    if call.state == "ringing":
        return "ringing_out"
    if call.state == "active":
        return "active"
    return call.state


def _call_out(db: Session, call: SnapCall, viewer: str) -> dict:
    call = _touch_liveness(db, call)
    people = _call_participants(db, call.call_id)
    me = next((person for person in people if person.user_id == viewer), None)
    ice = policy.public_status()
    return {
        "call_id": call.call_id,
        "conversation_id": call.conversation_id,
        "media": call.media,
        "state": call.state,
        "session_hint": _session_hint(call, me),
        "ended_reason": call.ended_reason,
        "my_state": me.state if me else None,
        "quality": me.last_quality if me else "unknown",
        "turn_configured": ice["turn_configured"],
        "quality_guarantee": False,
        "calling_blocker": ice["calling_blocker"],
        "participants": [
            {"user_id": person.user_id, "label": _label(db, person.user_id), "state": person.state, "quality": person.last_quality}
            for person in people
        ],
    }


def _require_call(db: Session, user: UserContext, call_id: str) -> tuple[SnapCall, SnapCallParticipant]:
    org = organization_id(user)
    call = db.get(SnapCall, call_id)
    if not call or call.organization_id != org:
        raise HTTPException(404, _NOT_FOUND)
    _require_conversation(db, user, call.conversation_id)
    me = (
        db.query(SnapCallParticipant)
        .filter_by(call_id=call.call_id, user_id=user.user_id)
        .one_or_none()
    )
    if not me:
        raise HTTPException(404, _NOT_FOUND)
    return _touch_liveness(db, call), me


def start_call(db: Session, user: UserContext, conversation_id: str, media: str) -> dict:
    if media not in {"audio", "video"}:
        raise HTTPException(422, "Choose an audio or video call.")
    conversation, member = _require_conversation(db, user, conversation_id)
    if not _active_member(member):
        raise HTTPException(403, "You left this conversation.")
    open_call = (
        db.query(SnapCall)
        .filter(SnapCall.conversation_id == conversation.conversation_id, SnapCall.state.in_(("ringing", "active")))
        .first()
    )
    if open_call:
        _touch_liveness(db, open_call)
        db.refresh(open_call)
        if open_call.state in {"ringing", "active"}:
            raise HTTPException(409, "A call is already open in this conversation.")
    others = [
        person
        for person in db.query(SnapMember).filter_by(conversation_id=conversation.conversation_id).all()
        if person.user_id != user.user_id and person.left_at is None
    ]
    if not others:
        raise HTTPException(422, "Nobody else is in this conversation.")
    _rate(user.user_id, "call", *policy.CALL_RATE)
    now = _now()
    call = SnapCall(
        call_id=str(uuid4()),
        organization_id=conversation.organization_id,
        conversation_id=conversation.conversation_id,
        caller_user_id=user.user_id,
        media=media,
        state="ringing",
        ended_reason=None,
        created_at=now,
        ended_at=None,
    )
    db.add(call)
    db.add(
        SnapCallParticipant(
            participant_id=str(uuid4()),
            call_id=call.call_id,
            user_id=user.user_id,
            state="accepted",
            last_quality="unknown",
            last_seen=now,
        )
    )
    for person in others:
        db.add(
            SnapCallParticipant(
                participant_id=str(uuid4()),
                call_id=call.call_id,
                user_id=person.user_id,
                state="invited",
                last_quality="unknown",
                last_seen=now,
            )
        )
    db.commit()
    return _call_out(db, call, user.user_id)


def list_incoming(db: Session, user: UserContext) -> list[dict]:
    org = organization_id(user)
    rows = (
        db.query(SnapCallParticipant)
        .filter_by(user_id=user.user_id, state="invited")
        .all()
    )
    calls = []
    for row in rows:
        call = db.get(SnapCall, row.call_id)
        if not call or call.organization_id != org or call.state != "ringing":
            continue
        try:
            _require_conversation(db, user, call.conversation_id)
        except HTTPException:
            continue
        calls.append(_call_out(db, call, user.user_id))
    return calls


def get_call(db: Session, user: UserContext, call_id: str) -> dict:
    call, _me = _require_call(db, user, call_id)
    return _call_out(db, call, user.user_id)


def _finish_if_nobody(db: Session, call: SnapCall) -> None:
    people = _call_participants(db, call.call_id)
    accepted = [person for person in people if person.state in {"accepted", "reconnecting"}]
    invited = [person for person in people if person.state == "invited"]
    if len(accepted) >= 2:
        if call.state == "ringing":
            call.state = "active"
        return
    if invited:
        return
    declined = any(person.state == "declined" for person in people)
    call.state = "declined" if declined else "ended"
    call.ended_reason = "declined" if declined else "hangup"
    call.ended_at = _now()
    _delete_signals(db, call.call_id)


def accept_call(db: Session, user: UserContext, call_id: str) -> dict:
    call, me = _require_call(db, user, call_id)
    if call.state not in {"ringing", "active"} or me.state not in {"invited", "reconnecting"}:
        raise HTTPException(409, "This call is no longer waiting for an answer.")
    me.state = "accepted"
    me.last_seen = _now()
    call.state = "active"
    db.commit()
    return _call_out(db, call, user.user_id)


def decline_call(db: Session, user: UserContext, call_id: str) -> dict:
    call, me = _require_call(db, user, call_id)
    if me.state == "invited":
        me.state = "declined"
        me.last_seen = _now()
        _finish_if_nobody(db, call)
        db.commit()
    return _call_out(db, call, user.user_id)


def _ended_reason_for(db: Session, call_id: str, user_id: str) -> str:
    latest = (
        db.query(SnapSignal)
        .filter_by(call_id=call_id, sender_user_id=user_id, kind="media")
        .order_by(SnapSignal.seq.desc())
        .first()
    )
    if latest is not None and latest.payload == "denied":
        return "permission_denied"
    return "hangup"


def end_call(db: Session, user: UserContext, call_id: str) -> dict:
    call, me = _require_call(db, user, call_id)
    me.state = "left"
    me.last_seen = _now()
    people = _call_participants(db, call.call_id)
    still = [person for person in people if person.state in {"accepted", "reconnecting", "invited"}]
    if len([person for person in people if person.state in {"accepted", "reconnecting"}]) < 2:
        call.state = "ended"
        call.ended_reason = _ended_reason_for(db, call.call_id, user.user_id)
        call.ended_at = _now()
        for person in still:
            person.state = "left"
        _delete_signals(db, call.call_id)
    db.commit()
    return _call_out(db, call, user.user_id)


def reconnect_call(db: Session, user: UserContext, call_id: str) -> dict:
    call, me = _require_call(db, user, call_id)
    if call.state not in {"ringing", "active"} or me.state not in {"accepted", "reconnecting"}:
        raise HTTPException(409, "The call ended. Start a new call. A relay server is not configured, so some networks cannot reconnect.")
    me.state = "reconnecting"
    me.last_seen = _now()
    me.last_quality = "disconnected"
    db.commit()
    return _call_out(db, call, user.user_id)


def _delete_signals(db: Session, call_id: str) -> None:
    db.query(SnapSignal).filter_by(call_id=call_id).delete()


def _signal_target(payload: str) -> str | None:
    if not payload or not payload.startswith("{"):
        return None
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    target = body.get("target")
    return target if isinstance(target, str) else None


def _offer_was_answered(offer: SnapSignal, others: list[SnapSignal]) -> bool:
    target = _signal_target(offer.payload)
    for other in others:
        if other.kind != "answer" or other.seq <= offer.seq:
            continue
        if target is None or other.sender_user_id == target:
            return True
    return False


def _assert_description_order(db: Session, call: SnapCall, user_id: str, kind: str, text: str) -> None:
    rows = db.query(SnapSignal).filter(SnapSignal.call_id == call.call_id, SnapSignal.kind.in_(_DESCRIPTION_KINDS)).all()
    mine = [row for row in rows if row.sender_user_id == user_id]
    others = [row for row in rows if row.sender_user_id != user_id]
    if kind == "renego" and call.state != "active":
        raise HTTPException(409, "Restart the connection only after the call is active.")
    if kind == "answer" and not any(row.kind in {"offer", "renego"} for row in others):
        raise HTTPException(409, "Wait for the other person's call offer before answering.")
    if kind in {"offer", "renego"}:
        target = _signal_target(text)
        for row in mine:
            if row.kind not in {"offer", "renego"}:
                continue
            if _signal_target(row.payload) != target:
                continue
            if _offer_was_answered(row, others):
                continue
            # An active ICE restart replaces this sender's unanswered description.
            # A second offer, or a restart while the call is still ringing, does not.
            if kind == "renego" and call.state == "active":
                continue
            raise HTTPException(409, "An offer is already waiting for an answer.")


def _assert_ice_ready(db: Session, call: SnapCall, user_id: str) -> None:
    found = (
        db.query(SnapSignal.signal_id)
        .filter(
            SnapSignal.call_id == call.call_id,
            SnapSignal.sender_user_id == user_id,
            SnapSignal.kind.in_(_DESCRIPTION_KINDS),
        )
        .first()
    )
    if found is None:
        raise HTTPException(409, "Send the call description before network candidates.")


def _prepare_signal(db: Session, call: SnapCall, user_id: str, kind: str, payload: str) -> str:
    text = payload if isinstance(payload, str) else ""
    if kind == "quality":
        if text not in _QUALITIES:
            raise HTTPException(422, "Quality must be excellent, good, fair, poor, disconnected, or unknown.")
        return text
    if kind == "media":
        if text not in {"denied", "granted"}:
            raise HTTPException(422, "Media permission must be granted or denied.")
        return text
    if kind in _DESCRIPTION_KINDS:
        try:
            text = policy.normalize_description(text, call.media)
        except ValueError as exc:
            if str(exc) == "relay":
                raise HTTPException(
                    422,
                    "That path needs a TURN relay. No relay is configured, and this preview did not buy one.",
                ) from exc
            raise HTTPException(422, "The call description must include session data for this audio or video call.") from exc
        _assert_description_order(db, call, user_id, kind, text)
        return text
    if kind == "ice":
        try:
            text = policy.normalize_ice(text)
        except ValueError as exc:
            if str(exc) == "relay":
                raise HTTPException(
                    422,
                    "That candidate needs a TURN relay. No relay is configured, and this preview did not buy one.",
                ) from exc
            raise HTTPException(422, "The network candidate is not valid.") from exc
        _assert_ice_ready(db, call, user_id)
        return text
    raise HTTPException(422, "Unsupported call signal.")


def post_signal(
    db: Session,
    user: UserContext,
    call_id: str,
    *,
    kind: str,
    payload: str,
    client_signal_id: str,
) -> dict:
    call, me = _require_call(db, user, call_id)
    if kind not in _SIGNAL_KINDS:
        raise HTTPException(422, "Unsupported call signal.")
    if call.state not in {"ringing", "active"} or me.state not in {"accepted", "reconnecting"}:
        raise HTTPException(409, "Join the call before sending audio or video signals.")
    try:
        client_key = policy.client_id(client_signal_id)
    except ValueError:
        raise HTTPException(422, "A client signal id must be 8 to 80 letters, numbers, dashes, or underscores.")
    existing = (
        db.query(SnapSignal)
        .filter_by(call_id=call.call_id, sender_user_id=user.user_id, client_signal_id=client_key)
        .one_or_none()
    )
    if existing:
        return {"signal_id": existing.signal_id, "seq": existing.seq, "duplicate": True}
    text = _prepare_signal(db, call, user.user_id, kind, payload)
    _rate(user.user_id, "signal", *policy.SIGNAL_RATE)
    _ensure_seq_indexes(db)
    if kind == "quality":
        me.last_quality = text
    call_id = call.call_id
    for _attempt in range(4):
        seq = _allocate_signal_seq(db, call_id)
        row = SnapSignal(
            signal_id=str(uuid4()),
            call_id=call_id,
            sender_user_id=user.user_id,
            seq=seq,
            client_signal_id=client_key,
            kind=kind,
            payload=text,
            created_at=_now(),
        )
        me.last_seen = row.created_at
        if me.state == "reconnecting" and kind in {"offer", "answer", "ice", "renego"}:
            me.state = "accepted"
            if call.state == "ringing":
                call.state = "active"
        db.add(row)
        try:
            db.commit()
            return {"signal_id": row.signal_id, "seq": row.seq, "duplicate": False}
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(SnapSignal)
                .filter_by(call_id=call_id, sender_user_id=user.user_id, client_signal_id=client_key)
                .one_or_none()
            )
            if existing:
                return {"signal_id": existing.signal_id, "seq": existing.seq, "duplicate": True}
    raise HTTPException(409, "Call signal could not be saved. Retry with the same client id.")


def _latest_description_ids(rows: list[SnapSignal]) -> set[str]:
    latest: dict[tuple[str, str | None], str] = {}
    for row in rows:
        if row.kind not in {"offer", "renego"}:
            continue
        latest[(row.sender_user_id, _signal_target(row.payload))] = row.signal_id
    return set(latest.values())


def list_signals(db: Session, user: UserContext, call_id: str, after_seq: int = 0) -> list[dict]:
    call, me = _require_call(db, user, call_id)
    if me.state in {"declined", "left"} or call.state in {"ended", "failed", "declined"}:
        return []
    rows = (
        db.query(SnapSignal)
        .filter(SnapSignal.call_id == call.call_id, SnapSignal.seq > after_seq, SnapSignal.sender_user_id != user.user_id)
        .order_by(SnapSignal.seq.asc())
        .limit(100)
        .all()
    )
    current = _latest_description_ids(rows)
    visible = []
    for row in rows:
        if row.kind in {"offer", "renego"} and row.signal_id not in current:
            continue
        visible.append(row)
    return [
        {"signal_id": row.signal_id, "seq": row.seq, "sender_user_id": row.sender_user_id, "kind": row.kind, "payload": row.payload}
        for row in visible
    ]


def _capture_out(row: SnapCapture) -> dict:
    return {
        "capture_id": row.capture_id,
        "status": row.status,
        "content_type": row.content_type,
        "byte_size": row.byte_size,
        "duration_ms": row.duration_ms,
        "conversation_id": row.conversation_id,
        "created_at": _aware(row.created_at).isoformat(),
        "expires_at": _aware(row.expires_at).isoformat(),
        "public_url": None,
    }


def _expire_capture(db: Session, row: SnapCapture) -> None:
    if row.status == "deleted":
        return
    expires = _aware(row.expires_at)
    if expires and expires <= _now():
        media_store.delete_bytes(row.storage_key)
        row.status = "deleted"
        row.deleted_at = _now()
        row.conversation_id = None
        db.commit()


def save_capture(
    db: Session,
    user: UserContext,
    *,
    data: bytes,
    declared_type: str,
    duration_ms: int,
) -> dict:
    org = organization_id(user)
    sniffed = policy.sniff_media(data, declared_type)
    if not sniffed:
        raise HTTPException(400, "Use a JPEG, PNG, WebP, WebM, or MP4 file from the camera picker.")
    if len(data) > policy.media_limit(sniffed) or len(data) == 0:
        raise HTTPException(413, "That camera file is over the preview size limit.")
    if sniffed.startswith("video/"):
        if duration_ms < policy.MIN_CLIP_MS or duration_ms > policy.MAX_CLIP_MS:
            raise HTTPException(422, "Video clips must be 15 seconds or shorter.")
    elif duration_ms not in {0} and duration_ms > policy.MAX_CLIP_MS:
        raise HTTPException(422, "That photo description is not valid.")
    _rate(user.user_id, "capture", *policy.CAPTURE_RATE)
    now = _now()
    row = SnapCapture(
        capture_id=str(uuid4()),
        organization_id=org,
        owner_user_id=user.user_id,
        conversation_id=None,
        storage_key=uuid4().hex,
        content_type=sniffed,
        byte_size=len(data),
        duration_ms=duration_ms if sniffed.startswith("video/") else 0,
        status="draft",
        created_at=now,
        expires_at=now + timedelta(hours=policy.CAPTURE_RETENTION_HOURS),
        shared_at=None,
        deleted_at=None,
    )
    media_store.write_bytes(row.storage_key, data)
    db.add(row)
    db.commit()
    return _capture_out(row)


def list_captures(db: Session, user: UserContext) -> list[dict]:
    org = organization_id(user)
    rows = (
        db.query(SnapCapture)
        .filter_by(organization_id=org, owner_user_id=user.user_id)
        .order_by(SnapCapture.created_at.desc())
        .limit(50)
        .all()
    )
    visible = []
    for row in rows:
        _expire_capture(db, row)
        if row.status != "deleted":
            visible.append(_capture_out(row))
    return visible


def _owned_capture(db: Session, user: UserContext, capture_id: str) -> SnapCapture:
    org = organization_id(user)
    row = db.get(SnapCapture, capture_id)
    if not row or row.organization_id != org or row.owner_user_id != user.user_id:
        raise HTTPException(404, _NOT_FOUND)
    _expire_capture(db, row)
    db.refresh(row)
    if row.status == "deleted":
        raise HTTPException(404, _NOT_FOUND)
    return row


def share_capture(db: Session, user: UserContext, capture_id: str, conversation_id: str, consent: bool) -> dict:
    if consent is not True:
        raise HTTPException(400, "Sharing needs an explicit consent confirmation.")
    row = _owned_capture(db, user, capture_id)
    if row.status == "shared":
        raise HTTPException(409, "This draft was already shared. Delete it before sharing another copy.")
    _conversation, member = _require_conversation(db, user, conversation_id)
    if not _active_member(member):
        raise HTTPException(403, "You left this conversation.")
    post_message(
        db,
        user,
        conversation_id,
        "Shared a private camera draft.",
        "cap" + row.capture_id.replace("-", "")[:20],
        kind="capture",
        capture_id=row.capture_id,
    )
    row.status = "shared"
    row.conversation_id = conversation_id
    row.shared_at = _now()
    db.commit()
    return _capture_out(row)


def delete_capture(db: Session, user: UserContext, capture_id: str) -> dict:
    org = organization_id(user)
    row = db.get(SnapCapture, capture_id)
    if not row or row.organization_id != org or row.owner_user_id != user.user_id:
        raise HTTPException(404, _NOT_FOUND)
    media_store.delete_bytes(row.storage_key)
    row.status = "deleted"
    row.deleted_at = _now()
    row.conversation_id = None
    db.commit()
    return {"capture_id": capture_id, "deleted": True}


def open_capture(db: Session, user: UserContext, capture_id: str) -> tuple[SnapCapture, str]:
    org = organization_id(user)
    row = db.get(SnapCapture, capture_id)
    if not row or row.organization_id != org:
        raise HTTPException(404, _NOT_FOUND)
    _expire_capture(db, row)
    db.refresh(row)
    if row.status == "deleted":
        raise HTTPException(404, _NOT_FOUND)
    if row.owner_user_id == user.user_id:
        return row, str(media_store.read_path(row.storage_key))
    if row.status != "shared" or not row.conversation_id:
        raise HTTPException(404, _NOT_FOUND)
    _require_conversation(db, user, row.conversation_id)
    member = _member(db, row.conversation_id, user.user_id)
    if not member or (member.left_at and _aware(row.shared_at) and _aware(row.shared_at) > _aware(member.left_at)):
        raise HTTPException(404, _NOT_FOUND)
    return row, str(media_store.read_path(row.storage_key))


def remove_my_content(db: Session, user: UserContext) -> dict:
    org = organization_id(user)
    now = _now()
    messages = (
        db.query(SnapMessage)
        .filter_by(organization_id=org, sender_user_id=user.user_id)
        .all()
    )
    removed_messages = 0
    for message in messages:
        if message.deleted_at is None:
            message.body = ""
            message.capture_id = None
            message.untrusted_links = False
            message.deleted_at = now
            removed_messages += 1
    captures = db.query(SnapCapture).filter_by(organization_id=org, owner_user_id=user.user_id).all()
    removed_captures = 0
    for capture in captures:
        if capture.status != "deleted":
            media_store.delete_bytes(capture.storage_key)
            capture.status = "deleted"
            capture.deleted_at = now
            capture.conversation_id = None
            removed_captures += 1
    memberships = db.query(SnapMember).filter_by(user_id=user.user_id).all()
    for membership in memberships:
        conversation = db.get(SnapConversation, membership.conversation_id)
        if conversation and conversation.organization_id == org and membership.left_at is None:
            membership.left_at = now
    pending = (
        db.query(SnapContact)
        .filter_by(organization_id=org, requester_user_id=user.user_id, status="pending")
        .all()
    )
    for contact in pending:
        db.delete(contact)
    db.commit()
    return {
        "messages_removed": removed_messages,
        "captures_removed": removed_captures,
        "pending_invites_removed": len(pending),
        "blocks_kept": True,
    }
