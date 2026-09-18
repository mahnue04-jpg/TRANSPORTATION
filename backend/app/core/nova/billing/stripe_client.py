"""Nova subscription Stripe TEST client. Not Health, Freight, Delivery, or Connect billing."""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from app.core.nova.signup.stripe_client import (
    STRIPE_HTTP_TIMEOUT_SECONDS,
    is_live_stripe_key,
    nova_live_stripe_enabled,
    sanitize_stripe_error,
    stripe_secret_key,
)
from app.helpers import uuid4

logger = logging.getLogger("amicor.nova.billing.stripe")

_CLIENT_OVERRIDE: "NovaBillingStripeClient | None" = None


class NovaBillingStripeClient(Protocol):
    def create_customer(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        ...

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        ...

    def create_billing_portal_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        ...


def nova_billing_webhook_secret() -> str:
    return (
        os.getenv("STRIPE_NOVA_BILLING_WEBHOOK_SECRET", "").strip()
        or os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    )


def set_nova_billing_stripe_override(client: NovaBillingStripeClient | None) -> None:
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def get_nova_billing_stripe_override() -> NovaBillingStripeClient | None:
    return _CLIENT_OVERRIDE


def get_nova_billing_stripe_client() -> NovaBillingStripeClient:
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    secret = stripe_secret_key()
    if not secret:
        raise ValueError("Stripe TEST key is not configured for Nova billing.")
    if is_live_stripe_key(secret) and not nova_live_stripe_enabled():
        raise ValueError("Live Stripe key detected but NOVA_STRIPE_LIVE_ENABLED is not explicitly enabled.")
    return LiveNovaBillingStripeClient(api_key=secret)


class FakeNovaBillingStripeClient:
    """In-process TEST double. Never contacts Stripe and never creates a charge."""

    def __init__(self) -> None:
        self.customers: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.portals: list[dict[str, Any]] = []
        self.customer_keys: dict[str, str] = {}
        self.checkout_keys: dict[str, str] = {}
        self.created_customers = 0
        self.created_sessions = 0

    def create_customer(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        existing_id = self.customer_keys.get(idempotency_key)
        if existing_id and existing_id in self.customers:
            return dict(self.customers[existing_id])
        self.created_customers += 1
        customer_id = f"cus_nova_bill_{self.created_customers}_{uuid4()[:8]}"
        record = {
            "id": customer_id,
            "object": "customer",
            "email": payload.get("email"),
            "metadata": dict(payload.get("metadata") or {}),
        }
        self.customers[customer_id] = record
        self.customer_keys[idempotency_key] = customer_id
        return dict(record)

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        existing_id = self.checkout_keys.get(idempotency_key)
        if existing_id and existing_id in self.sessions:
            return dict(self.sessions[existing_id])
        self.created_sessions += 1
        session_id = f"cs_test_nova_bill_{self.created_sessions}_{uuid4()[:8]}"
        record = {
            "id": session_id,
            "object": "checkout.session",
            "mode": "subscription",
            "status": "open",
            "url": f"https://checkout.stripe.com/c/pay/{session_id}",
            "customer": payload.get("customer"),
            "client_reference_id": payload.get("client_reference_id"),
            "metadata": dict(payload.get("metadata") or {}),
            "subscription_data": dict(payload.get("subscription_data") or {}),
            "line_items": list(payload.get("line_items") or []),
            "success_url": payload.get("success_url"),
            "cancel_url": payload.get("cancel_url"),
        }
        self.sessions[session_id] = record
        self.checkout_keys[idempotency_key] = session_id
        return dict(record)

    def create_billing_portal_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        portal_id = f"bps_nova_{uuid4()[:8]}"
        record = {
            "id": portal_id,
            "url": f"https://billing.stripe.com/p/session/{portal_id}",
            "customer": payload.get("customer"),
            "return_url": payload.get("return_url"),
            "idempotency_key": idempotency_key,
        }
        self.portals.append(record)
        return dict(record)


class LiveNovaBillingStripeClient:
    def __init__(self, *, api_key: str):
        if is_live_stripe_key(api_key) and not nova_live_stripe_enabled():
            raise ValueError("Live Stripe key detected but NOVA_STRIPE_LIVE_ENABLED is not explicitly enabled.")
        self.api_key = api_key

    def _build_client(self) -> Any:
        try:
            from stripe import StripeClient
        except Exception as exc:
            raise RuntimeError("Stripe SDK import is unavailable.") from exc
        import stripe as stripe_mod

        requests_cls = getattr(stripe_mod, "RequestsClient", None)
        httpx_cls = getattr(stripe_mod, "HTTPXClient", None)
        last_exc: BaseException | None = None
        if requests_cls is not None:
            try:
                try:
                    http_client = requests_cls(timeout=STRIPE_HTTP_TIMEOUT_SECONDS)
                except TypeError:
                    http_client = requests_cls()
                return StripeClient(self.api_key, http_client=http_client)
            except (TypeError, ImportError, ModuleNotFoundError) as exc:
                last_exc = exc
        if httpx_cls is not None:
            try:
                try:
                    http_client = httpx_cls(timeout=STRIPE_HTTP_TIMEOUT_SECONDS, allow_sync_methods=True)
                except TypeError:
                    http_client = httpx_cls(timeout=STRIPE_HTTP_TIMEOUT_SECONDS)
                return StripeClient(self.api_key, http_client=http_client)
            except (TypeError, ImportError, ModuleNotFoundError) as exc:
                last_exc = exc
        raise RuntimeError(f"Stripe HTTP client unavailable: {sanitize_stripe_error(last_exc)}")

    def _as_dict(self, created: Any) -> dict[str, Any]:
        payload = created if isinstance(created, dict) else getattr(created, "to_dict", lambda: {})()
        if isinstance(payload, dict) and payload.get("id"):
            return payload
        return {
            "id": getattr(created, "id", None),
            "url": getattr(created, "url", None),
            "customer": getattr(created, "customer", None),
            "metadata": getattr(created, "metadata", {}) or {},
        }

    def create_customer(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        client = self._build_client()
        created = client.v1.customers.create(payload, {"idempotency_key": idempotency_key})
        return self._as_dict(created)

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        client = self._build_client()
        created = client.v1.checkout.sessions.create(payload, {"idempotency_key": idempotency_key})
        return self._as_dict(created)

    def create_billing_portal_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        client = self._build_client()
        created = client.v1.billing_portal.sessions.create(payload, {"idempotency_key": idempotency_key})
        return self._as_dict(created)
