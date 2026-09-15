"""Dedicated AMICOR Nova SaaS Stripe TEST client. Not Health, Freight, or Delivery billing."""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Protocol

from app.core.nova.signup.offer import (
    CURRENCY,
    FOUNDING_PRICE_LOOKUP,
    FOUNDING_PRODUCT_NAME,
    FOUNDING_UNIT_AMOUNT,
    INTERVAL,
    PRODUCT_METADATA,
    STANDARD_PRICE_LOOKUP,
    STANDARD_PRODUCT_NAME,
    STANDARD_UNIT_AMOUNT,
    billing_plan,
)
from app.helpers import uuid4

logger = logging.getLogger("amicor.nova.signup.stripe")

STRIPE_HTTP_TIMEOUT_SECONDS = 15.0
_SECRET_PATTERN = re.compile(
    r"(?i)(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+"
    r"|whsec_[A-Za-z0-9]+"
    r"|cs_[A-Za-z0-9]+"
    r"|sub_[A-Za-z0-9]+"
)

_CLIENT_OVERRIDE: "NovaSaasStripeClient | None" = None


class NovaSaasStripeClient(Protocol):
    def create_checkout_session(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        ...

    def apply_subscription_schedule(self, *, subscription_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        ...

    def publishable_key(self) -> str:
        ...


def stripe_secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def stripe_publishable_key() -> str:
    return os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()


def nova_saas_webhook_secret() -> str:
    return (os.getenv("STRIPE_NOVA_SAAS_WEBHOOK_SECRET") or "").strip()


def is_live_stripe_key(secret: str) -> bool:
    raw = str(secret or "").strip()
    return raw.startswith("sk_live_") or raw.startswith("rk_live_")


def sanitize_stripe_error(message: Any, max_len: int = 240) -> str:
    text = str(message or "").replace("\n", " ").replace("\r", " ").strip()
    text = _SECRET_PATTERN.sub("[REDACTED]", text)
    if not text:
        return "unknown"
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def set_nova_saas_stripe_override(client: NovaSaasStripeClient | None) -> None:
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def get_nova_saas_stripe_override() -> NovaSaasStripeClient | None:
    return _CLIENT_OVERRIDE


def get_nova_saas_stripe_client() -> NovaSaasStripeClient:
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    secret = stripe_secret_key()
    if not secret:
        raise ValueError("Stripe TEST key is not configured for Nova SaaS signup.")
    if is_live_stripe_key(secret):
        raise ValueError("Live Stripe keys are not allowed for Nova SaaS signup. Use a TEST key.")
    return LiveNovaSaasStripeClient(api_key=secret)


class FakeNovaSaasStripeClient:
    """In-process TEST double. Never contacts Stripe and never creates a charge."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.schedules: list[dict[str, Any]] = []
        self.created_count = 0
        self.prices = {
            FOUNDING_PRICE_LOOKUP: "price_nova_founding_test",
            STANDARD_PRICE_LOOKUP: "price_nova_standard_test",
        }

    def publishable_key(self) -> str:
        return "pk_test_nova_saas_fake"

    def create_checkout_session(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        self.created_count += 1
        session_id = f"cs_test_nova_{self.created_count}_{uuid4()[:8]}"
        subscription_id = f"sub_test_nova_{self.created_count}_{uuid4()[:8]}"
        customer_id = str(payload.get("customer") or f"cus_test_nova_{self.created_count}")
        record = {
            "id": session_id,
            "object": "checkout.session",
            "mode": "subscription",
            "status": "open",
            "payment_status": "unpaid",
            "url": f"https://checkout.stripe.com/c/pay/{session_id}",
            "customer": customer_id,
            "subscription": None,
            "client_reference_id": payload.get("client_reference_id"),
            "metadata": dict(payload.get("metadata") or {}),
            "subscription_data": dict(payload.get("subscription_data") or {}),
            "line_items": list(payload.get("line_items") or []),
            "success_url": payload.get("success_url"),
            "cancel_url": payload.get("cancel_url"),
            "pending_subscription_id": subscription_id,
        }
        self.sessions[session_id] = record
        return dict(record)

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        return dict(self.sessions.get(session_id) or {"id": session_id, "status": "expired"})

    def complete_session(self, session_id: str, *, payment_status: str = "no_payment_required") -> dict[str, Any]:
        record = self.sessions[session_id]
        record["status"] = "complete"
        record["payment_status"] = payment_status
        if payment_status in {"paid", "no_payment_required"}:
            record["subscription"] = record.get("pending_subscription_id")
        else:
            record["subscription"] = None
        return dict(record)

    def apply_subscription_schedule(self, *, subscription_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        schedule = {
            "id": f"sub_sched_test_{uuid4()[:10]}",
            "subscription": subscription_id,
            "plan": plan,
            "phases": list(plan.get("phases") or []),
        }
        self.schedules.append(schedule)
        return schedule


class LiveNovaSaasStripeClient:
    def __init__(self, *, api_key: str):
        if is_live_stripe_key(api_key):
            raise ValueError("Live Stripe keys are not allowed for Nova SaaS signup. Use a TEST key.")
        self.api_key = api_key
        self._price_ids: dict[str, str] = {}

    def publishable_key(self) -> str:
        key = stripe_publishable_key()
        if key.startswith("pk_live_"):
            raise ValueError("Live Stripe publishable keys are not allowed for Nova SaaS signup.")
        return key

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
            "status": getattr(created, "status", None),
            "payment_status": getattr(created, "payment_status", None),
            "customer": getattr(created, "customer", None),
            "subscription": getattr(created, "subscription", None),
            "metadata": getattr(created, "metadata", {}) or {},
        }

    def _ensure_price(self, client: Any, *, lookup_key: str, product_name: str, unit_amount: int) -> str:
        if lookup_key in self._price_ids:
            return self._price_ids[lookup_key]
        listed = client.v1.prices.list({"lookup_keys": [lookup_key], "limit": 1})
        data = listed.get("data") if isinstance(listed, dict) else getattr(listed, "data", None)
        if data:
            price_id = data[0]["id"] if isinstance(data[0], dict) else getattr(data[0], "id", None)
            if price_id:
                self._price_ids[lookup_key] = str(price_id)
                return str(price_id)
        product = client.v1.products.create(
            {
                "name": product_name,
                "metadata": dict(PRODUCT_METADATA),
            }
        )
        product_id = product["id"] if isinstance(product, dict) else getattr(product, "id", None)
        price = client.v1.prices.create(
            {
                "product": product_id,
                "currency": CURRENCY,
                "unit_amount": int(unit_amount),
                "recurring": {"interval": INTERVAL},
                "lookup_key": lookup_key,
                "metadata": dict(PRODUCT_METADATA),
            }
        )
        price_id = price["id"] if isinstance(price, dict) else getattr(price, "id", None)
        self._price_ids[lookup_key] = str(price_id)
        return str(price_id)

    def catalog(self, client: Any) -> dict[str, str]:
        return {
            FOUNDING_PRICE_LOOKUP: self._ensure_price(
                client,
                lookup_key=FOUNDING_PRICE_LOOKUP,
                product_name=FOUNDING_PRODUCT_NAME,
                unit_amount=FOUNDING_UNIT_AMOUNT,
            ),
            STANDARD_PRICE_LOOKUP: self._ensure_price(
                client,
                lookup_key=STANDARD_PRICE_LOOKUP,
                product_name=STANDARD_PRODUCT_NAME,
                unit_amount=STANDARD_UNIT_AMOUNT,
            ),
        }

    def create_checkout_session(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._build_client()
        catalog = self.catalog(client)
        plan = billing_plan(founding_eligible=str(payload.get("metadata", {}).get("nova_tier")) == "founding")
        first_price = catalog[str(plan["phases"][0]["price_lookup"])]
        params: dict[str, Any] = {
            "mode": "subscription",
            "success_url": payload["success_url"],
            "cancel_url": payload["cancel_url"],
            "client_reference_id": payload["client_reference_id"],
            "metadata": dict(payload.get("metadata") or {}),
            "line_items": [{"price": first_price, "quantity": 1}],
            "subscription_data": dict(payload.get("subscription_data") or {}),
        }
        if payload.get("customer_email"):
            params["customer_email"] = payload["customer_email"]
        created = client.v1.checkout.sessions.create(params)
        return self._as_dict(created)

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        client = self._build_client()
        return self._as_dict(client.v1.checkout.sessions.retrieve(str(session_id)))

    def apply_subscription_schedule(self, *, subscription_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        client = self._build_client()
        catalog = self.catalog(client)
        created = client.v1.subscription_schedules.create({"from_subscription": subscription_id})
        schedule_id = created["id"] if isinstance(created, dict) else getattr(created, "id", None)
        current = created if isinstance(created, dict) else getattr(created, "to_dict", lambda: {})()
        phases_in = current.get("phases") if isinstance(current, dict) else None
        start_date = None
        trial_end = None
        if phases_in:
            first = phases_in[0] if isinstance(phases_in[0], dict) else {}
            start_date = first.get("start_date")
            trial_end = first.get("trial_end")
        phases: list[dict[str, Any]] = []
        for index, phase in enumerate(plan.get("phases") or []):
            item = {
                "items": [{"price": catalog[str(phase["price_lookup"])], "quantity": 1}],
            }
            if index == 0 and start_date is not None:
                item["start_date"] = start_date
            if phase.get("iterations"):
                item["iterations"] = int(phase["iterations"])
            if index == 0 and trial_end:
                item["trial_end"] = trial_end
            phases.append(item)
        updated = client.v1.subscription_schedules.update(str(schedule_id), {"phases": phases})
        payload = self._as_dict(updated)
        payload["plan"] = plan
        return payload
