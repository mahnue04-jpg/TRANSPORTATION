"""Scoped meeting grants. Provider secrets and invitation secrets never enter logs."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.db.session import get_db
from .models import SynapseMeeting

router = APIRouter(prefix="/api/nova/synapse", tags=["nova-synapse"])
owner_access = [Depends(require_nova_access)]


def provider_config():
    url = os.getenv("LIVEKIT_URL", "").strip().rstrip("/")
    key = os.getenv("LIVEKIT_API_KEY", "").strip()
    secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    parsed = urlsplit(url)
    # A trusted administrator configures one secure media origin, never a user URL.
    if (parsed.scheme != "wss" or not parsed.hostname or parsed.username or parsed.password
            or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", parsed.netloc)
            or parsed.path or parsed.query or parsed.fragment or not key or len(secret) < 32):
        return None
    return url, key, secret


def provider_origin():
    config = provider_config()
    return config[0] if config else ""


def _jwt(identity, room, *, name="", admin=False, service=False):
    config = provider_config()
    if not config:
        raise HTTPException(503, "Video service is not connected yet. Meeting calls are unavailable.")
    def enc(data):
        return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).rstrip(b"=")
    now = int(time.time())
    grant = {"room": room, "roomAdmin": admin}
    if service:
        grant["roomCreate"] = True
    else:
        grant.update(roomJoin=True, canPublish=True, canSubscribe=True, canPublishData=True)
    body = {"iss": config[1], "sub": identity, "name": name, "nbf": now - 5,
            "exp": now + 300, "video": grant}
    raw = enc({"alg": "HS256", "typ": "JWT"}) + b"." + enc(body)
    return (raw + b"." + base64.urlsafe_b64encode(hmac.new(config[2].encode(), raw, hashlib.sha256).digest()).rstrip(b"=")).decode()


def _scope(user):
    try:
        return NovaCoreService.resolve_organization_scope(user, None)
    except ValueError as exc:
        raise HTTPException(403, "Organization access required.") from exc


def _meeting(db, mid):
    row = db.get(SynapseMeeting, mid)
    if not row:
        raise HTTPException(404, "Meeting not found.")
    expiry = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if row.ended or expiry <= datetime.now(timezone.utc):
        raise HTTPException(410, "This meeting has ended or its invitation expired.")
    return row


def _owned(db, mid, user):
    row = _meeting(db, mid)
    if row.owner_user_id != user.user_id or row.organization_id != _scope(user):
        raise HTTPException(404, "Meeting not found.")
    return row


def _out(row):
    return {"meeting_id": row.meeting_id, "title": row.title, "locked": row.locked,
            "expires_at": row.expires_at.isoformat(), "ended": row.ended}


class CreateMeeting(BaseModel):
    title: str = Field(min_length=1, max_length=180)


class GuestJoin(BaseModel):
    invite: str = Field(min_length=32, max_length=100)
    name: str = Field(min_length=1, max_length=80)


class LockMeeting(BaseModel):
    locked: bool


@router.get("/status")
def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"configured": bool(provider_config()), "brand": "AMICOR Synapse"}


@router.get("/meetings", dependencies=owner_access)
def meetings(user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    rows = db.query(SynapseMeeting).filter_by(owner_user_id=user.user_id, organization_id=_scope(user), ended=False).order_by(SynapseMeeting.created_at.desc()).limit(50).all()
    return [_out(r) for r in rows if (r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at) > datetime.now(timezone.utc)]


@router.post("/meetings", dependencies=owner_access)
def create(payload: CreateMeeting, response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    if not provider_config():
        raise HTTPException(503, "Video service is not connected yet. Meeting calls are unavailable.")
    org = _scope(user)
    now = datetime.now(timezone.utc)
    if db.query(SynapseMeeting).filter_by(owner_user_id=user.user_id, organization_id=org, ended=False).filter(SynapseMeeting.expires_at > now).count() >= 20:
        raise HTTPException(429, "End an existing meeting before creating another.")
    invite = secrets.token_urlsafe(32)
    row = SynapseMeeting(meeting_id=str(uuid4()), organization_id=org, owner_user_id=user.user_id,
        title=payload.title.strip() or "AMICOR meeting", invite_hash=hashlib.sha256(invite.encode()).hexdigest(),
        locked=False, ended=False, created_at=now, expires_at=now + timedelta(hours=8))
    db.add(row)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return dict(_out(row), invite_path=f"/nova/synapse#room={row.meeting_id}&invite={invite}")


@router.post("/meetings/{mid}/host", dependencies=owner_access)
def host(mid: str, response: Response, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    row = _owned(db, mid, user)
    response.headers["Cache-Control"] = "no-store"
    token = _jwt("host-" + row.owner_user_id, row.meeting_id, name="Host", admin=True)
    return dict(_out(row), server_url=provider_config()[0], participant_token=token, host=True)


@router.post("/meetings/{mid}/join")
def join(mid: str, payload: GuestJoin, response: Response, db: Session = Depends(get_db)):
    row = _meeting(db, mid)
    if not hmac.compare_digest(hashlib.sha256(payload.invite.encode()).hexdigest(), row.invite_hash):
        raise HTTPException(404, "Meeting not found.")
    if row.locked:
        raise HTTPException(403, "The host has locked new invitations.")
    response.headers["Cache-Control"] = "no-store"
    token = _jwt("guest-" + str(uuid4()), row.meeting_id, name=payload.name.strip() or "Guest")
    return dict(_out(row), server_url=provider_config()[0], participant_token=token, host=False)


@router.patch("/meetings/{mid}/lock", dependencies=owner_access)
def lock(mid: str, payload: LockMeeting, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    row = _owned(db, mid, user)
    row.locked = payload.locked
    db.commit()
    return _out(row)


@router.post("/meetings/{mid}/end", dependencies=owner_access)
def end(mid: str, user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    row = _owned(db, mid, user)
    config = provider_config()
    grant = _jwt("service", row.meeting_id, admin=True, service=True)
    try:
        result = requests.post(config[0].replace("wss://", "https://", 1) + "/twirp/livekit.RoomService/DeleteRoom",
            json={"room": row.meeting_id}, headers={"Authorization": "Bearer " + grant}, timeout=10)
        # Deleting a room that was never joined is also an ended meeting.
        missing_room = False
        if result.status_code == 404:
            try:
                missing_room = result.json().get("code") == "not_found"
            except (ValueError, AttributeError):
                pass
        if result.status_code != 200 and not missing_room:
            raise HTTPException(503, "Could not end the video room. Please retry.")
    except requests.RequestException as exc:
        raise HTTPException(503, "Could not reach the video service. Please retry ending the meeting.") from exc
    row.ended = True
    row.locked = True
    db.commit()
    return {"ended": True}
