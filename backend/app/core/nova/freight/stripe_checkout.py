"""Nova freight Stripe TEST PaymentIntent client. Separate from Delivery checkout."""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Protocol

from app.helpers import uuid4

logger = logging.getLogger("amicor.nova.freight.stripe")

STRIPE_HTTP_TIMEOUT_SECONDS = 15.0
_SECRET_PATTERN = re.compile(
    r"(?i)(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+"
    r"|whsec_[A-Za-z0-9]+"
    r"|pi_[A-Za-z0-9]+_secret[_A-Za-z0-9]*"
)

_CLIENT_OVERRIDE: "NovaFreightStripeClient | None" = None


class NovaFreightStripeClient(Protocol):
    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        ...

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        ...


def stripe_secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def stripe_publishable_key() -> str:
    return os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()


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


def set_nova_freight_stripe_override(client: NovaFreightStripeClient | None) -> None:
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def get_nova_freight_stripe_override() -> NovaFreightStripeClient | None:
    return _CLIENT_OVERRIDE


def get_nova_freight_stripe_client() -> NovaFreightStripeClient:
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    secret = stripe_secret_key()
    if not secret:
        raise ValueError("Stripe TEST key is not configured for Nova freight.")
    if is_live_stripe_key(secret):
        raise ValueError("Live Stripe keys are not allowed for Nova freight. Use a TEST key.")
    return LiveNovaFreightStripeClient(api_key=secret)


class LiveNovaFreightStripeClient:
    def __init__(self, *, api_key: str):
        if is_live_stripe_key(api_key):
            raise ValueError("Live Stripe keys are not allowed for Nova freight. Use a TEST key.")
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
        raise RuntimeError(
            f"Stripe HTTP client unavailable: {sanitize_stripe_error(last_exc)}"
        )

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        client = self._build_client()
        created = client.v1.payment_intents.create(
            {
                "amount": int(amount_minor),
                "currency": currency.lower(),
                "automatic_payment_methods": {"enabled": True},
                "metadata": metadata,
            },
            {"idempotency_key": idempotency_key},
        )
        return _as_intent(created)

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        client = self._build_client()
        retrieved = client.v1.payment_intents.retrieve(str(payment_intent_id))
        return _as_intent(retrieved)


class FakeNovaFreightStripeClient:
    def __init__(self) -> None:
        self.created_count = 0
        self.intents: dict[str, dict[str, Any]] = {}

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        for existing in self.intents.values():
            if existing.get("idempotency_key") == idempotency_key:
                return existing
        self.created_count += 1
        intent_id = f"pi_nf_test_{self.created_count}_{uuid4()[:10]}"
        payload = {
            "id": intent_id,
            "client_secret": f"{intent_id}_secret_test",
            "status": "requires_payment_method",
            "amount": int(amount_minor),
            "currency": currency.lower(),
            "metadata": dict(metadata),
            "idempotency_key": idempotency_key,
        }
        self.intents[intent_id] = payload
        return payload

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        return dict(self.intents.get(payment_intent_id) or {"id": payment_intent_id, "status": "requires_payment_method"})

    def succeed(self, payment_intent_id: str) -> dict[str, Any]:
        payload = self.retrieve_payment_intent(payment_intent_id)
        payload["status"] = "succeeded"
        payload["amount_received"] = payload.get("amount")
        self.intents[payment_intent_id] = payload
        return payload

    def fail(self, payment_intent_id: str, reason: str = "card_declined") -> dict[str, Any]:
        payload = self.retrieve_payment_intent(payment_intent_id)
        payload["status"] = "requires_payment_method"
        payload["last_payment_error"] = {"code": reason, "message": "TEST card was declined"}
        self.intents[payment_intent_id] = payload
        return payload


def _as_intent(created: Any) -> dict[str, Any]:
    payload = created if isinstance(created, dict) else getattr(created, "to_dict", lambda: {})()
    if isinstance(payload, dict) and payload.get("id"):
        return payload
    return {
        "id": getattr(created, "id", None),
        "client_secret": getattr(created, "client_secret", None),
        "status": getattr(created, "status", None),
        "amount": getattr(created, "amount", None),
        "currency": getattr(created, "currency", None),
        "metadata": getattr(created, "metadata", {}) or {},
    }
