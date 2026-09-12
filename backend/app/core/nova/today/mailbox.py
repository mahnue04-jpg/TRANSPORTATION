"""Nova V2 Phase 4 mailbox read model. Uses existing IntegrationAccount only."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.auth import UserContext
from app.core.nova.communications.models import NovaCommunicationsMessage
from app.db.models import IntegrationAccount
from app.helpers import json_loads_or, now
from sqlalchemy.orm import Session

STALE_AFTER = timedelta(hours=6)
FRESH_WITHIN = timedelta(minutes=30)


class MailboxItem:
    def __init__(self, **payload: Any) -> None:
        self.external_message_id = str(payload.get("external_message_id") or "")
        self.provider = str(payload.get("provider") or "")
        self.sender = str(payload.get("sender") or "")
        self.recipients = list(payload.get("recipients") or [])
        self.subject = str(payload.get("subject") or "(no subject)")
        self.received_at = payload.get("received_at")
        self.unread = bool(payload.get("unread", True))
        self.important = bool(payload.get("important", False))
        self.snippet = str(payload.get("snippet") or "")[:240]
        self.connector_account_id = str(payload.get("connector_account_id") or "")
        self.source_href = payload.get("source_href")
        self.source_health = str(payload.get("source_health") or "ok")
        self.message_id = payload.get("message_id")


class ConnectorHealth:
    def __init__(
        self,
        *,
        status: str,
        provider: str | None = None,
        account_email: str | None = None,
        connector_account_id: str | None = None,
        last_success_at: datetime | None = None,
        last_attempted_at: datetime | None = None,
        freshness: str = "unknown",
        stale_age_seconds: int | None = None,
        recheck_available: bool = False,
        detail: str,
    ) -> None:
        self.status = status
        self.provider = provider
        self.account_email = account_email
        self.connector_account_id = connector_account_id
        self.last_success_at = last_success_at
        self.last_attempted_at = last_attempted_at
        self.freshness = freshness
        self.stale_age_seconds = stale_age_seconds
        self.recheck_available = recheck_available
        self.detail = detail

    def as_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "provider": self.provider,
            "account_email": self.account_email,
            "connector_account_id": self.connector_account_id,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_attempted_at": self.last_attempted_at.isoformat() if self.last_attempted_at else None,
            "freshness": self.freshness,
            "stale_age_seconds": str(self.stale_age_seconds) if self.stale_age_seconds is not None else None,
            "recheck_available": "yes" if self.recheck_available else "no",
            "detail": self.detail,
        }


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_received(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return _as_utc(parsed)
    except ValueError:
        try:
            return _as_utc(parsedate_to_datetime(text))
        except Exception:
            return None


def _stable_message_id(external_id: str) -> str:
    digest = hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:12].upper()
    return f"NCM-{digest}"


def owner_email_accounts(db: Session, user: UserContext) -> list[IntegrationAccount]:
    return (
        db.query(IntegrationAccount)
        .filter(IntegrationAccount.user_id == user.user_id, IntegrationAccount.service == "email")
        .order_by(IntegrationAccount.updated_at.desc())
        .all()
    )


def get_owner_account(
    db: Session,
    user: UserContext,
    connector_account_id: str | None = None,
) -> IntegrationAccount | None:
    accounts = owner_email_accounts(db, user)
    if connector_account_id:
        match = next((row for row in accounts if row.id == connector_account_id), None)
        if match is None:
            raise PermissionError("Connector account is not available to this owner")
        return match
    usable = [row for row in accounts if row.provider in {"gmail", "outlook"} and (row.access_token or row.account_email)]
    return usable[0] if usable else (accounts[0] if accounts else None)


def last_success_from_meta(account: IntegrationAccount | None) -> datetime | None:
    if account is None:
        return None
    meta = json_loads_or(account.meta_json, {})
    if not isinstance(meta, dict):
        return None
    return _parse_received(str(meta.get("last_mailbox_read_at") or ""))


def last_attempt_from_meta(account: IntegrationAccount | None) -> datetime | None:
    if account is None:
        return None
    meta = json_loads_or(account.meta_json, {})
    if not isinstance(meta, dict):
        return None
    return _parse_received(str(meta.get("last_mailbox_attempt_at") or ""))


def token_expired(account: IntegrationAccount | None) -> bool:
    if account is None or not account.token_expires_at:
        return False
    return bool(_as_utc(account.token_expires_at) < now())


def freshness_for(last_success_at: datetime | None, *, at: datetime | None = None) -> tuple[str, int | None]:
    if last_success_at is None:
        return "unknown", None
    stamp = at or now()
    success = _as_utc(last_success_at)
    if success is None:
        return "unknown", None
    age = max(0, int((stamp - success).total_seconds()))
    if stamp - success <= FRESH_WITHIN:
        return "fresh", age
    if stamp - success <= STALE_AFTER:
        return "aging", age
    return "stale", age


def recheck_available_for(account: IntegrationAccount | None) -> bool:
    if account is None:
        return False
    return str(account.provider or "").lower() in {"gmail", "outlook"}


def try_authorized_refresh(account: IntegrationAccount) -> str:
    """Reuse existing Outlook refresh only. Do not invent a Gmail OAuth refresh helper."""
    provider = str(account.provider or "").lower()
    if provider == "smtp":
        raise RuntimeError("SMTP accounts cannot read a mailbox")
    if provider == "gmail":
        if token_expired(account):
            raise RuntimeError("Gmail token expired and no refresh helper exists")
        if not account.access_token:
            raise RuntimeError("Gmail integration has no access token")
        return account.access_token
    if provider == "outlook":
        from app.ecosystem import _refresh_outlook_if_needed

        try:
            return _refresh_outlook_if_needed(account)
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            raise RuntimeError(str(detail)) from exc
    raise RuntimeError(f"Unsupported mailbox provider {provider}")


def _health_for_account(
    account: IntegrationAccount | None,
    *,
    status: str,
    detail: str,
    last_success_at: datetime | None = None,
    last_attempted_at: datetime | None = None,
) -> ConnectorHealth:
    success_at = last_success_at or last_success_from_meta(account)
    freshness, stale_age = freshness_for(success_at)
    return ConnectorHealth(
        status=status,
        provider=account.provider if account else None,
        account_email=account.account_email if account else None,
        connector_account_id=account.id if account else None,
        last_success_at=success_at,
        last_attempted_at=last_attempted_at or last_attempt_from_meta(account),
        freshness=freshness,
        stale_age_seconds=stale_age,
        recheck_available=recheck_available_for(account),
        detail=detail,
    )


def fetch_provider_messages(account: IntegrationAccount, *, limit: int = 12) -> list[dict[str, Any]]:
    """Read-only metadata via existing ecosystem inbox helpers. No send. No new credentials."""
    from app.ecosystem import _gmail_inbox, _outlook_inbox

    provider = str(account.provider or "").lower()
    if provider == "smtp":
        return []
    token = try_authorized_refresh(account)
    if provider == "gmail":
        return list(_gmail_inbox(token, limit) or [])
    if provider == "outlook":
        return list(_outlook_inbox(token, limit) or [])
    raise RuntimeError(f"Unsupported mailbox provider {provider}")


def normalize_provider_row(
    row: dict[str, Any],
    *,
    account: IntegrationAccount,
) -> MailboxItem | None:
    external_id = str(row.get("id") or row.get("external_message_id") or "").strip()
    if not external_id:
        return None
    unread = row.get("unread")
    if unread is None:
        unread = True
    important = bool(row.get("important", False))
    labels = [str(item).upper() for item in (row.get("label_ids") or row.get("labelIds") or [])]
    if "UNREAD" in labels:
        unread = True
    if "IMPORTANT" in labels:
        important = True
    return MailboxItem(
        external_message_id=external_id,
        provider=account.provider,
        sender=str(row.get("from") or row.get("sender") or account.account_email or "unknown"),
        recipients=list(row.get("recipients") or []),
        subject=str(row.get("subject") or "(no subject)")[:512],
        received_at=_parse_received(str(row.get("date") or row.get("received_at") or "")),
        unread=bool(unread),
        important=important,
        snippet=str(row.get("snippet") or "")[:240],
        connector_account_id=account.id,
        source_href="/nova/communications",
        source_health="ok",
        message_id=_stable_message_id(f"{account.id}:{external_id}"),
    )


def upsert_mailbox_item(
    db: Session,
    item: MailboxItem,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaCommunicationsMessage | None:
    if not item.message_id:
        return None
    existing = (
        db.query(NovaCommunicationsMessage)
        .filter(NovaCommunicationsMessage.message_id == item.message_id)
        .first()
    )
    if existing is not None:
        if existing.organization_id != organization_id or existing.owner_user_id != user.user_id:
            return None
        existing.sender = item.sender[:320]
        existing.subject = item.subject[:512]
        existing.snippet = item.snippet or existing.snippet
        existing.read = not item.unread
        existing.important = item.important
        existing.source = item.provider[:32]
        existing.source_ref = item.external_message_id[:64]
        if item.received_at:
            existing.created_at = item.received_at
        return existing
    row = NovaCommunicationsMessage(
        message_id=item.message_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        sender=item.sender[:320],
        subject=item.subject[:512],
        body="",
        snippet=item.snippet,
        read=not item.unread,
        important=item.important,
        source=item.provider[:32],
        source_ref=item.external_message_id[:64],
        created_at=item.received_at or now(),
    )
    db.add(row)
    return row


def _account_meta(account: IntegrationAccount) -> dict[str, Any]:
    meta = json_loads_or(account.meta_json, {})
    return meta if isinstance(meta, dict) else {}


def _mark_attempt(account: IntegrationAccount) -> datetime:
    stamp = now()
    meta = _account_meta(account)
    meta["last_mailbox_attempt_at"] = stamp.isoformat()
    from app.helpers import json_dumps

    account.meta_json = json_dumps(meta)
    account.updated_at = stamp
    return stamp


def _mark_success(account: IntegrationAccount) -> datetime:
    stamp = now()
    meta = _account_meta(account)
    meta["last_mailbox_read_at"] = stamp.isoformat()
    meta["last_mailbox_attempt_at"] = stamp.isoformat()
    from app.helpers import json_dumps

    account.meta_json = json_dumps(meta)
    account.updated_at = stamp
    return stamp


def read_mailbox(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    connector_account_id: str | None = None,
    persist: bool = True,
    limit: int = 12,
) -> tuple[list[MailboxItem], ConnectorHealth]:
    account = get_owner_account(db, user, connector_account_id)
    if account is None:
        return [], _health_for_account(
            None,
            status="disconnected",
            detail="No mailbox connector is connected. Today did not invent messages.",
        )
    attempted_at = _mark_attempt(account)
    if account.provider == "smtp":
        return [], _health_for_account(
            account,
            status="unavailable",
            detail="SMTP accounts cannot read a mailbox. No messages were invented.",
            last_attempted_at=attempted_at,
        )
    expired = token_expired(account)
    last_success = last_success_from_meta(account)
    try:
        raw = fetch_provider_messages(account, limit=limit)
    except Exception as exc:
        if expired or "token" in str(exc).lower() or "refresh" in str(exc).lower():
            status = "stale"
            detail = "Mailbox connector token is stale or expired. Today did not invent messages."
        else:
            status = "unavailable"
            detail = "Mailbox connector is unavailable. Today did not invent messages."
        return [], _health_for_account(
            account,
            status=status,
            detail=detail,
            last_success_at=last_success,
            last_attempted_at=attempted_at,
        )

    items: list[MailboxItem] = []
    for row in raw:
        item = normalize_provider_row(row, account=account)
        if item is None:
            continue
        if persist:
            saved = upsert_mailbox_item(db, item, organization_id=organization_id, user=user)
            if saved is not None:
                item.message_id = saved.message_id
                item.source_href = "/nova/communications"
        items.append(item)
    if persist:
        db.flush()
    items.sort(
        key=lambda row: (
            row.important,
            row.unread,
            row.received_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    success_at = _mark_success(account)
    status = "connected"
    if token_expired(account):
        status = "degraded"
    elif last_success and now() - last_success > STALE_AFTER and not items:
        status = "stale"
    return items, _health_for_account(
        account,
        status=status,
        detail=f"{len(items)} connector messages read. Nothing was sent." if items else "Mailbox connector is present. No unread or important messages were invented.",
        last_success_at=success_at,
        last_attempted_at=success_at,
    )
