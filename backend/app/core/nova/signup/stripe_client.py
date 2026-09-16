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


def stripe_phase_duration(phase: dict[str, Any]) -> dict[str, Any] | None:
    """Stripe Basil+ rejected phases.iterations. Founding uses duration months instead."""
    duration = phase.get("duration") if isinstance(phase.get("duration"), dict) else None
    if duration and duration.get("interval_count"):
        return {
            "interval": str(duration.get("interval") or INTERVAL),
            "interval_count": int(duration["interval_count"]),
        }
    if phase.get("iterations"):
        return {"interval": INTERVAL, "interval_count": int(phase["iterations"])}
    return None


def build_stripe_schedule_phases(
    plan: dict[str, Any],
    *,
    catalog: dict[str, str],
    start_date: Any = None,
    trial_end: Any = None,
) -> list[dict[str, Any]]:
    """Stripe schedule update payload. Never sends phases.iterations."""
    phases: list[dict[str, Any]] = []
    for index, phase in enumerate(plan.get("phases") or []):
        lookup = str(phase.get("price_lookup") or "")
        item: dict[str, Any] = {
            "items": [{"price": catalog[lookup], "quantity": 1}],
        }
        if index == 0 and start_date is not None:
            item["start_date"] = start_date
        duration = stripe_phase_duration(phase if isinstance(phase, dict) else {})
        if duration is not None:
            item["duration"] = duration
        if index == 0 and trial_end:
            item["trial_end"] = trial_end
        phases.append(item)
    return phases


def schedule_id_from_subscription(subscription: dict[str, Any] | None) -> str | None:
    raw = (subscription or {}).get("schedule")
    if isinstance(raw, dict):
        value = raw.get("id")
        return str(value) if value else None
    if raw:
        return str(raw)
    return None


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
        self.subscription_schedules: dict[str, str] = {}
        self.created_count = 0
        self.schedule_create_calls = 0
        self.schedule_update_calls = 0
        self.fail_next_update = False
        self.last_stripe_phases: list[dict[str, Any]] = []
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

    def attach_partial_schedule(self, subscription_id: str) -> dict[str, Any]:
        existing_id = self.subscription_schedules.get(subscription_id)
        if existing_id:
            return dict(self._schedule_by_id(existing_id) or {"id": existing_id, "subscription": subscription_id})
        schedule = {
            "id": f"sub_sched_test_{uuid4()[:10]}",
            "subscription": subscription_id,
            "plan": {},
            "phases": [],
            "stripe_phases": [],
            "partial": True,
        }
        self.schedules.append(schedule)
        self.subscription_schedules[subscription_id] = str(schedule["id"])
        return dict(schedule)

    def _schedule_by_id(self, schedule_id: str) -> dict[str, Any] | None:
        for item in self.schedules:
            if item.get("id") == schedule_id:
                return item
        return None

    def apply_subscription_schedule(self, *, subscription_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        stripe_phases = build_stripe_schedule_phases(plan, catalog=self.prices)
        existing_id = self.subscription_schedules.get(subscription_id)
        if existing_id:
            self.schedule_update_calls += 1
            if self.fail_next_update:
                self.fail_next_update = False
                raise RuntimeError("Received unknown parameter: phases[iterations]")
            schedule = self._schedule_by_id(existing_id) or {
                "id": existing_id,
                "subscription": subscription_id,
            }
            schedule["plan"] = plan
            schedule["phases"] = list(plan.get("phases") or [])
            schedule["stripe_phases"] = stripe_phases
            schedule["partial"] = False
            self.last_stripe_phases = stripe_phases
            return dict(schedule)
        self.schedule_create_calls += 1
        schedule = {
            "id": f"sub_sched_test_{uuid4()[:10]}",
            "subscription": subscription_id,
            "plan": plan,
            "phases": list(plan.get("phases") or []),
            "stripe_phases": stripe_phases,
            "partial": False,
        }
        self.schedules.append(schedule)
        self.subscription_schedules[subscription_id] = str(schedule["id"])
        self.last_stripe_phases = stripe_phases
        if self.fail_next_update:
            self.fail_next_update = False
            raise RuntimeError("Received unknown parameter: phases[iterations]")
        return dict(schedule)


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
            "schedule": getattr(created, "schedule", None),
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
        subscription = self._as_dict(client.v1.subscriptions.retrieve(str(subscription_id)))
        schedule_id = schedule_id_from_subscription(subscription)
        if schedule_id:
            current = self._as_dict(client.v1.subscription_schedules.retrieve(str(schedule_id)))
        else:
            created = client.v1.subscription_schedules.create({"from_subscription": subscription_id})
            current = self._as_dict(created)
            schedule_id = str(current.get("id") or "") or None
        phases_in = current.get("phases") if isinstance(current, dict) else None
        start_date = None
        trial_end = None
        if phases_in:
            first = phases_in[0] if isinstance(phases_in[0], dict) else {}
            start_date = first.get("start_date")
            trial_end = first.get("trial_end")
        phases = build_stripe_schedule_phases(
            plan,
            catalog=catalog,
            start_date=start_date,
            trial_end=trial_end,
        )
        updated = client.v1.subscription_schedules.update(str(schedule_id), {"phases": phases})
        payload = self._as_dict(updated)
        payload["plan"] = plan
        return payload
