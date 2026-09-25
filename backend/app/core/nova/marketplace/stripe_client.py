"""Dedicated Stripe TEST client for AMICOR one-time marketplace purchases."""
from __future__ import annotations

import os
from typing import Any, Protocol

from app.core.nova.signup.stripe_client import STRIPE_HTTP_TIMEOUT_SECONDS, sanitize_stripe_error
from app.helpers import uuid4

_OVERRIDE: "MarketplaceStripeClient | None" = None


class MarketplaceStripeClient(Protocol):
    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...


def marketplace_secret_key() -> str:
    return (
        os.getenv("STRIPE_MARKETPLACE_SECRET_KEY", "").strip()
        or os.getenv("STRIPE_SECRET_KEY", "").strip()
    )


def marketplace_webhook_secret() -> str:
    return os.getenv("STRIPE_MARKETPLACE_WEBHOOK_SECRET", "").strip()


def set_marketplace_stripe_override(client: MarketplaceStripeClient | None) -> None:
    global _OVERRIDE
    _OVERRIDE = client


def get_marketplace_stripe_override() -> MarketplaceStripeClient | None:
    return _OVERRIDE


def get_marketplace_stripe_client() -> MarketplaceStripeClient:
    if _OVERRIDE is not None:
        return _OVERRIDE
    secret = marketplace_secret_key()
    if not secret:
        raise ValueError("Stripe TEST key is not configured for AMICOR Marketplace.")
    if not secret.startswith("sk_test_"):
        raise ValueError("AMICOR Marketplace checkout is TEST-only and rejects non-test Stripe keys.")
    return LiveMarketplaceStripeClient(secret)


class FakeMarketplaceStripeClient:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}
        self.created_count = 0

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        existing = self.keys.get(idempotency_key)
        if existing:
            return dict(self.sessions[existing])
        self.created_count += 1
        sid = f"cs_test_market_{self.created_count}_{uuid4()[:8]}"
        record = {
            "id": sid,
            "object": "checkout.session",
            "mode": "payment",
            "status": "open",
            "payment_status": "unpaid",
            "url": f"https://checkout.stripe.com/c/pay/{sid}",
            "client_reference_id": payload.get("client_reference_id"),
            "customer_email": payload.get("customer_email"),
            "metadata": dict(payload.get("metadata") or {}),
            "line_items": list(payload.get("line_items") or []),
            "success_url": payload.get("success_url"),
            "cancel_url": payload.get("cancel_url"),
        }
        self.sessions[sid] = record
        self.keys[idempotency_key] = sid
        return dict(record)


class LiveMarketplaceStripeClient:
    def __init__(self, api_key: str) -> None:
        if not str(api_key).startswith("sk_test_"):
            raise ValueError("AMICOR Marketplace checkout is TEST-only.")
        self.api_key = api_key

    def _client(self):
        from stripe import StripeClient
        import stripe as stripe_mod
        requests_cls = getattr(stripe_mod, "RequestsClient", None)
        httpx_cls = getattr(stripe_mod, "HTTPXClient", None)
        if requests_cls is not None:
            try:
                return StripeClient(self.api_key, http_client=requests_cls(timeout=STRIPE_HTTP_TIMEOUT_SECONDS))
            except TypeError:
                return StripeClient(self.api_key, http_client=requests_cls())
        if httpx_cls is not None:
            try:
                return StripeClient(self.api_key, http_client=httpx_cls(timeout=STRIPE_HTTP_TIMEOUT_SECONDS, allow_sync_methods=True))
            except TypeError:
                return StripeClient(self.api_key, http_client=httpx_cls(timeout=STRIPE_HTTP_TIMEOUT_SECONDS))
        raise RuntimeError("Stripe HTTP client unavailable.")

    @staticmethod
    def _dict(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        payload = getattr(obj, "to_dict", lambda: {})()
        if isinstance(payload, dict):
            return payload
        return {"id": getattr(obj, "id", None), "url": getattr(obj, "url", None)}

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        try:
            created = self._client().v1.checkout.sessions.create(payload, {"idempotency_key": idempotency_key})
            return self._dict(created)
        except Exception as exc:
            raise RuntimeError(f"Marketplace Stripe checkout unavailable: {sanitize_stripe_error(exc)}") from exc
