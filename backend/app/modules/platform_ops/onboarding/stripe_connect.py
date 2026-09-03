"""Hosted Stripe Connect onboarding for driver payouts.

Uses Accounts v2 (marketplace / recipient). Stores only the connected-account
ID and status fields — never bank routing or account numbers.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

logger = logging.getLogger("amicor.platform_ops.stripe_connect")

PAYOUT_STATUS_NOT_STARTED = "not_started"
PAYOUT_STATUS_PENDING = "pending_verification"
PAYOUT_STATUS_COMPLETE = "complete"
PAYOUT_STATUS_NEEDS_ATTENTION = "needs_attention"
PAYOUT_STATUS_NOT_CONFIGURED = "not_configured"

PAYOUT_DISPLAY = {
    PAYOUT_STATUS_NOT_STARTED: "Not started",
    PAYOUT_STATUS_PENDING: "Pending verification",
    PAYOUT_STATUS_COMPLETE: "Complete",
    PAYOUT_STATUS_NEEDS_ATTENTION: "Needs attention",
    PAYOUT_STATUS_NOT_CONFIGURED: "Needs attention",
}

_CLIENT_OVERRIDE: "StripeConnectClient | None" = None


class StripeConnectClient(Protocol):
    def create_recipient_account(
        self,
        *,
        display_name: str,
        email: str | None,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        ...

    def create_account_onboarding_link(
        self,
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        ...

    def retrieve_account(self, account_id: str) -> dict[str, Any]:
        ...


def stripe_secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def is_stripe_connect_configured() -> bool:
    return bool(stripe_secret_key()) or _CLIENT_OVERRIDE is not None


def set_stripe_connect_client_override(client: StripeConnectClient | None) -> None:
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def get_stripe_connect_client() -> StripeConnectClient | None:
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    if not stripe_secret_key():
        return None
    return LiveStripeConnectClient(api_key=stripe_secret_key())


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, dict):
            return converted
    dumped = getattr(value, "model_dump", None)
    if callable(dumped):
        converted = dumped()
        if isinstance(converted, dict):
            return converted
    return {}


def _nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def map_account_to_payout_status(account: dict[str, Any] | None) -> dict[str, Any]:
    """Map a Stripe account payload to stored status fields. Never includes bank data."""
    payload = _as_dict(account)
    account_id = str(payload.get("id") or "").strip() or None
    transfer_status = str(
        _nested(
            payload,
            "configuration",
            "recipient",
            "capabilities",
            "stripe_balance",
            "stripe_transfers",
            "status",
        )
        or ""
    ).lower()
    details_submitted = bool(
        payload.get("details_submitted")
        or _nested(payload, "requirements", "currently_due") == []
        and payload.get("details_submitted") is not False
    )
    if transfer_status == "active":
        status = PAYOUT_STATUS_COMPLETE
        payouts_enabled = True
        details_submitted = True
    elif transfer_status in {"restricted", "inactive", "unrequested"}:
        status = PAYOUT_STATUS_NEEDS_ATTENTION
        payouts_enabled = False
    elif transfer_status in {"pending", "pending_verification"}:
        status = PAYOUT_STATUS_PENDING
        payouts_enabled = False
        details_submitted = True
    elif payload.get("payouts_enabled") is True:
        status = PAYOUT_STATUS_COMPLETE
        payouts_enabled = True
        details_submitted = True
    elif details_submitted or payload.get("details_submitted"):
        status = PAYOUT_STATUS_PENDING
        payouts_enabled = False
        details_submitted = True
    elif account_id:
        status = PAYOUT_STATUS_PENDING
        payouts_enabled = False
    else:
        status = PAYOUT_STATUS_NOT_STARTED
        payouts_enabled = False
        details_submitted = False
    currently_due = _nested(payload, "requirements", "currently_due")
    past_due = _nested(payload, "requirements", "past_due")
    if (isinstance(currently_due, list) and currently_due) or (isinstance(past_due, list) and past_due):
        if status != PAYOUT_STATUS_COMPLETE:
            status = PAYOUT_STATUS_NEEDS_ATTENTION
    return {
        "stripe_account_id": account_id,
        "stripe_onboarding_status": status,
        "stripe_payouts_enabled": payouts_enabled,
        "stripe_details_submitted": bool(details_submitted),
    }


class LiveStripeConnectClient:
    """Stripe Accounts v2 recipient + hosted Account Link onboarding."""

    def __init__(self, *, api_key: str):
        self.api_key = api_key

    def _client(self):
        import stripe

        return stripe.StripeClient(self.api_key)

    def create_recipient_account(
        self,
        *,
        display_name: str,
        email: str | None,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "display_name": display_name[:150] or "Amicor driver",
            "dashboard": "express",
            "identity": {"country": "us"},
            "defaults": {
                "responsibilities": {
                    "fees_collector": "application",
                    "losses_collector": "application",
                }
            },
            "configuration": {
                "recipient": {
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {"requested": True},
                        }
                    }
                }
            },
            "metadata": metadata,
        }
        if email:
            payload["contact_email"] = email
        client = self._client()
        created = client.v2.core.accounts.create(payload)
        return _as_dict(created)

    def create_account_onboarding_link(
        self,
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        client = self._client()
        created = client.v1.account_links.create(
            {
                "account": account_id,
                "refresh_url": refresh_url,
                "return_url": return_url,
                "type": "account_onboarding",
            }
        )
        return _as_dict(created)

    def retrieve_account(self, account_id: str) -> dict[str, Any]:
        client = self._client()
        retrieved = client.v2.core.accounts.retrieve(account_id)
        return _as_dict(retrieved)


class FakeStripeConnectClient:
    """In-process Connect client for tests. Never talks to Stripe."""

    def __init__(self) -> None:
        self.accounts: dict[str, dict[str, Any]] = {}
        self.created_count = 0
        self.link_count = 0
        self.last_account_id: str | None = None

    def create_recipient_account(
        self,
        *,
        display_name: str,
        email: str | None,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        self.created_count += 1
        account_id = f"acct_test_{self.created_count}"
        self.accounts[account_id] = {
            "id": account_id,
            "display_name": display_name,
            "contact_email": email,
            "metadata": dict(metadata),
            "details_submitted": False,
            "payouts_enabled": False,
            "configuration": {
                "recipient": {
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {"status": "pending"},
                        }
                    }
                }
            },
        }
        self.last_account_id = account_id
        return {"id": account_id}

    def create_account_onboarding_link(
        self,
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        if account_id not in self.accounts:
            raise ValueError("Unknown connected account.")
        self.link_count += 1
        return {
            "url": f"https://connect.stripe.test/setup/{account_id}?return_url=1",
            "refresh_url": refresh_url,
            "return_url": return_url,
        }

    def retrieve_account(self, account_id: str) -> dict[str, Any]:
        if account_id not in self.accounts:
            raise ValueError("Unknown connected account.")
        return dict(self.accounts[account_id])

    def mark_complete(self, account_id: str | None = None) -> None:
        target = account_id or self.last_account_id
        if not target or target not in self.accounts:
            raise ValueError("Unknown connected account.")
        row = self.accounts[target]
        row["details_submitted"] = True
        row["payouts_enabled"] = True
        row["configuration"]["recipient"]["capabilities"]["stripe_balance"]["stripe_transfers"][
            "status"
        ] = "active"
