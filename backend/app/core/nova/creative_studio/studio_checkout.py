"""AMICOR-branded Stripe Checkout for Creative Studio (TEST mode only).

Customer pays AMICOR for a 30-second Studio commercial order.
Provider/compute costs are tracked as internal operating cost — never claimed
as "all money stays internal," and never auto-purchased.

Hard rules:
- TEST Stripe keys only unless the owner explicitly enables live later
- No automatic billing until an explicit checkout is started
- No third-party vendor checkout shown to the customer
- No credit top-ups of fal/Kling/D-ID/OpenAI from this path
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

# Customer-facing AMICOR Studio commercial price (planning figure, TEST checkout).
CUSTOMER_PRICE_USD = 49.00
CUSTOMER_PRICE_MINOR = 4900
CURRENCY = "usd"
SCOPE_LABEL = "30-second AMICOR Creative Studio commercial"
RENDER_COST_CEILING_USD = 8.00  # internal planning ceiling for provider/compute

_SECRET_PATTERN = re.compile(
    r"(?i)(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+"
    r"|whsec_[A-Za-z0-9]+"
    r"|cs_(?:live|test)_[A-Za-z0-9]+"
)

_CLIENT_OVERRIDE: "StudioStripeClient | None" = None
_DEFAULT_FAKE_CLIENT: "FakeStudioStripeClient | None" = None
_ORDERS: dict[str, dict[str, Any]] = {}


class StudioStripeClient(Protocol):
    def create_checkout_session(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stripe_secret_key() -> str:
    return str(os.getenv("STRIPE_SECRET_KEY") or "").strip()


def stripe_publishable_key() -> str:
    return str(
        os.getenv("STRIPE_PUBLISHABLE_KEY")
        or os.getenv("NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY")
        or ""
    ).strip()


def is_live_stripe_key(secret: str) -> bool:
    raw = str(secret or "").strip()
    return raw.startswith("sk_live_") or raw.startswith("rk_live_")


def studio_live_stripe_enabled() -> bool:
    return str(os.getenv("NOVA_CREATIVE_STRIPE_LIVE_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def sanitize_stripe_error(message: Any, max_len: int = 240) -> str:
    text = str(message or "").replace("\n", " ").replace("\r", " ").strip()
    text = _SECRET_PATTERN.sub("[REDACTED]", text)
    if not text:
        return "unknown"
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def set_studio_stripe_override(client: StudioStripeClient | None) -> None:
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def get_studio_stripe_override() -> StudioStripeClient | None:
    return _CLIENT_OVERRIDE


def reset_studio_orders_for_tests() -> None:
    global _DEFAULT_FAKE_CLIENT
    _ORDERS.clear()
    _DEFAULT_FAKE_CLIENT = None


def stripe_runtime_mode() -> str:
    secret = stripe_secret_key()
    if _CLIENT_OVERRIDE is not None:
        return "test_fake"
    if not secret:
        return "unconfigured"
    if is_live_stripe_key(secret):
        return "live_blocked" if not studio_live_stripe_enabled() else "live"
    if secret.startswith("sk_test_"):
        return "test"
    return "unconfigured"


def checkout_readiness() -> dict[str, Any]:
    mode = stripe_runtime_mode()
    secret_present = bool(stripe_secret_key())
    publishable_present = bool(stripe_publishable_key())
    return {
        "payment_mode": mode,
        "stripe_secret_configured": secret_present,
        "stripe_publishable_configured": publishable_present,
        "real_test_checkout_available": mode == "test",
        "local_test_simulation_available": mode in {"test_fake", "unconfigured"} or not secret_present,
        "live_blocked": mode == "live_blocked",
        "message": (
            "Stripe TEST keys are configured. Customer Checkout uses AMICOR branding."
            if mode == "test"
            else (
                "Stripe TEST keys are not in this environment yet. Studio still creates "
                "AMICOR TEST-simulated checkout orders with receipts and job status for verification."
                if mode in {"test_fake", "unconfigured"}
                else f"Stripe mode is {mode}."
            )
        ),
    }


def public_pricing() -> dict[str, Any]:
    readiness = checkout_readiness()
    return {
        "product": "AMICOR Creative Studio commercial",
        "scope": SCOPE_LABEL,
        "customer_price_usd": CUSTOMER_PRICE_USD,
        "currency": CURRENCY.upper(),
        "includes": [
            "AMICOR-branded Studio checkout (customer pays AMICOR)",
            "Up to 30 seconds H.264/AAC MP4",
            "Narration, captions, and job status / receipt",
            "Internal production-cost tracking (separate from customer price)",
        ],
        "excludes": [
            "Automatic provider credit purchases",
            "Third-party vendor checkout shown to the customer",
            "Public advertising publish without owner approval",
            "Changes to the approved 60-second commercial",
        ],
        "internal_render_cost_ceiling_usd": RENDER_COST_CEILING_USD,
        "payment_mode": readiness["payment_mode"],
        "checkout_readiness": readiness,
        "auto_billing": False,
        "requires_explicit_checkout": True,
    }


class FakeStudioStripeClient:
    """In-process TEST double. Never contacts Stripe and never creates a charge."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.created_count = 0

    def create_checkout_session(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        self.created_count += 1
        session_id = f"cs_test_studio_{self.created_count}_{uuid.uuid4().hex[:8]}"
        record = {
            "id": session_id,
            "object": "checkout.session",
            "mode": "payment",
            "status": "open",
            "payment_status": "unpaid",
            "url": f"https://checkout.stripe.com/c/pay/{session_id}",
            "customer_email": payload.get("customer_email"),
            "client_reference_id": payload.get("client_reference_id"),
            "metadata": dict(payload.get("metadata") or {}),
            "amount_total": CUSTOMER_PRICE_MINOR,
            "currency": CURRENCY,
            "success_url": payload.get("success_url"),
            "cancel_url": payload.get("cancel_url"),
            "line_items": list(payload.get("line_items") or []),
        }
        self.sessions[session_id] = record
        return dict(record)

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        return dict(self.sessions.get(session_id) or {"id": session_id, "status": "expired"})

    def mark_paid(self, session_id: str) -> dict[str, Any]:
        record = self.sessions[session_id]
        record["status"] = "complete"
        record["payment_status"] = "paid"
        return dict(record)


class LiveStudioStripeClient:
    def __init__(self, *, api_key: str):
        if is_live_stripe_key(api_key) and not studio_live_stripe_enabled():
            raise ValueError("Live Stripe keys are blocked for Creative Studio checkout.")
        self.api_key = api_key

    def _build_client(self) -> Any:
        try:
            from stripe import StripeClient
        except Exception as exc:
            raise RuntimeError("Stripe SDK import is unavailable.") from exc
        return StripeClient(self.api_key)

    def create_checkout_session(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._build_client()
        created = client.v1.checkout.sessions.create(payload)
        return {
            "id": getattr(created, "id", None) or (created.get("id") if isinstance(created, dict) else None),
            "object": "checkout.session",
            "mode": getattr(created, "mode", None) or (created.get("mode") if isinstance(created, dict) else "payment"),
            "status": getattr(created, "status", None) or (created.get("status") if isinstance(created, dict) else "open"),
            "payment_status": getattr(created, "payment_status", None)
            or (created.get("payment_status") if isinstance(created, dict) else "unpaid"),
            "url": getattr(created, "url", None) or (created.get("url") if isinstance(created, dict) else None),
            "metadata": dict(getattr(created, "metadata", None) or (created.get("metadata") if isinstance(created, dict) else {}) or {}),
            "amount_total": getattr(created, "amount_total", None)
            or (created.get("amount_total") if isinstance(created, dict) else CUSTOMER_PRICE_MINOR),
            "currency": getattr(created, "currency", None) or (created.get("currency") if isinstance(created, dict) else CURRENCY),
        }

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        client = self._build_client()
        retrieved = client.v1.checkout.sessions.retrieve(str(session_id))
        if isinstance(retrieved, dict):
            return retrieved
        return {
            "id": getattr(retrieved, "id", session_id),
            "status": getattr(retrieved, "status", None),
            "payment_status": getattr(retrieved, "payment_status", None),
            "url": getattr(retrieved, "url", None),
            "metadata": dict(getattr(retrieved, "metadata", None) or {}),
            "amount_total": getattr(retrieved, "amount_total", None),
            "currency": getattr(retrieved, "currency", None),
        }


def get_studio_stripe_client() -> StudioStripeClient:
    global _DEFAULT_FAKE_CLIENT
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    secret = stripe_secret_key()
    if not secret:
        # Singleton local/test client so create + complete-test share session state
        # when Stripe TEST secrets are not yet configured in the environment.
        if _DEFAULT_FAKE_CLIENT is None:
            _DEFAULT_FAKE_CLIENT = FakeStudioStripeClient()
        return _DEFAULT_FAKE_CLIENT
    if is_live_stripe_key(secret) and not studio_live_stripe_enabled():
        raise ValueError("Live Stripe keys are not allowed for Creative Studio. Use a TEST key.")
    return LiveStudioStripeClient(api_key=secret)


def _order_id() -> str:
    return f"cso_{uuid.uuid4().hex[:12]}"


def create_studio_checkout_order(
    *,
    owner_id: str,
    project_id: str,
    customer_email: str | None = None,
    success_url: str,
    cancel_url: str,
    estimated_render_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Start AMICOR Stripe Checkout in TEST mode for one 30s commercial order."""
    mode = stripe_runtime_mode()
    if mode == "live_blocked":
        raise ValueError("Live Stripe is blocked for Creative Studio until owner enables it.")
    if mode == "live":
        raise ValueError("Creative Studio checkout is TEST-only in this release.")

    client = get_studio_stripe_client()
    order_id = _order_id()
    render_cost = float(estimated_render_cost_usd) if estimated_render_cost_usd is not None else RENDER_COST_CEILING_USD
    if render_cost > RENDER_COST_CEILING_USD:
        raise ValueError(
            f"Estimated render cost ${render_cost:.2f} exceeds the ${RENDER_COST_CEILING_USD:.2f} ceiling. "
            "Owner approval required before raising the ceiling."
        )

    metadata = {
        "amicor_product": "nova_creative_studio",
        "order_id": order_id,
        "project_id": str(project_id),
        "owner_id": str(owner_id),
        "scope": SCOPE_LABEL,
        "customer_price_usd": f"{CUSTOMER_PRICE_USD:.2f}",
        "internal_render_cost_ceiling_usd": f"{RENDER_COST_CEILING_USD:.2f}",
        "estimated_render_cost_usd": f"{render_cost:.2f}",
    }
    payload: dict[str, Any] = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": order_id,
        "metadata": metadata,
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": CURRENCY,
                    "unit_amount": CUSTOMER_PRICE_MINOR,
                    "product_data": {
                        "name": "AMICOR Creative Studio — 30s commercial",
                        "description": (
                            "Customer pays AMICOR. Includes Studio production job status, "
                            "receipt, and downloadable MP4 when rendering completes."
                        ),
                    },
                },
            }
        ],
    }
    if customer_email:
        payload["customer_email"] = customer_email

    try:
        session = client.create_checkout_session(payload=payload)
    except Exception as exc:
        raise RuntimeError(f"Stripe checkout unavailable: {sanitize_stripe_error(exc)}") from exc

    order = {
        "id": order_id,
        "owner_id": owner_id,
        "project_id": project_id,
        "status": "checkout_open",
        "payment_status": session.get("payment_status") or "unpaid",
        "customer_price_usd": CUSTOMER_PRICE_USD,
        "currency": CURRENCY.upper(),
        "scope": SCOPE_LABEL,
        "stripe_checkout_session_id": session.get("id"),
        "checkout_url": session.get("url"),
        "payment_mode": mode if mode != "unconfigured" else "test_fake",
        "branded_as": "AMICOR",
        "third_party_checkout_shown": False,
        "auto_billing": False,
        "receipt": None,
        "production_cost": {
            "estimated_render_cost_usd": round(render_cost, 4),
            "ceiling_usd": RENDER_COST_CEILING_USD,
            "actual_render_cost_usd": None,
            "paid_provider_charges": False,
            "note": (
                "Internal operating estimate only. Customer price is separate. "
                "No provider credits are purchased from this checkout."
            ),
        },
        "job_status": "awaiting_payment",
        "created_at": _now(),
        "updated_at": _now(),
        "pricing": public_pricing(),
    }
    _ORDERS[order_id] = order
    return {
        "order": order,
        "checkout": {
            "id": session.get("id"),
            "url": session.get("url"),
            "status": session.get("status"),
            "payment_status": session.get("payment_status"),
            "amount_total_minor": session.get("amount_total") or CUSTOMER_PRICE_MINOR,
            "currency": CURRENCY,
            "branded_as": "AMICOR",
        },
        "message": "AMICOR Stripe Checkout session created in TEST mode. No live charge.",
    }


def get_studio_order(order_id: str, *, owner_id: str) -> dict[str, Any] | None:
    order = _ORDERS.get(order_id)
    if order is None or order.get("owner_id") != owner_id:
        return None
    return dict(order)


def list_studio_orders(*, owner_id: str, project_id: str | None = None) -> list[dict[str, Any]]:
    rows = [dict(order) for order in _ORDERS.values() if order.get("owner_id") == owner_id]
    if project_id:
        rows = [order for order in rows if order.get("project_id") == project_id]
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows


def sync_studio_order_from_stripe(order_id: str, *, owner_id: str) -> dict[str, Any]:
    order = get_studio_order(order_id, owner_id=owner_id)
    if order is None:
        raise KeyError("order_not_found")
    session_id = str(order.get("stripe_checkout_session_id") or "")
    if not session_id:
        raise ValueError("Order has no Stripe checkout session.")
    client = get_studio_stripe_client()
    session = client.retrieve_checkout_session(session_id)
    payment_status = str(session.get("payment_status") or order.get("payment_status") or "unpaid")
    status = str(session.get("status") or "open")
    order["payment_status"] = payment_status
    order["updated_at"] = _now()
    if payment_status == "paid" or status == "complete":
        order["status"] = "paid"
        order["job_status"] = "queued_for_production"
        order["receipt"] = {
            "receipt_id": f"rcpt_{order_id}",
            "paid_at": _now(),
            "customer_price_usd": order["customer_price_usd"],
            "currency": order["currency"],
            "scope": order["scope"],
            "stripe_checkout_session_id": session_id,
            "payment_mode": order["payment_mode"],
            "line_items": [
                {
                    "description": SCOPE_LABEL,
                    "amount_usd": order["customer_price_usd"],
                }
            ],
            "production_cost_summary": order["production_cost"],
            "note": "TEST-mode receipt. Not a live charge unless a real TEST card completed checkout.",
        }
    elif status == "expired":
        order["status"] = "expired"
        order["job_status"] = "cancelled"
    else:
        order["status"] = "checkout_open"
        order["job_status"] = "awaiting_payment"
    _ORDERS[order_id] = order
    return dict(order)


def record_production_cost(
    order_id: str,
    *,
    owner_id: str,
    actual_render_cost_usd: float,
    paid_provider_charges: bool = False,
    note: str = "",
) -> dict[str, Any]:
    order = get_studio_order(order_id, owner_id=owner_id)
    if order is None:
        raise KeyError("order_not_found")
    cost = dict(order.get("production_cost") or {})
    cost["actual_render_cost_usd"] = round(float(actual_render_cost_usd), 4)
    cost["paid_provider_charges"] = bool(paid_provider_charges)
    if note:
        cost["note"] = str(note)[:500]
    order["production_cost"] = cost
    order["updated_at"] = _now()
    if order.get("receipt"):
        receipt = dict(order["receipt"])
        receipt["production_cost_summary"] = cost
        order["receipt"] = receipt
    _ORDERS[order_id] = order
    return dict(order)


def mark_order_job_status(order_id: str, *, owner_id: str, job_status: str) -> dict[str, Any]:
    order = get_studio_order(order_id, owner_id=owner_id)
    if order is None:
        raise KeyError("order_not_found")
    order["job_status"] = str(job_status)
    order["updated_at"] = _now()
    _ORDERS[order_id] = order
    return dict(order)


def complete_test_checkout(order_id: str, *, owner_id: str) -> dict[str, Any]:
    """Mark a TEST/fake checkout paid so receipts and job status can be verified without a card.

    Only allowed when payment_mode is test_fake or test. Never creates a live charge.
    """
    order = get_studio_order(order_id, owner_id=owner_id)
    if order is None:
        raise KeyError("order_not_found")
    mode = str(order.get("payment_mode") or stripe_runtime_mode())
    if mode not in {"test", "test_fake"}:
        raise ValueError("TEST checkout completion is only available in Stripe TEST mode.")
    client = get_studio_stripe_client()
    session_id = str(order.get("stripe_checkout_session_id") or "")
    if isinstance(client, FakeStudioStripeClient) and session_id:
        client.mark_paid(session_id)
    elif mode == "test" and session_id:
        # Real Stripe TEST sessions must be paid with a test card in Checkout UI.
        # Sync whatever Stripe currently reports instead of forging payment.
        return sync_studio_order_from_stripe(order_id, owner_id=owner_id)
    return sync_studio_order_from_stripe(order_id, owner_id=owner_id)
