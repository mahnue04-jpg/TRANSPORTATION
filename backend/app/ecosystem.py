"""Ecosystem integration layer.

Adds email, calendar, search diagnostics, semantic memory, and workflow endpoints
without replacing existing runtime foundations.
"""
from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import secrets
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_chat_history, get_memory_summary, save_memory_summary # type: ignore
from app.db.models import (
    CalendarEventRecord,
    EmailDraftRecord,
    IntegrationAccount,
    MemoryRecord,
    MemoryVectorRecord,
    WorkflowRunRecord,
    WorkflowTemplate,
)
from app.db.session import SessionLocal
from app.helpers import ensure_user_id, json_dumps, json_loads_or, now
from app.router import route_message # type: ignore
from app.web_search import get_search_diagnostics, search_web # type: ignore

router = APIRouter(prefix="/api", tags=["ecosystem"])


# ── Helpers with underscore prefix for backward compatibility within this module ──
def _now() -> datetime:
    """Backward compatibility wrapper. Use now() from helpers."""
    return now()


def _ensure_user_id(user_id: str) -> str:
    """Backward compatibility wrapper. Use ensure_user_id() from helpers."""
    return ensure_user_id(user_id)


def _json_loads_or(value: str | None, fallback: Any) -> Any:
    """Backward compatibility wrapper. Use json_loads_or() from helpers."""
    return json_loads_or(value, fallback)


def _json_dumps(value: Any) -> str:
    """Backward compatibility wrapper. Use json_dumps() from helpers."""
    return json_dumps(value)


def _find_integration(db, user_id: str, service: str, provider: str) -> IntegrationAccount | None: # type: ignore
    return (
        db.query(IntegrationAccount) # type: ignore
        .filter(
            IntegrationAccount.user_id == user_id,
            IntegrationAccount.service == service,
            IntegrationAccount.provider == provider,
        )
        .first()
    )


def _upsert_integration(
    db, # type: ignore
    *,
    user_id: str,
    service: str,
    provider: str,
    account_email: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
    token_expires_at: datetime | None = None,
    scopes: str | None = None,
    meta: dict[str, Any] | None = None,
) -> IntegrationAccount:
    record = _find_integration(db, user_id, service, provider) # type: ignore
    if not record:
        record = IntegrationAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            service=service,
            provider=provider,
        )
        db.add(record) # type: ignore

    if account_email is not None:
        record.account_email = account_email
    if access_token is not None:
        record.access_token = access_token
    if refresh_token is not None:
        record.refresh_token = refresh_token
    if token_expires_at is not None:
        record.token_expires_at = token_expires_at
    if scopes is not None:
        record.scopes = scopes
    if meta is not None:
        record.meta_json = _json_dumps(meta)

    record.updated_at = _now()
    db.commit() # type: ignore
    db.refresh(record) # type: ignore
    return record


class EmailConnectRequest(BaseModel):
    user_id: str
    provider: str = Field(pattern="^(gmail|outlook|smtp)$")
    action: str = Field(default="start", pattern="^(start|complete|status|configure_smtp)$")
    code: str | None = None
    redirect_uri: str | None = None
    account_email: str | None = None
    state: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None


class EmailDraftRequest(BaseModel):
    user_id: str
    provider: str = "smtp"
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    attachments: list[dict[str, Any]] = Field(default_factory=list) # type: ignore


class EmailSendRequest(BaseModel):
    user_id: str
    provider: str = "smtp"
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    attachments: list[dict[str, Any]] = Field(default_factory=list) # type: ignore
    save_as_draft: bool = False


class CalendarConnectRequest(BaseModel):
    user_id: str
    provider: str = Field(pattern="^(google|outlook)$")
    action: str = Field(default="start", pattern="^(start|complete|status)$")
    code: str | None = None
    redirect_uri: str | None = None
    state: str | None = None


class CalendarEventRequest(BaseModel):
    user_id: str
    provider: str = Field(default="local", pattern="^(local|google|outlook)$")
    title: str
    description: str | None = None
    start_time: str
    end_time: str
    timezone: str = "UTC"
    attendees: list[str] = Field(default_factory=list)
    reminder_minutes: int | None = 15


class ScheduleAssistRequest(BaseModel):
    user_id: str
    title: str
    duration_minutes: int = 30
    window_start: str
    window_end: str
    provider: str = Field(default="local", pattern="^(local|google|outlook)$")


class MemoryIndexRequest(BaseModel):
    user_id: str
    text: str
    source: str = "conversation"
    priority: float = 0.5


class MemoryCompressRequest(BaseModel):
    user_id: str


class WorkflowCreateRequest(BaseModel):
    user_id: str
    name: str
    description: str | None = None
    reusable_prompt: str | None = None
    action_chain: list[dict[str, Any]] = Field(default_factory=list) # type: ignore


class WorkflowExecuteRequest(BaseModel):
    user_id: str
    input_text: str = ""


# ── OAuth helpers ─────────────────────────────────────────────────────────────

def _oauth_redirect(provider: str, service: str, redirect_uri: str | None) -> str:
    env_key = f"{provider.upper()}_{service.upper()}_REDIRECT_URI"
    return redirect_uri or os.getenv(env_key, "http://127.0.0.1:8011/app")


def _google_scopes(service: str) -> str:
    if service == "email":
        return "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
    return "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"


def _outlook_scopes(service: str) -> str:
    if service == "email":
        return "Mail.Read Mail.Send offline_access User.Read"
    return "Calendars.Read Calendars.ReadWrite offline_access User.Read"


def _oauth_start(provider: str, service: str, redirect_uri: str, state: str) -> dict[str, Any]:
    if provider == "gmail" or provider == "google":
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        if not client_id:
            raise HTTPException(status_code=400, detail="GOOGLE_CLIENT_ID is not configured")
        scopes = _google_scopes(service)
        url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={requests.utils.quote(client_id)}" # type: ignore
            f"&redirect_uri={requests.utils.quote(redirect_uri)}" # type: ignore
            "&response_type=code"
            f"&scope={requests.utils.quote(scopes)}" # type: ignore
            "&access_type=offline&prompt=consent"
            f"&state={requests.utils.quote(state)}" # type: ignore
        )
        return {"authorization_url": url, "scopes": scopes}

    client_id = os.getenv("OUTLOOK_CLIENT_ID", "")
    tenant = os.getenv("OUTLOOK_TENANT_ID", "common")
    if not client_id:
        raise HTTPException(status_code=400, detail="OUTLOOK_CLIENT_ID is not configured")
    scopes = _outlook_scopes(service)
    url = (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        f"?client_id={requests.utils.quote(client_id)}" # type: ignore
        f"&redirect_uri={requests.utils.quote(redirect_uri)}" # type: ignore
        "&response_type=code"
        f"&scope={requests.utils.quote(scopes)}" # type: ignore
        f"&state={requests.utils.quote(state)}" # type: ignore
    )
    return {"authorization_url": url, "scopes": scopes}


def _oauth_exchange(provider: str, service: str, code: str, redirect_uri: str) -> dict[str, Any]:
    if provider in ("gmail", "google"):
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="Google OAuth client is not configured")
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        token_res = requests.post("https://oauth2.googleapis.com/token", data=payload, timeout=15)
        if token_res.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Google token exchange failed: {token_res.text[:200]}")
        tk = token_res.json()
        access_token = tk.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Google token exchange returned no access token")

        email = None
        try:
            profile = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if profile.ok:
                email = profile.json().get("email")
        except Exception:
            email = None

        return {
            "access_token": access_token,
            "refresh_token": tk.get("refresh_token"),
            "expires_in": int(tk.get("expires_in", 3600)),
            "scopes": tk.get("scope", _google_scopes(service)),
            "account_email": email,
        }

    client_id = os.getenv("OUTLOOK_CLIENT_ID", "")
    client_secret = os.getenv("OUTLOOK_CLIENT_SECRET", "")
    tenant = os.getenv("OUTLOOK_TENANT_ID", "common")
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Outlook OAuth client is not configured")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "scope": _outlook_scopes(service),
    }
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    token_res = requests.post(token_url, data=payload, timeout=15)
    if token_res.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Outlook token exchange failed: {token_res.text[:200]}")

    tk = token_res.json()
    access_token = tk.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Outlook token exchange returned no access token")

    email = None
    try:
        me = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if me.ok:
            body = me.json()
            email = body.get("mail") or body.get("userPrincipalName")
    except Exception:
        email = None

    return {
        "access_token": access_token,
        "refresh_token": tk.get("refresh_token"),
        "expires_in": int(tk.get("expires_in", 3600)),
        "scopes": tk.get("scope", _outlook_scopes(service)),
        "account_email": email,
    }


def _refresh_outlook_if_needed(account: IntegrationAccount) -> str:
    if not account.access_token:
        raise HTTPException(status_code=400, detail="Outlook integration has no access token")
    if not account.token_expires_at or account.token_expires_at > _now() + timedelta(seconds=30):
        return account.access_token
    if not account.refresh_token:
        raise HTTPException(status_code=401, detail="Outlook token expired and no refresh token is available")

    client_id = os.getenv("OUTLOOK_CLIENT_ID", "")
    client_secret = os.getenv("OUTLOOK_CLIENT_SECRET", "")
    tenant = os.getenv("OUTLOOK_TENANT_ID", "common")
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Outlook OAuth refresh is not configured")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": account.refresh_token,
        "scope": account.scopes or _outlook_scopes(account.service),
    }
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    token_res = requests.post(token_url, data=payload, timeout=15)
    if token_res.status_code >= 400:
        raise HTTPException(status_code=401, detail="Outlook token refresh failed")
    tk = token_res.json()
    account.access_token = tk.get("access_token", account.access_token)
    if tk.get("refresh_token"):
        account.refresh_token = tk["refresh_token"]
    account.token_expires_at = _now() + timedelta(seconds=int(tk.get("expires_in", 3600)))
    account.updated_at = _now()
    return account.access_token # type: ignore


def _smtp_send(meta: dict[str, Any], account_email: str | None, send_req: EmailSendRequest) -> dict[str, Any]:
    host = meta.get("smtp_host") or os.getenv("SMTP_HOST")
    port = int(meta.get("smtp_port") or os.getenv("SMTP_PORT", "587"))
    username = meta.get("smtp_username") or os.getenv("SMTP_USERNAME")
    password = meta.get("smtp_password") or os.getenv("SMTP_PASSWORD")
    from_email = account_email or username or os.getenv("SMTP_FROM")

    if not host or not from_email:
        raise HTTPException(status_code=400, detail="SMTP is not configured")

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = ", ".join(send_req.to)
    if send_req.cc:
        msg["Cc"] = ", ".join(send_req.cc)
    msg["Subject"] = send_req.subject
    msg.set_content(send_req.body)

    for attachment in send_req.attachments:
        try:
            raw = base64.b64decode(attachment.get("content_base64", ""))
            maintype, subtype = (attachment.get("content_type", "application/octet-stream")).split("/", 1)
            msg.add_attachment(
                raw,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.get("filename", "attachment.bin"),
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid attachment payload: {exc}")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.ehlo()
        try:
            server.starttls(context=context)
            server.ehlo()
        except Exception:
            pass
        if username and password:
            server.login(username, password)
        recipients = send_req.to + send_req.cc + send_req.bcc
        server.send_message(msg, to_addrs=recipients)

    return {"provider": "smtp", "status": "sent"}


def _gmail_send(access_token: str, send_req: EmailSendRequest, from_email: str | None) -> dict[str, Any]:
    msg = EmailMessage()
    msg["From"] = from_email or "me"
    msg["To"] = ", ".join(send_req.to)
    if send_req.cc:
        msg["Cc"] = ", ".join(send_req.cc)
    msg["Subject"] = send_req.subject
    msg.set_content(send_req.body)
    for attachment in send_req.attachments:
        raw = base64.b64decode(attachment.get("content_base64", ""))
        maintype, subtype = (attachment.get("content_type", "application/octet-stream")).split("/", 1)
        msg.add_attachment(raw, maintype=maintype, subtype=subtype, filename=attachment.get("filename", "attachment.bin"))

    raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    res = requests.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"raw": raw_b64},
        timeout=15,
    )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Gmail send failed: {res.text[:240]}")
    return {"provider": "gmail", "status": "sent", "id": res.json().get("id")}


def _outlook_send(access_token: str, send_req: EmailSendRequest) -> dict[str, Any]:
    payload = { # type: ignore
        "message": {
            "subject": send_req.subject,
            "body": {"contentType": "Text", "content": send_req.body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in send_req.to],
            "ccRecipients": [{"emailAddress": {"address": addr}} for addr in send_req.cc],
            "bccRecipients": [{"emailAddress": {"address": addr}} for addr in send_req.bcc],
        },
        "saveToSentItems": True,
    }
    res = requests.post(
        "https://graph.microsoft.com/v1.0/me/sendMail",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=payload, # type: ignore
        timeout=15,
    )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Outlook send failed: {res.text[:240]}")
    return {"provider": "outlook", "status": "sent"}


def _gmail_inbox(access_token: str, limit: int) -> list[dict[str, Any]]:
    list_res = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"maxResults": limit, "labelIds": "INBOX"},
        timeout=15,
    )
    if list_res.status_code >= 400:
        raise HTTPException(status_code=502, detail="Gmail inbox read failed")

    messages = []
    for item in list_res.json().get("messages", [])[:limit]:
        msg_id = item.get("id")
        if not msg_id:
            continue
        detail = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
            timeout=15,
        )
        if not detail.ok:
            continue
        headers = {h.get("name", "").lower(): h.get("value", "") for h in detail.json().get("payload", {}).get("headers", [])}
        messages.append( # type: ignore
            {
                "id": msg_id,
                "subject": headers.get("subject", "(no subject)"),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "snippet": detail.json().get("snippet", ""),
            }
        )
    return messages # type: ignore


def _outlook_inbox(access_token: str, limit: int) -> list[dict[str, Any]]:
    res = requests.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"$top": limit, "$select": "id,subject,from,receivedDateTime,bodyPreview"},
        timeout=15,
    )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail="Outlook inbox read failed")
    items = []
    for row in res.json().get("value", [])[:limit]:
        items.append( # type: ignore
            {
                "id": row.get("id"),
                "subject": row.get("subject") or "(no subject)",
                "from": ((row.get("from") or {}).get("emailAddress") or {}).get("address", ""), # type: ignore
                "date": row.get("receivedDateTime", ""),
                "snippet": row.get("bodyPreview", ""),
            }
        )
    return items # type: ignore


@router.post("/email/connect")
def email_connect(req: EmailConnectRequest): # type: ignore
    user_id = _ensure_user_id(req.user_id)
    provider = req.provider.lower()
    with SessionLocal() as db:
        if provider == "smtp" and req.action == "configure_smtp":
            meta = { # type: ignore
                "smtp_host": req.smtp_host,
                "smtp_port": req.smtp_port or 587,
                "smtp_username": req.smtp_username,
                "smtp_password": req.smtp_password,
            }
            rec = _upsert_integration(
                db,
                user_id=user_id,
                service="email",
                provider="smtp",
                account_email=req.account_email,
                meta=meta, # type: ignore
            )
            return {"status": "configured", "provider": "smtp", "account_email": rec.account_email} # type: ignore

        if req.action == "status":
            rec = _find_integration(db, user_id, "email", provider)
            return {
                "status": "ok",
                "connected": bool(rec and (rec.access_token or provider == "smtp")),
                "provider": provider,
                "account_email": rec.account_email if rec else None,
            } # type: ignore

        redirect_uri = _oauth_redirect("google" if provider == "gmail" else "outlook", "email", req.redirect_uri)

        if req.action == "start":
            state = req.state or secrets.token_urlsafe(24)
            start = _oauth_start("google" if provider == "gmail" else "outlook", "email", redirect_uri, state)
            _upsert_integration(
                db,
                user_id=user_id,
                service="email",
                provider=provider,
                meta={"oauth_state": state, "redirect_uri": redirect_uri},
            )
            return {
                "status": "authorize",
                "provider": provider,
                "authorization_url": start["authorization_url"],
                "state": state,
                "scopes": start["scopes"],
            } # type: ignore

        if req.action == "complete":
            if not req.code:
                raise HTTPException(status_code=422, detail="code is required for complete action")
            token = _oauth_exchange("google" if provider == "gmail" else "outlook", "email", req.code, redirect_uri)
            expires_at = _now() + timedelta(seconds=int(token.get("expires_in", 3600)))
            rec = _upsert_integration(
                db,
                user_id=user_id,
                service="email",
                provider=provider,
                access_token=token["access_token"],
                refresh_token=token.get("refresh_token"),
                token_expires_at=expires_at,
                scopes=token.get("scopes"),
                account_email=token.get("account_email") or req.account_email,
                meta={"redirect_uri": redirect_uri},
            )
            return {
                "status": "connected",
                "provider": provider,
                "account_email": rec.account_email,
                "token_expires_at": rec.token_expires_at.isoformat() if rec.token_expires_at else None,
            } # type: ignore

    raise HTTPException(status_code=400, detail="Unsupported action")


@router.get("/email/drafts")
def get_email_drafts(user_id: str): # type: ignore
    uid = _ensure_user_id(user_id)
    with SessionLocal() as db:
        rows = (
            db.query(EmailDraftRecord)
            .filter(EmailDraftRecord.user_id == uid)
            .order_by(EmailDraftRecord.updated_at.desc())
            .limit(100)
            .all()
        )
        payload = []
        for row in rows:
            payload.append( # type: ignore
                {
                    "id": row.id,
                    "provider": row.provider,
                    "to": _json_loads_or(row.to_recipients, []),
                    "cc": _json_loads_or(row.cc_recipients, []),
                    "bcc": _json_loads_or(row.bcc_recipients, []),
                    "subject": row.subject,
                    "body": row.body,
                    "attachments": _json_loads_or(row.attachments_json, []),
                    "status": row.status,
                    "updated_at": row.updated_at.isoformat(),
                }
            )
    return {"status": "ok", "drafts": payload} # type: ignore


@router.post("/email/drafts")
def save_email_draft(req: EmailDraftRequest):
    uid = _ensure_user_id(req.user_id)
    with SessionLocal() as db:
        row = EmailDraftRecord(
            id=str(uuid.uuid4()),
            user_id=uid,
            provider=req.provider,
            to_recipients=_json_dumps(req.to),
            cc_recipients=_json_dumps(req.cc),
            bcc_recipients=_json_dumps(req.bcc),
            subject=req.subject,
            body=req.body,
            attachments_json=_json_dumps(req.attachments),
            status="draft",
            updated_at=_now(),
        )
        db.add(row)
        db.commit()
        return {"status": "saved", "draft_id": row.id}


@router.post("/email/send")
def send_email(req: EmailSendRequest): # type: ignore
    uid = _ensure_user_id(req.user_id)
    if not req.to:
        raise HTTPException(status_code=422, detail="At least one recipient is required")

    with SessionLocal() as db:
        provider = req.provider.lower()
        integration = _find_integration(db, uid, "email", provider)
        result = None
        fallback_used = False

        if req.save_as_draft:
            draft = EmailDraftRecord(
                id=str(uuid.uuid4()),
                user_id=uid,
                provider=provider,
                to_recipients=_json_dumps(req.to),
                cc_recipients=_json_dumps(req.cc),
                bcc_recipients=_json_dumps(req.bcc),
                subject=req.subject,
                body=req.body,
                attachments_json=_json_dumps(req.attachments),
                status="draft",
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(draft)
            db.commit()
            return {"status": "saved", "draft_id": draft.id}

        try:
            if provider == "gmail":
                if not integration or not integration.access_token:
                    raise HTTPException(status_code=400, detail="Gmail is not connected")
                result = _gmail_send(integration.access_token, req, integration.account_email)
            elif provider == "outlook":
                if not integration:
                    raise HTTPException(status_code=400, detail="Outlook is not connected")
                token = _refresh_outlook_if_needed(integration)
                result = _outlook_send(token, req)
                db.commit()
            else:
                smtp_meta = _json_loads_or(integration.meta_json, {}) if integration else {} # type: ignore
                result = _smtp_send(smtp_meta, integration.account_email if integration else None, req) # type: ignore
        except Exception:
            if provider != "smtp":
                smtp_rec = _find_integration(db, uid, "email", "smtp")
                smtp_meta = _json_loads_or(smtp_rec.meta_json, {}) if smtp_rec else {} # type: ignore
                if smtp_meta or os.getenv("SMTP_HOST"):
                    fallback_used = True
                    result = _smtp_send(smtp_meta, smtp_rec.account_email if smtp_rec else None, req) # type: ignore
                else:
                    raise
            else:
                raise

        draft = EmailDraftRecord(
            id=str(uuid.uuid4()),
            user_id=uid,
            provider=result.get("provider", provider),
            to_recipients=_json_dumps(req.to),
            cc_recipients=_json_dumps(req.cc),
            bcc_recipients=_json_dumps(req.bcc),
            subject=req.subject,
            body=req.body,
            attachments_json=_json_dumps(req.attachments),
            status="sent",
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(draft)
        db.commit()
        return {
            "status": "sent",
            "provider": result.get("provider", provider),
            "fallback_used": fallback_used,
            "draft_id": draft.id,
        } # type: ignore


@router.get("/email/inbox")
def read_inbox(user_id: str, provider: str = "gmail", limit: int = 10): # type: ignore
    uid = _ensure_user_id(user_id)
    limit = max(1, min(limit, 50))
    provider = provider.lower()

    with SessionLocal() as db:
        integration = _find_integration(db, uid, "email", provider)
        if not integration:
            return {"status": "ok", "provider": provider, "messages": []} # type: ignore

        if provider == "gmail":
            if not integration.access_token:
                raise HTTPException(status_code=400, detail="Gmail integration has no token")
            messages = _gmail_inbox(integration.access_token, limit)
            return {"status": "ok", "provider": "gmail", "messages": messages} # type: ignore

        if provider == "outlook":
            token = _refresh_outlook_if_needed(integration)
            db.commit()
            messages = _outlook_inbox(token, limit)
            return {"status": "ok", "provider": "outlook", "messages": messages} # type: ignore

        drafts = (
            db.query(EmailDraftRecord)
            .filter(EmailDraftRecord.user_id == uid)
            .order_by(EmailDraftRecord.updated_at.desc())
            .limit(limit)
            .all()
        )
        messages = [
            {
                "id": d.id,
                "subject": d.subject,
                "from": "local-draft",
                "date": d.updated_at.isoformat(),
                "snippet": d.body[:180],
            }
            for d in drafts
        ]
        return {"status": "ok", "provider": "local", "messages": messages} # type: ignore


@router.post("/calendar/connect")
def calendar_connect(req: CalendarConnectRequest): # type: ignore
    uid = _ensure_user_id(req.user_id)
    provider = req.provider.lower()

    with SessionLocal() as db:
        if req.action == "status":
            rec = _find_integration(db, uid, "calendar", provider)
            return {
                "status": "ok",
                "connected": bool(rec and rec.access_token),
                "provider": provider,
                "account_email": rec.account_email if rec else None,
            } # type: ignore

        redirect_uri = _oauth_redirect(provider, "calendar", req.redirect_uri)
        oauth_provider = "google" if provider == "google" else "outlook"

        if req.action == "start":
            state = req.state or secrets.token_urlsafe(24)
            start = _oauth_start(oauth_provider, "calendar", redirect_uri, state)
            _upsert_integration(
                db,
                user_id=uid,
                service="calendar",
                provider=provider,
                meta={"oauth_state": state, "redirect_uri": redirect_uri},
            )
            return {
                "status": "authorize",
                "provider": provider,
                "authorization_url": start["authorization_url"],
                "state": state,
                "scopes": start["scopes"],
            } # type: ignore

        if req.action == "complete":
            if not req.code:
                raise HTTPException(status_code=422, detail="code is required for complete action")
            token = _oauth_exchange(oauth_provider, "calendar", req.code, redirect_uri)
            rec = _upsert_integration(
                db,
                user_id=uid,
                service="calendar",
                provider=provider,
                access_token=token["access_token"],
                refresh_token=token.get("refresh_token"),
                token_expires_at=_now() + timedelta(seconds=int(token.get("expires_in", 3600))),
                scopes=token.get("scopes"),
                account_email=token.get("account_email"),
                meta={"redirect_uri": redirect_uri},
            )
            return {
                "status": "connected",
                "provider": provider,
                "account_email": rec.account_email,
                "token_expires_at": rec.token_expires_at.isoformat() if rec.token_expires_at else None,
            } # type: ignore

    raise HTTPException(status_code=400, detail="Unsupported action")


def _parse_iso_datetime(value: str) -> datetime:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid datetime format: {value}")


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _google_create_event(access_token: str, event_req: CalendarEventRequest) -> str:
    payload = { # type: ignore
        "summary": event_req.title,
        "description": event_req.description or "",
        "start": {"dateTime": event_req.start_time, "timeZone": event_req.timezone},
        "end": {"dateTime": event_req.end_time, "timeZone": event_req.timezone},
        "attendees": [{"email": e} for e in event_req.attendees],
    }
    if event_req.reminder_minutes is not None:
        payload["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": event_req.reminder_minutes}],
        }

    res = requests.post(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=payload, # type: ignore
        timeout=15,
    )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Google Calendar create failed: {res.text[:240]}")
    return res.json().get("id", "")


def _outlook_create_event(access_token: str, event_req: CalendarEventRequest) -> str:
    payload = { # type: ignore
        "subject": event_req.title,
        "body": {"contentType": "Text", "content": event_req.description or ""},
        "start": {"dateTime": event_req.start_time, "timeZone": event_req.timezone},
        "end": {"dateTime": event_req.end_time, "timeZone": event_req.timezone},
        "attendees": [
            {"emailAddress": {"address": e}, "type": "required"}
            for e in event_req.attendees
        ],
    }
    if event_req.reminder_minutes is not None:
        payload["isReminderOn"] = True
        payload["reminderMinutesBeforeStart"] = event_req.reminder_minutes

    res = requests.post(
        "https://graph.microsoft.com/v1.0/me/events",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=payload, # type: ignore
        timeout=15,
    )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Outlook Calendar create failed: {res.text[:240]}")
    return res.json().get("id", "")


@router.post("/calendar/events")
def create_calendar_event(req: CalendarEventRequest): # type: ignore
    uid = _ensure_user_id(req.user_id)
    start_dt = _parse_iso_datetime(req.start_time)
    end_dt = _parse_iso_datetime(req.end_time)
    if end_dt <= start_dt:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")

    external_id = None
    provider = req.provider.lower()

    with SessionLocal() as db:
        if provider in ("google", "outlook"):
            rec = _find_integration(db, uid, "calendar", provider)
            if not rec or not rec.access_token:
                raise HTTPException(status_code=400, detail=f"{provider} calendar is not connected")
            if provider == "google":
                external_id = _google_create_event(rec.access_token, req)
            else:
                token = _refresh_outlook_if_needed(rec)
                external_id = _outlook_create_event(token, req)
                db.commit()

        row = CalendarEventRecord(
            id=str(uuid.uuid4()),
            user_id=uid,
            provider=provider,
            external_event_id=external_id,
            title=req.title,
            description=req.description,
            start_time=start_dt,
            end_time=end_dt,
            timezone=req.timezone,
            attendees_json=_json_dumps(req.attendees),
            reminder_minutes=req.reminder_minutes,
            status="confirmed",
            created_at=_now(),
        )
        db.add(row)
        db.commit()
        return {
            "status": "created",
            "event_id": row.id,
            "provider": provider,
            "external_event_id": external_id,
        } # type: ignore


@router.get("/calendar/events")
def list_calendar_events(user_id: str, provider: str = "local", limit: int = 50): # type: ignore
    uid = _ensure_user_id(user_id)
    provider = provider.lower()
    limit = max(1, min(limit, 200))

    with SessionLocal() as db:
        rows = (
            db.query(CalendarEventRecord)
            .filter(CalendarEventRecord.user_id == uid)
            .filter(CalendarEventRecord.provider == provider if provider != "all" else True) # type: ignore
            .order_by(CalendarEventRecord.start_time.asc())
            .limit(limit)
            .all()
        )
        events = [ # type: ignore
            {
                "id": r.id,
                "provider": r.provider,
                "title": r.title,
                "description": r.description,
                "start_time": r.start_time.isoformat(),
                "end_time": r.end_time.isoformat(),
                "timezone": r.timezone,
                "attendees": _json_loads_or(r.attendees_json, []),
                "reminder_minutes": r.reminder_minutes,
                "status": r.status,
            }
            for r in rows
        ]
    return {"status": "ok", "events": events} # type: ignore


@router.post("/calendar/schedule")
def schedule_assistant(req: ScheduleAssistRequest): # type: ignore
    uid = _ensure_user_id(req.user_id)
    start = _parse_iso_datetime(req.window_start)
    end = _parse_iso_datetime(req.window_end)
    duration = max(15, min(req.duration_minutes, 240))

    with SessionLocal() as db:
        busy = (
            db.query(CalendarEventRecord)
            .filter(CalendarEventRecord.user_id == uid)
            .filter(CalendarEventRecord.start_time < end)
            .filter(CalendarEventRecord.end_time > start)
            .order_by(CalendarEventRecord.start_time.asc())
            .all()
        )

    cursor = start
    suggestions = []
    delta = timedelta(minutes=duration)
    for item in busy:
        item_start = _ensure_aware(item.start_time)
        item_end = _ensure_aware(item.end_time)
        if cursor + delta <= item_start:
            suggestions.append({"start": cursor.isoformat(), "end": (cursor + delta).isoformat()}) # type: ignore
            if len(suggestions) >= 3: # type: ignore
                break
        cursor = max(cursor, item_end)

    while len(suggestions) < 3 and cursor + delta <= end: # type: ignore
        suggestions.append({"start": cursor.isoformat(), "end": (cursor + delta).isoformat()}) # type: ignore
        cursor += timedelta(minutes=30)

    return {
        "status": "ok",
        "title": req.title,
        "duration_minutes": duration,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "suggestions": suggestions,
    } # type: ignore


# ── Search diagnostics and provider strategy endpoints ────────────────────────

@router.get("/search")
def search_endpoint(query: str, news_mode: bool = False, max_results: int = 4): # type: ignore
    if not query.strip():
        raise HTTPException(status_code=422, detail="query is required")
    return search_web(query, max_results=max(1, min(max_results, 10)), news_mode=news_mode) # type: ignore


@router.get("/search/diagnostics")
def search_diagnostics(): # type: ignore
    return {"status": "ok", "diagnostics": get_search_diagnostics()} # type: ignore


# ── Semantic memory evolution endpoints ───────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if t]


def _embed_text(text: str, dims: int = 64) -> list[float]:
    vec = [0.0] * dims
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = digest[0] % dims
        sign = -1.0 if digest[1] % 2 else 1.0
        vec[idx] += sign * (1.0 + (digest[2] / 255.0))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    step = max(1, chunk_size - overlap)
    i = 0
    while i < len(text):
        chunks.append(text[i:i + chunk_size]) # type: ignore
        i += step
    return chunks # type: ignore


@router.post("/memory/index")
def memory_index(req: MemoryIndexRequest): # type: ignore
    uid = _ensure_user_id(req.user_id)
    chunks = _chunk_text(req.text)
    if not chunks:
        raise HTTPException(status_code=422, detail="text must contain at least one non-whitespace character")

    priority = max(0.0, min(req.priority, 1.0))
    created = 0
    with SessionLocal() as db:
        for chunk in chunks:
            embedding = _embed_text(chunk)
            db.add(
                MemoryVectorRecord(
                    id=str(uuid.uuid4()),
                    user_id=uid,
                    source=req.source,
                    text_chunk=chunk,
                    embedding_json=_json_dumps(embedding),
                    priority_score=priority,
                    created_at=_now(),
                )
            )
            created += 1
        db.commit()
    return {"status": "indexed", "chunks": created, "source": req.source} # type: ignore


@router.get("/memory/retrieve")
def memory_retrieve(user_id: str, query: str, top_k: int = 5): # type: ignore
    uid = _ensure_user_id(user_id)
    if not query.strip():
        raise HTTPException(status_code=422, detail="query is required")
    k = max(1, min(top_k, 20))
    q_emb = _embed_text(query)

    with SessionLocal() as db:
        rows = (
            db.query(MemoryVectorRecord)
            .filter(MemoryVectorRecord.user_id == uid)
            .order_by(MemoryVectorRecord.created_at.desc())
            .limit(1000)
            .all()
        )

    scored = []
    for row in rows:
        emb = _json_loads_or(row.embedding_json, [])
        if not emb:
            continue
        sim = _cosine(q_emb, emb)
        score = sim * 0.8 + float(row.priority_score or 0.0) * 0.2
        scored.append( # type: ignore
            {
                "id": row.id,
                "source": row.source,
                "text": row.text_chunk,
                "score": round(score, 4),
                "created_at": row.created_at.isoformat(),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True) # type: ignore
    return {"status": "ok", "results": scored[:k]} # type: ignore


@router.post("/memory/compress")
def memory_compress(req: MemoryCompressRequest): # type: ignore
    uid = _ensure_user_id(req.user_id)
    history = get_chat_history(uid, limit=120) # type: ignore
    if not history:
        return {"status": "ok", "summary": get_memory_summary(uid), "messages": 0} # type: ignore

    user_lines = [m.get("content", "") for m in history if m.get("role") == "user"] # type: ignore
    ai_lines = [m.get("content", "") for m in history if m.get("role") == "assistant"] # type: ignore
    summary_parts = []
    if user_lines:
        summary_parts.append("User goals: " + " | ".join(line[:120] for line in user_lines[-4:])) # type: ignore
    if ai_lines:
        summary_parts.append("Assistant outputs: " + " | ".join(line[:120] for line in ai_lines[-4:])) # type: ignore
    summary = "\n".join(summary_parts)[:1800] # type: ignore

    save_memory_summary(uid, summary)
    with SessionLocal() as db:
        row = db.query(MemoryRecord).filter(MemoryRecord.user_id == uid).first()
        if not row:
            row = MemoryRecord(user_id=uid, summary=summary)
            db.add(row)
        else:
            row.summary = summary
            row.updated_at = _now()
        db.commit()

    return {"status": "compressed", "messages": len(history), "summary": summary} # type: ignore


# ── Workflow system ───────────────────────────────────────────────────────────

@router.post("/workflows")
def create_workflow(req: WorkflowCreateRequest):
    uid = _ensure_user_id(req.user_id)
    with SessionLocal() as db:
        row = WorkflowTemplate(
            id=str(uuid.uuid4()),
            user_id=uid,
            name=req.name,
            description=req.description,
            reusable_prompt=req.reusable_prompt,
            action_chain_json=_json_dumps(req.action_chain),
            is_active=True,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(row)
        db.commit()
        return {"status": "created", "workflow_id": row.id}


@router.get("/workflows")
def list_workflows(user_id: str): # type: ignore
    uid = _ensure_user_id(user_id)
    with SessionLocal() as db:
        rows = (
            db.query(WorkflowTemplate)
            .filter(WorkflowTemplate.user_id == uid)
            .order_by(WorkflowTemplate.updated_at.desc())
            .all()
        )
    return {
        "status": "ok",
        "workflows": [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "reusable_prompt": row.reusable_prompt,
                "action_chain": _json_loads_or(row.action_chain_json, []),
                "is_active": row.is_active,
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ],
    } # type: ignore


@router.post("/workflows/{workflow_id}/execute")
def execute_workflow(workflow_id: str, req: WorkflowExecuteRequest): # type: ignore
    uid = _ensure_user_id(req.user_id)
    with SessionLocal() as db:
        wf = (
            db.query(WorkflowTemplate)
            .filter(WorkflowTemplate.id == workflow_id, WorkflowTemplate.user_id == uid)
            .first()
        )
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")

        actions = _json_loads_or(wf.action_chain_json, [])
        step_results = []
        status = "completed"
        error_msg = None

        try:
            for idx, action in enumerate(actions, start=1):
                action_type = (action.get("type") or "chat").lower()
                template = action.get("prompt") or req.input_text
                message = template.replace("{{input}}", req.input_text)

                if action_type == "chat":
                    result = route_message(message, user_id=uid) # type: ignore
                    step_results.append({"step": idx, "type": action_type, "result": result.get("response", "")}) # type: ignore
                elif action_type == "search":
                    result = search_web(message, news_mode=bool(action.get("news_mode", False))) # type: ignore
                    step_results.append({"step": idx, "type": action_type, "result": result.get("response", "")}) # type: ignore
                elif action_type == "email_draft":
                    draft = EmailDraftRecord(
                        id=str(uuid.uuid4()),
                        user_id=uid,
                        provider=action.get("provider", "smtp"),
                        to_recipients=_json_dumps(action.get("to", [])),
                        cc_recipients=_json_dumps(action.get("cc", [])),
                        bcc_recipients=_json_dumps(action.get("bcc", [])),
                        subject=action.get("subject", "Workflow Draft"),
                        body=message,
                        attachments_json=_json_dumps(action.get("attachments", [])),
                        status="draft",
                        created_at=_now(),
                        updated_at=_now(),
                    )
                    db.add(draft)
                    step_results.append({"step": idx, "type": action_type, "result": f"draft:{draft.id}"}) # type: ignore
                elif action_type == "calendar_event":
                    now = _now()
                    start_time = now + timedelta(hours=1)
                    end_time = start_time + timedelta(minutes=int(action.get("duration_minutes", 30)))
                    evt = CalendarEventRecord(
                        id=str(uuid.uuid4()),
                        user_id=uid,
                        provider=action.get("provider", "local"),
                        external_event_id=None,
                        title=action.get("title", "Workflow Event"),
                        description=message,
                        start_time=start_time,
                        end_time=end_time,
                        timezone=action.get("timezone", "UTC"),
                        attendees_json=_json_dumps(action.get("attendees", [])),
                        reminder_minutes=action.get("reminder_minutes", 15),
                        status="confirmed",
                        created_at=_now(),
                    )
                    db.add(evt)
                    step_results.append({"step": idx, "type": action_type, "result": f"event:{evt.id}"}) # type: ignore
                else:
                    step_results.append({"step": idx, "type": action_type, "result": "skipped:unknown_action"}) # type: ignore

            output_summary = " | ".join(str(s.get("result", ""))[:160] for s in step_results)[:4000] # type: ignore
        except Exception as exc:
            status = "failed"
            error_msg = str(exc)
            output_summary = ""

        run = WorkflowRunRecord(
            id=str(uuid.uuid4()),
            workflow_id=wf.id,
            user_id=uid,
            input_text=req.input_text,
            output_summary=output_summary,
            step_results_json=_json_dumps(step_results),
            status=status,
            error_msg=error_msg,
            created_at=_now(),
            completed_at=_now(),
        )
        db.add(run)
        wf.updated_at = _now()
        db.commit()

        if status != "completed":
            raise HTTPException(status_code=500, detail=error_msg or "Workflow execution failed")

        return {"status": "completed", "run_id": run.id, "step_results": step_results, "summary": output_summary} # type: ignore


@router.get("/workflows/{workflow_id}/history")
def workflow_history(workflow_id: str, user_id: str, limit: int = 20): # type: ignore
    uid = _ensure_user_id(user_id)
    limit = max(1, min(limit, 100))
    with SessionLocal() as db:
        rows = (
            db.query(WorkflowRunRecord)
            .filter(WorkflowRunRecord.workflow_id == workflow_id, WorkflowRunRecord.user_id == uid)
            .order_by(WorkflowRunRecord.created_at.desc())
            .limit(limit)
            .all()
        )
    return {
        "status": "ok",
        "runs": [
            {
                "run_id": r.id,
                "status": r.status,
                "input_text": r.input_text,
                "summary": r.output_summary,
                "steps": _json_loads_or(r.step_results_json, []),
                "error_msg": r.error_msg,
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ],
    } # type: ignore
