"""Stripe Checkout for the public Nova Anonymous Operations Agent.

This module is isolated from Health, Freight, Delivery, and Nova SaaS subscription
billing. Live mode remains fail-closed behind NOVA_STRIPE_LIVE_ENABLED.
"""
from __future__ import annotations

import json
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

AGENT_PRODUCT = "nova_anonymous_operations_agent"
AGENT_WEBHOOK_ENV = "STRIPE_NOVA_AGENT_WEBHOOK_SECRET"

AGENT_PLANS: dict[str, dict[str, Any]] = {
    "free_scope": {
        "label": "Free Scope Check",
        "amount_cents": 0,
        "mode": "free",
    },
    "starter_49": {
        "label": "$49 Starter Task",
        "amount_cents": 4900,
        "mode": "payment",
    },
    "launch_99": {
        "label": "$99/month Launch Operations",
        "amount_cents": 9900,
        "mode": "subscription",
        "interval": "month",
    },
    "business_299": {
        "label": "$299/month Business Operations",
        "amount_cents": 29900,
        "mode": "subscription",
        "interval": "month",
    },
    "not_sure": {
        "label": "Not sure — help me choose",
        "amount_cents": 0,
        "mode": "review",
    },
}

_CLIENT_OVERRIDE: "AgentStripeClient | None" = None


class AgentStripeClient(Protocol):
    def create_customer(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        ...

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        ...


class FakeAgentStripeClient:
    """In-process checkout double used by tests. Never contacts Stripe."""

    def __init__(self) -> None:
        self.customers: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.customer_keys: dict[str, str] = {}
        self.session_keys: dict[str, str] = {}
        self.last_payload: dict[str, Any] | None = None

    def create_customer(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        existing = self.customer_keys.get(idempotency_key)
        if existing:
            return dict(self.customers[existing])
        customer_id = f"cus_agent_test_{uuid4()[:10]}"
        row = {"id": customer_id, "email": payload.get("email"), "metadata": dict(payload.get("metadata") or {})}
        self.customers[customer_id] = row
        self.customer_keys[idempotency_key] = customer_id
        return dict(row)

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        existing = self.session_keys.get(idempotency_key)
        if existing:
            return dict(self.sessions[existing])
        session_id = f"cs_test_agent_{uuid4()[:10]}"
        row = {
            "id": session_id,
            "url": f"https://checkout.stripe.com/c/pay/{session_id}",
            "mode": payload.get("mode"),
            "customer": payload.get("customer"),
            "metadata": dict(payload.get("metadata") or {}),
            "line_items": list(payload.get("line_items") or []),
            "payment_status": "unpaid",
            "status": "open",
        }
        self.sessions[session_id] = row
        self.session_keys[idempotency_key] = session_id
        self.last_payload = dict(payload)
        return dict(row)


class LiveAgentStripeClient:
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

    @staticmethod
    def _as_dict(created: Any) -> dict[str, Any]:
        payload = created if isinstance(created, dict) else getattr(created, "to_dict", lambda: {})()
        if isinstance(payload, dict):
            return payload
        return {
            "id": getattr(created, "id", None),
            "url": getattr(created, "url", None),
            "customer": getattr(created, "customer", None),
            "status": getattr(created, "status", None),
            "payment_status": getattr(created, "payment_status", None),
        }

    def create_customer(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        client = self._build_client()
        created = client.v1.customers.create(payload, {"idempotency_key": idempotency_key})
        return self._as_dict(created)

    def create_checkout_session(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        client = self._build_client()
        created = client.v1.checkout.sessions.create(payload, {"idempotency_key": idempotency_key})
        return self._as_dict(created)


def set_agent_stripe_override(client: AgentStripeClient | None) -> None:
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def agent_webhook_secret() -> str:
    return (os.getenv(AGENT_WEBHOOK_ENV) or "").strip()


def agent_checkout_mode() -> str:
    secret = stripe_secret_key()
    if not secret:
        return "not_configured"
    if is_live_stripe_key(secret):
        return "live" if nova_live_stripe_enabled() and bool(agent_webhook_secret()) else "live_gated"
    return "test"


def get_agent_stripe_client() -> AgentStripeClient:
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    secret = stripe_secret_key()
    if not secret:
        raise RuntimeError("Stripe key is not configured for the Operations Agent.")
    if is_live_stripe_key(secret) and not nova_live_stripe_enabled():
        raise RuntimeError("Live Stripe key detected but NOVA_STRIPE_LIVE_ENABLED is not explicitly enabled.")
    return LiveAgentStripeClient(api_key=secret)


def public_base_url() -> str:
    return (os.getenv("AMICOR_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")


def plan_payload(plan_key: str) -> dict[str, Any]:
    plan = AGENT_PLANS.get(str(plan_key or "").strip())
    if plan is None:
        raise ValueError("Unsupported Operations Agent plan")
    return dict(plan)


def checkout_payload(*, lead_id: str, email: str, plan_key: str, customer_id: str) -> dict[str, Any]:
    plan = plan_payload(plan_key)
    if plan["mode"] not in {"payment", "subscription"}:
        raise ValueError("This Operations Agent option does not require checkout")
    metadata = {
        "nova_product": AGENT_PRODUCT,
        "nova_agent_lead_id": str(lead_id),
        "nova_agent_plan": str(plan_key),
    }
    price_data: dict[str, Any] = {
        "currency": "usd",
        "unit_amount": int(plan["amount_cents"]),
        "product_data": {
            "name": f"AMICOR Nova — {plan['label']}",
            "metadata": {"nova_product": AGENT_PRODUCT, "nova_agent_plan": str(plan_key)},
        },
    }
    if plan["mode"] == "subscription":
        price_data["recurring"] = {"interval": str(plan.get("interval") or "month")}
    base = public_base_url()
    payload: dict[str, Any] = {
        "mode": plan["mode"],
        "customer": customer_id,
        "client_reference_id": str(lead_id),
        "line_items": [{"price_data": price_data, "quantity": 1}],
        "metadata": metadata,
        "success_url": f"{base}/nova/anonymous-agent?checkout=success&lead_id={lead_id}",
        "cancel_url": f"{base}/nova/anonymous-agent?checkout=cancelled&lead_id={lead_id}",
        "customer_update": {"name": "auto", "address": "auto"},
    }
    if plan["mode"] == "subscription":
        payload["subscription_data"] = {"metadata": metadata}
    else:
        payload["payment_intent_data"] = {"metadata": metadata}
    return payload


def verify_agent_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    secret = agent_webhook_secret()
    if not secret:
        raise RuntimeError("Operations Agent Stripe webhook secret is not configured.")
    if not signature:
        raise ValueError("Missing Stripe-Signature header")
    import stripe

    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise ValueError("Invalid Stripe webhook") from exc
    if isinstance(event, dict):
        return event
    rendered = getattr(event, "to_dict", lambda: {})()
    if not isinstance(rendered, dict):
        rendered = json.loads(payload.decode("utf-8"))
    return rendered
