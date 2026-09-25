import json

import pytest

from app.core.nova.marketplace.stripe_client import (
    FakeMarketplaceStripeClient,
    get_marketplace_stripe_client,
    set_marketplace_stripe_override,
)


def test_fake_marketplace_checkout_is_one_time_payment():
    client = FakeMarketplaceStripeClient()
    payload = {
        "mode": "payment",
        "success_url": "https://example.test/success",
        "cancel_url": "https://example.test/cancel",
        "client_reference_id": "purchase-1",
        "customer_email": "buyer@example.com",
        "metadata": {"amicor_marketplace_purchase_id": "purchase-1"},
        "line_items": [{"price_data": {"currency": "usd", "unit_amount": 900}, "quantity": 1}],
    }
    session = client.create_checkout_session(payload=payload, idempotency_key="purchase-1")
    again = client.create_checkout_session(payload=payload, idempotency_key="purchase-1")
    assert session["mode"] == "payment"
    assert session["id"] == again["id"]
    assert client.created_count == 1


def test_marketplace_rejects_non_test_key(monkeypatch):
    set_marketplace_stripe_override(None)
    monkeypatch.setenv("STRIPE_MARKETPLACE_SECRET_KEY", "sk_live_do_not_use")
    with pytest.raises(ValueError, match="TEST-only"):
        get_marketplace_stripe_client()


def test_marketplace_does_not_need_subscription_price_lookup():
    client = FakeMarketplaceStripeClient()
    session = client.create_checkout_session(
        payload={
            "mode": "payment",
            "line_items": [{"price_data": {"currency": "usd", "unit_amount": 2900}, "quantity": 1}],
        },
        idempotency_key="blueprint",
    )
    assert session["mode"] == "payment"
    assert "subscription_data" not in session
