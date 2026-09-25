"""One-time AMICOR marketplace checkout, webhook, and download entitlements."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from .manifest import PRODUCT_FILES
from .models import MarketplaceEntitlement, MarketplacePurchase, MarketplaceWebhookEvent
from .schema_ensure import ensure_marketplace_schema
from .stripe_client import get_marketplace_stripe_client, get_marketplace_stripe_override, marketplace_webhook_secret

ENTITLEMENT_HOURS = 72


class MarketplacePurchaseError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or "https://amicor-health-isf-py.onrender.com").rstrip("/")


def _email(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if "@" not in cleaned or len(cleaned) > 320:
        raise MarketplacePurchaseError("A valid email is required.", 422)
    return cleaned


def start_marketplace_checkout(db: Session, *, product_slug: str, email: str) -> dict[str, Any]:
    ensure_marketplace_schema()
    spec = PRODUCT_FILES.get(product_slug)
    if spec is None:
        raise MarketplacePurchaseError("Unknown marketplace product.", 404)
    if spec["access"] == "free" or int(spec["price_cents"]) <= 0:
        raise MarketplacePurchaseError("This product is free and does not require Stripe checkout.", 409)

    purchase = MarketplacePurchase(
        product_slug=product_slug,
        email=_email(email),
        amount_cents=int(spec["price_cents"]),
        currency="usd",
        status="pending",
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)

    payload = {
        "mode": "payment",
        "success_url": f"{_base_url()}/nova/marketplace/product/{product_slug}?purchase=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{_base_url()}/nova/marketplace/product/{product_slug}?purchase=cancelled",
        "client_reference_id": purchase.id,
        "customer_email": purchase.email,
        "metadata": {
            "amicor_marketplace_purchase_id": purchase.id,
            "amicor_product_slug": product_slug,
            "purchase_type": "one_time_digital_product",
        },
        "line_items": [{
            "price_data": {
                "currency": "usd",
                "unit_amount": int(spec["price_cents"]),
                "product_data": {
                    "name": product_slug.replace("-", " ").title(),
                    "metadata": {"amicor_product_slug": product_slug},
                },
            },
            "quantity": 1,
        }],
    }
    try:
        session = get_marketplace_stripe_client().create_checkout_session(
            payload=payload,
            idempotency_key=f"marketplace-checkout:{purchase.id}",
        )
    except Exception as exc:
        purchase.status = "failed"
        purchase.updated_at = now()
        db.commit()
        raise MarketplacePurchaseError(str(exc), 503) from exc
    purchase.stripe_checkout_session_id = str(session.get("id") or "") or None
    purchase.status = "checkout_open"
    purchase.updated_at = now()
    db.commit()
    return {
        "purchase_id": purchase.id,
        "product_slug": product_slug,
        "amount_cents": purchase.amount_cents,
        "currency": purchase.currency,
        "checkout_url": session.get("url"),
        "checkout_session_id": purchase.stripe_checkout_session_id,
        "mode": "payment",
    }


def verify_marketplace_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    override = get_marketplace_stripe_override()
    if override is not None and not signature:
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise MarketplacePurchaseError("Invalid webhook payload.", 400)
        return parsed
    secret = marketplace_webhook_secret()
    if not secret:
        raise MarketplacePurchaseError("Marketplace webhook secret is not configured.", 503)
    if not signature:
        raise MarketplacePurchaseError("Missing Stripe-Signature header.", 400)
    import stripe
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise MarketplacePurchaseError("Invalid marketplace webhook.", 400) from exc
    if isinstance(event, dict):
        return event
    converted = getattr(event, "to_dict", lambda: {})()
    if not isinstance(converted, dict):
        raise MarketplacePurchaseError("Invalid marketplace webhook.", 400)
    return converted


def _new_entitlement(db: Session, purchase: MarketplacePurchase) -> str:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    existing = db.query(MarketplaceEntitlement).filter(MarketplaceEntitlement.purchase_id == purchase.id).first()
    if existing is not None:
        return ""
    db.add(MarketplaceEntitlement(
        purchase_id=purchase.id,
        product_slug=purchase.product_slug,
        email=purchase.email,
        token_hash=digest,
        expires_at=now() + timedelta(hours=ENTITLEMENT_HOURS),
    ))
    return raw


def process_marketplace_webhook(db: Session, event: dict[str, Any]) -> dict[str, Any]:
    ensure_marketplace_schema()
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id:
        raise MarketplacePurchaseError("Webhook event id is required.", 400)
    if db.query(MarketplaceWebhookEvent).filter(MarketplaceWebhookEvent.stripe_event_id == event_id).first():
        return {"duplicate": True, "result": "ignored"}

    obj = ((event.get("data") or {}).get("object") or {}) if isinstance(event.get("data"), dict) else {}
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    purchase_id = str(meta.get("amicor_marketplace_purchase_id") or obj.get("client_reference_id") or "").strip()
    purchase = db.get(MarketplacePurchase, purchase_id) if purchase_id else None
    result = "ignored"
    raw_token = ""

    if event_type == "checkout.session.completed" and purchase is not None:
        payment_status = str(obj.get("payment_status") or "")
        if payment_status == "paid":
            purchase.status = "paid"
            purchase.stripe_payment_intent_id = str(obj.get("payment_intent") or "") or None
            purchase.updated_at = now()
            raw_token = _new_entitlement(db, purchase)
            result = "entitled"
        else:
            result = "awaiting_payment"
    elif event_type in {"checkout.session.expired", "checkout.session.async_payment_failed"} and purchase is not None:
        purchase.status = "failed" if event_type.endswith("failed") else "expired"
        purchase.updated_at = now()
        result = purchase.status

    db.add(MarketplaceWebhookEvent(
        stripe_event_id=event_id,
        event_type=event_type or "unknown",
        purchase_id=purchase.id if purchase else None,
        processing_result=result,
    ))
    db.commit()
    response = {"duplicate": False, "result": result, "purchase_id": purchase.id if purchase else None}
    if raw_token:
        response["test_download_token"] = raw_token
    return response


def entitlement_for_token(db: Session, *, product_slug: str, token: str) -> MarketplaceEntitlement | None:
    ensure_marketplace_schema()
    digest = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
    row = db.query(MarketplaceEntitlement).filter(
        MarketplaceEntitlement.product_slug == product_slug,
        MarketplaceEntitlement.token_hash == digest,
    ).first()
    if row is None or row.expires_at <= now():
        return None
    purchase = db.get(MarketplacePurchase, row.purchase_id)
    if purchase is None or purchase.status != "paid":
        return None
    return row
