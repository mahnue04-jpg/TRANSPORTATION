"""Recipient-approved snapshot copies. Never transfers authentication or upload access."""
from datetime import timedelta, timezone
import hashlib
import json

from sqlalchemy.exc import IntegrityError

from app.helpers import now
from . import service
from .models import (NovaWorkspaceTransfer, NovaWorkspaceProject, NovaWorkspaceFile,
                     NovaWorkspaceConversation, NovaWorkspaceMessage)


def summary(row):
    snapshot = json.loads(row.snapshot_json)
    return dict(transfer_id=row.transfer_id, title=snapshot["title"],
                sender_email=row.sender_email, recipient_email=row.recipient_email,
                status=row.status, expires_at=row.expires_at,
                file_text_count=len(snapshot["files"]),
                conversation_count=len(snapshot["conversations"]),
                destination_workspace_id=row.destination_workspace_id)


def prepare(db, workspace_id, recipient_email, include_conversations, include_file_text, *, organization_id, user):
    project = service.get_project(db, workspace_id, organization_id=organization_id, user=user)
    if project.owner_user_id != user.user_id:
        raise service.NovaWorkspaceError("Only the project owner can offer a transfer", status_code=403)
    recipient = recipient_email.strip().lower()
    if recipient == user.email.strip().lower():
        raise service.NovaWorkspaceError("Choose another account's email")
    snapshot = dict(title=project.title, description=project.description, files=[], conversations=[])
    if include_file_text:
        files = db.query(NovaWorkspaceFile).filter_by(workspace_id=workspace_id,
            organization_id=organization_id, owner_user_id=user.user_id).order_by(NovaWorkspaceFile.file_id).all()
        snapshot["files"] = [dict(filename=f.filename, content_type=f.content_type, excerpt=f.excerpt) for f in files]
    if include_conversations:
        conversations = db.query(NovaWorkspaceConversation).filter_by(workspace_id=workspace_id,
            organization_id=organization_id, owner_user_id=user.user_id).order_by(NovaWorkspaceConversation.conversation_id).all()
        for convo in conversations:
            messages = db.query(NovaWorkspaceMessage).filter_by(conversation_id=convo.conversation_id,
                organization_id=organization_id).order_by(NovaWorkspaceMessage.created_at, NovaWorkspaceMessage.message_id).all()
            snapshot["conversations"].append(dict(title=convo.title,
                messages=[dict(role=m.role, content=m.content) for m in messages]))
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    if len(encoded.encode()) > 2_000_000:
        raise service.NovaWorkspaceError("Project transfer is too large. Exclude history or file text.", status_code=413)
    key = hashlib.sha256(json.dumps([organization_id, user.user_id, workspace_id, recipient, encoded]).encode()).hexdigest()
    existing = db.query(NovaWorkspaceTransfer).filter_by(dedup_key=key).first()
    if existing:
        if existing.status == "accepted" or (existing.status == "pending" and existing.expires_at.replace(tzinfo=timezone.utc) > now()):
            return summary(existing)
        existing.dedup_key = hashlib.sha256((existing.transfer_id + key).encode()).hexdigest()
        existing.status = "expired" if existing.status == "pending" else existing.status
        db.flush()
    row = NovaWorkspaceTransfer(transfer_id=service._new_id("NWT-"), dedup_key=key,
        source_organization_id=organization_id, source_user_id=user.user_id,
        sender_email=user.email, recipient_email=recipient, snapshot_json=encoded,
        status="pending", expires_at=now() + timedelta(days=7))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.query(NovaWorkspaceTransfer).filter_by(dedup_key=key).one()
    return summary(row)


def incoming(db, *, user):
    rows = db.query(NovaWorkspaceTransfer).filter_by(recipient_email=user.email.strip().lower(), status="pending").order_by(NovaWorkspaceTransfer.created_at.desc()).all()
    return [summary(row) for row in rows if row.expires_at.replace(tzinfo=timezone.utc) > now()]


def accept(db, transfer_id, *, organization_id, user):
    row = db.query(NovaWorkspaceTransfer).filter_by(transfer_id=transfer_id,
        recipient_email=user.email.strip().lower()).with_for_update().first()
    if row is None:
        raise service.NovaWorkspaceError("Transfer not found", status_code=404)
    if row.status == "accepted":
        if row.accepted_user_id != user.user_id or row.accepted_organization_id != organization_id:
            raise service.NovaWorkspaceError("Transfer already accepted in another workspace", status_code=409)
        return summary(row)
    if row.status != "pending":
        raise service.NovaWorkspaceError("Transfer is no longer available", status_code=410)
    if row.expires_at.replace(tzinfo=timezone.utc) <= now():
        raise service.NovaWorkspaceError("Transfer expired. Ask the sender to prepare a new transfer.", status_code=410)
    snapshot = json.loads(row.snapshot_json)
    project_id = service._new_id("NW-")
    db.add(NovaWorkspaceProject(workspace_id=project_id, organization_id=organization_id,
        owner_user_id=user.user_id, title=snapshot["title"], description=snapshot["description"], status="active", archived=False))
    for f in snapshot["files"]:
        db.add(NovaWorkspaceFile(file_id=service._new_id("NWF-"), workspace_id=project_id,
            organization_id=organization_id, owner_user_id=user.user_id, **f))
    for convo in snapshot["conversations"]:
        convo_id = service._new_id("NWC-")
        db.add(NovaWorkspaceConversation(conversation_id=convo_id, workspace_id=project_id,
            organization_id=organization_id, owner_user_id=user.user_id, title=convo["title"], source="transfer"))
        for m in convo["messages"]:
            db.add(NovaWorkspaceMessage(message_id=service._new_id("NWM-"), conversation_id=convo_id,
                organization_id=organization_id, **m))
    service._record_activity(db, organization_id=organization_id, owner_user_id=user.user_id,
        kind="project_transferred", title="Accepted project " + snapshot["title"], workspace_id=project_id,
        ref_type="transfer", ref_id=row.transfer_id)
    row.status = "accepted"
    row.accepted_user_id = user.user_id
    row.accepted_organization_id = organization_id
    row.destination_workspace_id = project_id
    db.commit()
    return summary(row)


def cancel(db, transfer_id, *, organization_id, user):
    row = db.query(NovaWorkspaceTransfer).filter_by(transfer_id=transfer_id,
        source_organization_id=organization_id, source_user_id=user.user_id).with_for_update().first()
    if row is None:
        raise service.NovaWorkspaceError("Transfer not found", status_code=404)
    if row.status == "accepted":
        raise service.NovaWorkspaceError("The recipient already accepted this copy", status_code=409)
    row.status = "canceled"
    db.commit()
    return summary(row)
