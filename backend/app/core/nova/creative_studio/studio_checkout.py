"""AMICOR-branded Stripe Checkout for Creative Studio.

Customer pays AMICOR for a 30-second Studio commercial order.
Provider/compute costs are tracked as internal operating cost — never claimed
as "all money stays internal," and never auto-purchased.

Hard rules:
- TEST Stripe keys by default; LIVE only when NOVA_CREATIVE_STRIPE_LIVE_ENABLED is on
- No automatic billing until an explicit checkout is started
- No third-party vendor checkout shown to the customer
- No credit top-ups of fal/Kling/D-ID/OpenAI from this path
- Orders are durable (DB) so paid revenue survives process restart
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

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
_WEBHOOK_EVENTS: dict[str, dict[str, Any]] = {}


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


def studio_webhook_secret() -> str:
    return str(
        os.getenv("STRIPE_NOVA_CREATIVE_WEBHOOK_SECRET")
        or os.getenv("STRIPE_WEBHOOK_SECRET")
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
    _WEBHOOK_EVENTS.clear()
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
    webhook_present = bool(studio_webhook_secret())
    live_enabled = studio_live_stripe_enabled()
    return {
        "payment_mode": mode,
        "stripe_secret_configured": secret_present,
        "stripe_publishable_configured": publishable_present,
        "stripe_webhook_configured": webhook_present,
        "real_test_checkout_available": mode == "test",
        "local_test_simulation_available": mode in {"test_fake", "unconfigured"} or not secret_present,
        "live_blocked": mode == "live_blocked",
        "live_checkout_available": mode == "live" and live_enabled,
        "live_flag_enabled": live_enabled,
        "durable_orders": True,
        "message": (
            "Stripe LIVE keys are configured and NOVA_CREATIVE_STRIPE_LIVE_ENABLED is on. "
            "Customer Checkout uses AMICOR branding for real charges."
            if mode == "live"
            else (
                "Stripe TEST keys are configured. Customer Checkout uses AMICOR branding."
                if mode == "test"
                else (
                    "Stripe LIVE keys are present but blocked until NOVA_CREATIVE_STRIPE_LIVE_ENABLED=true."
                    if mode == "live_blocked"
                    else (
                        "Stripe TEST keys are not in this environment yet. Studio still creates "
                        "AMICOR TEST-simulated checkout orders with receipts and job status for verification."
                        if mode in {"test_fake", "unconfigured"}
                        else f"Stripe mode is {mode}."
                    )
                )
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


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _open_db() -> Session | None:
    try:
        from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
        from app.db.session import SessionLocal

        ensure_nova_creative_schema()
        return SessionLocal()
    except Exception:
        return None


def _order_from_orm(orm: Any) -> dict[str, Any]:
    receipt = _loads(getattr(orm, "receipt_json", None), None)
    production_cost = _loads(getattr(orm, "production_cost_json", None), {})
    fulfillment = _loads(getattr(orm, "fulfillment_json", None), {})
    meta = _loads(getattr(orm, "metadata_json", None), {})
    return {
        "id": orm.id,
        "owner_id": orm.owner_id,
        "project_id": orm.project_id,
        "status": orm.status,
        "payment_status": orm.payment_status,
        "customer_price_usd": float(orm.customer_price_usd or CUSTOMER_PRICE_USD),
        "currency": orm.currency or CURRENCY.upper(),
        "scope": orm.scope or SCOPE_LABEL,
        "customer_email": orm.customer_email or "",
        "stripe_checkout_session_id": orm.stripe_checkout_session_id,
        "stripe_payment_intent_id": orm.stripe_payment_intent_id,
        "checkout_url": orm.checkout_url,
        "payment_mode": orm.payment_mode,
        "branded_as": "AMICOR",
        "third_party_checkout_shown": False,
        "auto_billing": False,
        "receipt": receipt,
        "production_cost": production_cost,
        "fulfillment": fulfillment,
        "job_status": orm.job_status,
        "created_at": orm.created_at,
        "updated_at": orm.updated_at,
        "pricing": meta.get("pricing") or public_pricing(),
        "durable": True,
    }


def _save_order_durable(order: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
    """Persist order to in-memory cache and DB when available."""
    order_id = str(order["id"])
    _ORDERS[order_id] = dict(order)

    owns_session = False
    session = db
    if session is None:
        session = _open_db()
        owns_session = session is not None
    if session is None:
        order = dict(order)
        order["durable"] = False
        _ORDERS[order_id] = order
        return dict(order)

    try:
        from app.core.nova.creative_studio.db_models import NovaCreativeOrder

        orm = session.get(NovaCreativeOrder, order_id)
        if orm is None:
            orm = NovaCreativeOrder(id=order_id, owner_id=order["owner_id"], project_id=order["project_id"])
            session.add(orm)
        orm.owner_id = str(order["owner_id"])
        orm.project_id = str(order["project_id"])
        orm.status = str(order.get("status") or "checkout_open")
        orm.payment_status = str(order.get("payment_status") or "unpaid")
        orm.job_status = str(order.get("job_status") or "awaiting_payment")
        orm.payment_mode = str(order.get("payment_mode") or "test_fake")
        orm.customer_price_usd = float(order.get("customer_price_usd") or CUSTOMER_PRICE_USD)
        orm.currency = str(order.get("currency") or CURRENCY.upper())
        orm.scope = str(order.get("scope") or SCOPE_LABEL)
        orm.customer_email = str(order.get("customer_email") or "")
        orm.stripe_checkout_session_id = order.get("stripe_checkout_session_id")
        orm.stripe_payment_intent_id = order.get("stripe_payment_intent_id")
        orm.checkout_url = order.get("checkout_url")
        orm.production_cost_json = _dumps(order.get("production_cost") or {})
        orm.receipt_json = _dumps(order.get("receipt"))
        orm.fulfillment_json = _dumps(order.get("fulfillment") or {})
        orm.metadata_json = _dumps({"pricing": order.get("pricing") or public_pricing()})
        orm.created_at = str(order.get("created_at") or _now())
        orm.updated_at = str(order.get("updated_at") or _now())
        session.commit()
        order = dict(order)
        order["durable"] = True
        _ORDERS[order_id] = order
        return dict(order)
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        order = dict(order)
        order["durable"] = False
        _ORDERS[order_id] = order
        return dict(order)
    finally:
        if owns_session and session is not None:
            session.close()


def _load_order(order_id: str, *, owner_id: str | None = None, db: Session | None = None) -> dict[str, Any] | None:
    cached = _ORDERS.get(order_id)
    if cached is not None:
        if owner_id is not None and cached.get("owner_id") != owner_id:
            return None
        return dict(cached)

    owns_session = False
    session = db
    if session is None:
        session = _open_db()
        owns_session = session is not None
    if session is None:
        return None
    try:
        from app.core.nova.creative_studio.db_models import NovaCreativeOrder

        orm = session.get(NovaCreativeOrder, order_id)
        if orm is None:
            return None
        if owner_id is not None and orm.owner_id != owner_id:
            return None
        order = _order_from_orm(orm)
        _ORDERS[order_id] = order
        return dict(order)
    except Exception:
        return None
    finally:
        if owns_session and session is not None:
            session.close()


def _list_orders_durable(*, owner_id: str, project_id: str | None = None, db: Session | None = None) -> list[dict[str, Any]]:
    rows = [dict(order) for order in _ORDERS.values() if order.get("owner_id") == owner_id]
    if project_id:
        rows = [order for order in rows if order.get("project_id") == project_id]
    known_ids = {str(order.get("id")) for order in rows}

    owns_session = False
    session = db
    if session is None:
        session = _open_db()
        owns_session = session is not None
    if session is not None:
        try:
            from app.core.nova.creative_studio.db_models import NovaCreativeOrder

            query = session.query(NovaCreativeOrder).filter(NovaCreativeOrder.owner_id == owner_id)
            if project_id:
                query = query.filter(NovaCreativeOrder.project_id == project_id)
            for orm in query.all():
                if orm.id in known_ids:
                    continue
                order = _order_from_orm(orm)
                _ORDERS[orm.id] = order
                rows.append(order)
                known_ids.add(orm.id)
        except Exception:
            pass
        finally:
            if owns_session:
                session.close()

    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows


def _build_receipt(order: dict[str, Any], *, session_id: str, live: bool = False) -> dict[str, Any]:
    return {
        "receipt_id": f"rcpt_{order['id']}",
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
        "production_cost_summary": order.get("production_cost"),
        "note": (
            "LIVE receipt. Customer paid AMICOR via Stripe Checkout."
            if live
            else "TEST-mode receipt. Not a live charge unless a real TEST card completed checkout."
        ),
    }


def fulfill_paid_order(order: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
    """Mark a paid order ready for local walking-commercial production.

    Does not activate fal/Kling/D-ID or purchase provider credits.
    Links an existing 30s walking commercial asset when already rendered.
    """
    fulfillment = dict(order.get("fulfillment") or {})
    if fulfillment.get("fulfilled_at") and order.get("job_status") in {
        "queued_for_production",
        "ready_for_download",
        "fulfilled",
    }:
        return dict(order)

    linked_asset_id = None
    linked_download_url = None
    try:
        from app.core.nova.creative_studio.store import get_store

        store = get_store(db)
        assets = store.list_assets(str(order["project_id"]), str(order["owner_id"]))
        for asset in assets:
            meta = getattr(asset, "metadata", None) or {}
            if not isinstance(meta, dict):
                meta = {}
            render_mode = str(meta.get("render_mode") or "")
            milestone = str(meta.get("milestone") or "")
            if asset.kind == "video" and (
                render_mode == "local_walking_commercial_30s"
                or milestone == "30s_walking_commercial"
                or meta.get("final_promo") is True
            ):
                linked_asset_id = asset.id
                linked_download_url = (
                    f"/api/nova/creative/projects/{order['project_id']}/assets/{asset.id}/file"
                )
                break
    except Exception:
        linked_asset_id = None
        linked_download_url = None

    fulfillment.update(
        {
            "fulfilled_at": _now(),
            "production_path": "local_walking_commercial_30s",
            "paid_providers_activated": False,
            "fal_kling_did_unchanged": True,
            "approved_60s_commercial_unchanged": True,
            "ready_for_render": linked_asset_id is None,
            "ready_for_download": linked_asset_id is not None,
            "linked_asset_id": linked_asset_id,
            "download_url": linked_download_url,
            "note": (
                "Payment confirmed. Existing 30s walking commercial is linked for download."
                if linked_asset_id
                else (
                    "Payment confirmed. Order queued for local 30s walking commercial production. "
                    "No paid Genova/FAL/Kling/D-ID credits purchased."
                )
            ),
        }
    )
    order["fulfillment"] = fulfillment
    order["job_status"] = "ready_for_download" if linked_asset_id else "queued_for_production"
    order["updated_at"] = _now()
    return _save_order_durable(order, db=db)


def create_studio_checkout_order(
    *,
    owner_id: str,
    project_id: str,
    customer_email: str | None = None,
    success_url: str,
    cancel_url: str,
    estimated_render_cost_usd: float | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """Start AMICOR Stripe Checkout for one 30s commercial order (TEST or gated LIVE)."""
    mode = stripe_runtime_mode()
    if mode == "live_blocked":
        raise ValueError(
            "Live Stripe is blocked for Creative Studio until owner sets "
            "NOVA_CREATIVE_STRIPE_LIVE_ENABLED=true."
        )
    # mode == "live" is allowed only when the owner flag is on (stripe_runtime_mode already checks).

    client = get_studio_stripe_client()
    order_id = _order_id()
    render_cost = float(estimated_render_cost_usd) if estimated_render_cost_usd is not None else RENDER_COST_CEILING_USD
    if render_cost > RENDER_COST_CEILING_USD:
        raise ValueError(
            f"Estimated render cost ${render_cost:.2f} exceeds the ${RENDER_COST_CEILING_USD:.2f} ceiling. "
            "Owner approval required before raising the ceiling."
        )

    payment_mode = mode if mode != "unconfigured" else "test_fake"
    metadata = {
        "amicor_product": "nova_creative_studio",
        "order_id": order_id,
        "project_id": str(project_id),
        "owner_id": str(owner_id),
        "scope": SCOPE_LABEL,
        "customer_price_usd": f"{CUSTOMER_PRICE_USD:.2f}",
        "internal_render_cost_ceiling_usd": f"{RENDER_COST_CEILING_USD:.2f}",
        "estimated_render_cost_usd": f"{render_cost:.2f}",
        "payment_mode": payment_mode,
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
        "customer_email": customer_email or "",
        "stripe_checkout_session_id": session.get("id"),
        "stripe_payment_intent_id": None,
        "checkout_url": session.get("url"),
        "payment_mode": payment_mode,
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
        "fulfillment": {},
        "job_status": "awaiting_payment",
        "created_at": _now(),
        "updated_at": _now(),
        "pricing": public_pricing(),
    }
    order = _save_order_durable(order, db=db)
    message = (
        "AMICOR Stripe Checkout session created in LIVE mode. Real charges require a completed Checkout."
        if payment_mode == "live"
        else "AMICOR Stripe Checkout session created in TEST mode. No live charge."
    )
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
            "payment_mode": payment_mode,
        },
        "message": message,
    }


def get_studio_order(order_id: str, *, owner_id: str, db: Session | None = None) -> dict[str, Any] | None:
    return _load_order(order_id, owner_id=owner_id, db=db)


def list_studio_orders(
    *,
    owner_id: str,
    project_id: str | None = None,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    return _list_orders_durable(owner_id=owner_id, project_id=project_id, db=db)


def sync_studio_order_from_stripe(order_id: str, *, owner_id: str, db: Session | None = None) -> dict[str, Any]:
    order = get_studio_order(order_id, owner_id=owner_id, db=db)
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
    live = str(order.get("payment_mode") or "") == "live"
    if payment_status == "paid" or status == "complete":
        order["status"] = "paid"
        order["receipt"] = _build_receipt(order, session_id=session_id, live=live)
        order = fulfill_paid_order(order, db=db)
    elif status == "expired":
        order["status"] = "expired"
        order["job_status"] = "cancelled"
        order = _save_order_durable(order, db=db)
    else:
        order["status"] = "checkout_open"
        order["job_status"] = "awaiting_payment"
        order = _save_order_durable(order, db=db)
    return dict(order)


def record_production_cost(
    order_id: str,
    *,
    owner_id: str,
    actual_render_cost_usd: float,
    paid_provider_charges: bool = False,
    note: str = "",
    db: Session | None = None,
) -> dict[str, Any]:
    order = get_studio_order(order_id, owner_id=owner_id, db=db)
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
    return _save_order_durable(order, db=db)


def mark_order_job_status(
    order_id: str,
    *,
    owner_id: str,
    job_status: str,
    db: Session | None = None,
) -> dict[str, Any]:
    order = get_studio_order(order_id, owner_id=owner_id, db=db)
    if order is None:
        raise KeyError("order_not_found")
    order["job_status"] = str(job_status)
    order["updated_at"] = _now()
    return _save_order_durable(order, db=db)


def complete_test_checkout(order_id: str, *, owner_id: str, db: Session | None = None) -> dict[str, Any]:
    """Mark a TEST/fake checkout paid so receipts and job status can be verified without a card.

    Only allowed when payment_mode is test_fake or test. Never creates a live charge.
    """
    order = get_studio_order(order_id, owner_id=owner_id, db=db)
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
        return sync_studio_order_from_stripe(order_id, owner_id=owner_id, db=db)
    return sync_studio_order_from_stripe(order_id, owner_id=owner_id, db=db)


class StudioCheckoutError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def verify_studio_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    override = get_studio_stripe_override()
    if override is not None and not signature:
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise StudioCheckoutError("Invalid webhook payload.", 400)
        return parsed
    secret = studio_webhook_secret()
    if not secret:
        raise StudioCheckoutError("Creative Studio webhook secret is not configured.", 503)
    if not signature:
        raise StudioCheckoutError("Missing Stripe-Signature header.", 400)
    import stripe

    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise StudioCheckoutError("Invalid Creative Studio webhook signature.", 400) from exc
    if isinstance(event, dict):
        return event
    converted = getattr(event, "to_dict", lambda: {})()
    if not isinstance(converted, dict):
        raise StudioCheckoutError("Invalid Creative Studio webhook payload.", 400)
    return converted


def _record_webhook_event(
    *,
    event_id: str,
    event_type: str,
    order_id: str | None,
    result: str,
    db: Session | None = None,
) -> None:
    _WEBHOOK_EVENTS[event_id] = {
        "stripe_event_id": event_id,
        "event_type": event_type,
        "order_id": order_id,
        "processing_result": result,
        "created_at": _now(),
    }
    owns_session = False
    session = db
    if session is None:
        session = _open_db()
        owns_session = session is not None
    if session is None:
        return
    try:
        from app.core.nova.creative_studio.db_models import NovaCreativeWebhookEvent

        existing = (
            session.query(NovaCreativeWebhookEvent)
            .filter(NovaCreativeWebhookEvent.stripe_event_id == event_id)
            .first()
        )
        if existing is not None:
            return
        session.add(
            NovaCreativeWebhookEvent(
                id=f"cwe_{uuid.uuid4().hex[:12]}",
                stripe_event_id=event_id,
                event_type=event_type or "unknown",
                order_id=order_id,
                processing_result=result,
                created_at=_now(),
            )
        )
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        if owns_session and session is not None:
            session.close()


def _webhook_seen(event_id: str, *, db: Session | None = None) -> bool:
    if event_id in _WEBHOOK_EVENTS:
        return True
    owns_session = False
    session = db
    if session is None:
        session = _open_db()
        owns_session = session is not None
    if session is None:
        return False
    try:
        from app.core.nova.creative_studio.db_models import NovaCreativeWebhookEvent

        return (
            session.query(NovaCreativeWebhookEvent)
            .filter(NovaCreativeWebhookEvent.stripe_event_id == event_id)
            .first()
            is not None
        )
    except Exception:
        return False
    finally:
        if owns_session and session is not None:
            session.close()


def process_studio_webhook(event: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id:
        raise StudioCheckoutError("Webhook event id is required.", 400)
    if _webhook_seen(event_id, db=db):
        return {"duplicate": True, "result": "ignored"}

    obj = ((event.get("data") or {}).get("object") or {}) if isinstance(event.get("data"), dict) else {}
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    order_id = str(meta.get("order_id") or obj.get("client_reference_id") or "").strip()
    order = _load_order(order_id, db=db) if order_id else None
    result = "ignored"

    if event_type == "checkout.session.completed" and order is not None:
        payment_status = str(obj.get("payment_status") or "")
        if payment_status == "paid" or str(obj.get("status") or "") == "complete":
            order["payment_status"] = "paid"
            order["status"] = "paid"
            order["stripe_payment_intent_id"] = str(obj.get("payment_intent") or "") or order.get(
                "stripe_payment_intent_id"
            )
            session_id = str(obj.get("id") or order.get("stripe_checkout_session_id") or "")
            live = str(order.get("payment_mode") or "") == "live"
            order["receipt"] = _build_receipt(order, session_id=session_id, live=live)
            order = fulfill_paid_order(order, db=db)
            result = "fulfilled" if order.get("fulfillment", {}).get("ready_for_download") else "queued_for_production"
        else:
            result = "awaiting_payment"
    elif event_type in {"checkout.session.expired", "checkout.session.async_payment_failed"} and order is not None:
        order["status"] = "failed" if event_type.endswith("failed") else "expired"
        order["job_status"] = "cancelled"
        order["updated_at"] = _now()
        order = _save_order_durable(order, db=db)
        result = order["status"]

    _record_webhook_event(
        event_id=event_id,
        event_type=event_type,
        order_id=order["id"] if order else (order_id or None),
        result=result,
        db=db,
    )
    return {
        "duplicate": False,
        "result": result,
        "order_id": order["id"] if order else None,
        "job_status": order.get("job_status") if order else None,
        "fulfillment": order.get("fulfillment") if order else None,
    }
