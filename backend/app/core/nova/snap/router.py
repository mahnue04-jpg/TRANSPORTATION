"""Authenticated Snap HTTP API. Status is public and contains no secrets."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.db.models import User as PlatformUser
from app.db.session import get_db

from . import policy, service

router = APIRouter(prefix="/api/nova/snap", tags=["nova-snap"])
_guard = [Depends(require_nova_access)]


def _quiet(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _peer(db: Session, user: UserContext, email: str) -> str:
    org = service.organization_id(user)
    target = (
        db.query(PlatformUser)
        .filter(
            PlatformUser.email == (email or "").strip().lower(),
            PlatformUser.organization_id == org,
            PlatformUser.is_active.is_(True),
        )
        .one_or_none()
    )
    if target is None or target.id == user.user_id:
        raise HTTPException(404, "No active Nova account with that email was found in your organization.")
    return target.id


class ContactIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ContactRespond(BaseModel):
    accept: bool


class BlockIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)


class DirectIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)


class GroupIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    user_ids: list[str] = Field(min_length=1, max_length=7)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    client_message_id: str = Field(min_length=8, max_length=80)


class ReadIn(BaseModel):
    message_id: str = Field(min_length=1, max_length=36)


class ReportIn(BaseModel):
    target_user_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=3, max_length=500)
    conversation_id: str | None = None
    message_id: str | None = None


class CallIn(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=36)
    media: str = Field(pattern="^(audio|video)$")


class SignalIn(BaseModel):
    kind: str = Field(min_length=3, max_length=16)
    payload: str = Field(max_length=20000)
    client_signal_id: str = Field(min_length=8, max_length=80)


class ShareIn(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=36)
    consent: bool


@router.get("/status")
def status(response: Response):
    _quiet(response)
    return policy.public_status()


@router.get("/me", dependencies=_guard)
def me(response: Response, user: UserContext = Depends(get_current_user_context)):
    _quiet(response)
    return service.profile(user)


@router.get("/calls/config", dependencies=_guard)
def call_config(response: Response, user: UserContext = Depends(get_current_user_context)):
    _quiet(response)
    return service.ice_for_member(user)


@router.get("/contacts", dependencies=_guard)
def contacts(response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _quiet(response)
    return service.list_contacts(db, user)


@router.post("/contacts", dependencies=_guard)
def create_contact(
    payload: ContactIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.request_contact(db, user, _peer(db, user, payload.email))


@router.post("/contacts/{contact_id}/respond", dependencies=_guard)
def respond_contact(
    contact_id: str,
    payload: ContactRespond,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.respond_contact(db, user, contact_id, payload.accept)


@router.post("/blocks", dependencies=_guard)
def block(
    payload: BlockIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.block_user(db, user, payload.user_id)


@router.delete("/blocks/{other_user_id}", dependencies=_guard)
def unblock(
    other_user_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.unblock_user(db, user, other_user_id)


@router.get("/conversations", dependencies=_guard)
def conversations(response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _quiet(response)
    return service.list_conversations(db, user)


@router.post("/conversations/direct", dependencies=_guard)
def direct(
    payload: DirectIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.create_direct(db, user, payload.user_id)


@router.post("/conversations/group", dependencies=_guard)
def group(
    payload: GroupIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.create_group(db, user, payload.title, payload.user_ids)


@router.post("/conversations/{conversation_id}/leave", dependencies=_guard)
def leave(
    conversation_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.leave_conversation(db, user, conversation_id)


@router.get("/conversations/{conversation_id}/messages", dependencies=_guard)
def messages(
    conversation_id: str,
    response: Response,
    after: int = 0,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.list_messages(db, user, conversation_id, after)


@router.post("/conversations/{conversation_id}/messages", dependencies=_guard)
def send_message(
    conversation_id: str,
    payload: MessageIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.post_message(db, user, conversation_id, payload.body, payload.client_message_id)


@router.post("/conversations/{conversation_id}/read", dependencies=_guard)
def read(
    conversation_id: str,
    payload: ReadIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.mark_read(db, user, conversation_id, payload.message_id)


@router.delete("/messages/{message_id}", dependencies=_guard)
def remove_message(
    message_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.delete_message(db, user, message_id)


@router.post("/reports", dependencies=_guard)
def report(
    payload: ReportIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.report_message(
        db,
        user,
        target_user_id=payload.target_user_id,
        reason=payload.reason,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
    )


@router.get("/reports", dependencies=_guard)
def reports(response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _quiet(response)
    return service.list_reports(db, user)


@router.post("/calls", dependencies=_guard)
def call(
    payload: CallIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.start_call(db, user, payload.conversation_id, payload.media)


@router.get("/calls/incoming", dependencies=_guard)
def incoming(response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _quiet(response)
    return service.list_incoming(db, user)


@router.get("/calls/{call_id}", dependencies=_guard)
def call_state(
    call_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.get_call(db, user, call_id)


@router.post("/calls/{call_id}/accept", dependencies=_guard)
def accept(
    call_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.accept_call(db, user, call_id)


@router.post("/calls/{call_id}/decline", dependencies=_guard)
def decline(
    call_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.decline_call(db, user, call_id)


@router.post("/calls/{call_id}/end", dependencies=_guard)
def end(
    call_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.end_call(db, user, call_id)


@router.post("/calls/{call_id}/reconnect", dependencies=_guard)
def reconnect(
    call_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.reconnect_call(db, user, call_id)


@router.post("/calls/{call_id}/signals", dependencies=_guard)
def signal(
    call_id: str,
    payload: SignalIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.post_signal(
        db,
        user,
        call_id,
        kind=payload.kind,
        payload=payload.payload,
        client_signal_id=payload.client_signal_id,
    )


@router.get("/calls/{call_id}/signals", dependencies=_guard)
def signals(
    call_id: str,
    response: Response,
    after: int = 0,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.list_signals(db, user, call_id, after)


@router.get("/captures", dependencies=_guard)
def captures(response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _quiet(response)
    return service.list_captures(db, user)


@router.post("/captures", dependencies=_guard)
async def create_capture(
    response: Response,
    upload: UploadFile = File(...),
    duration_ms: int = Form(0),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    data = await upload.read(policy.MAX_CLIP_BYTES + 1)
    return service.save_capture(
        db,
        user,
        data=data,
        declared_type=upload.content_type or "",
        duration_ms=duration_ms,
    )


@router.post("/captures/{capture_id}/share", dependencies=_guard)
def share(
    capture_id: str,
    payload: ShareIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.share_capture(db, user, capture_id, payload.conversation_id, payload.consent)


@router.delete("/captures/{capture_id}", dependencies=_guard)
def remove_capture(
    capture_id: str,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _quiet(response)
    return service.delete_capture(db, user, capture_id)


@router.get("/captures/{capture_id}/media", dependencies=_guard)
def capture_media(
    capture_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    row, path = service.open_capture(db, user, capture_id)
    return FileResponse(
        path,
        media_type=row.content_type,
        filename=f"snap-{row.capture_id}",
        content_disposition_type="attachment",
        headers={"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/privacy/remove-my-content", dependencies=_guard)
def remove_mine(response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _quiet(response)
    return service.remove_my_content(db, user)
