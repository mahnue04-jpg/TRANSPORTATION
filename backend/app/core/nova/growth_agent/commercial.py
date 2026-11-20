"""Plan/feature-gate model. Prices configurable and unlaunched — no live Stripe."""

from __future__ import annotations

from typing import Any

# Prices are illustrative configuration only. Not offered for sale; no Checkout.
PLANS: dict[str, dict[str, Any]] = {
    "starter": {
        "label": "Starter",
        "monthly_price_usd": 49,
        "launched": False,
        "quotas": {
            "conversations_per_month": 200,
            "workflow_runs_per_month": 100,
            "appointments_per_month": 50,
            "ai_tokens_per_month": 100_000,
        },
        "features": ["chat_widget", "crm", "faq_engine", "booking", "mock_workflows"],
    },
    "growth": {
        "label": "Growth",
        "monthly_price_usd": 149,
        "launched": False,
        "quotas": {
            "conversations_per_month": 1000,
            "workflow_runs_per_month": 500,
            "appointments_per_month": 250,
            "ai_tokens_per_month": 500_000,
        },
        "features": [
            "chat_widget",
            "crm",
            "faq_engine",
            "booking",
            "mock_workflows",
            "analytics",
            "handoff",
        ],
    },
    "pro": {
        "label": "Pro",
        "monthly_price_usd": 399,
        "launched": False,
        "quotas": {
            "conversations_per_month": 5000,
            "workflow_runs_per_month": 2500,
            "appointments_per_month": 1000,
            "ai_tokens_per_month": 2_000_000,
        },
        "features": [
            "chat_widget",
            "crm",
            "faq_engine",
            "booking",
            "mock_workflows",
            "analytics",
            "handoff",
            "priority_support_placeholder",
        ],
    },
}

# Estimated unit costs for instrumentation only — not billed.
UNIT_COST_MODEL = {
    "email_mock": 0.0,
    "sms_mock": 0.0,
    "sms_live_estimate_usd": 0.0075,
    "email_live_estimate_usd": 0.001,
    "ai_token_estimate_usd": 0.000002,
    "voice_minute_estimate_usd": 0.02,
    "notes": (
        "Estimates only. Live providers remain off. Legal/compliance review and "
        "owner approval required before any paid activation."
    ),
}


def plan_catalog() -> dict[str, Any]:
    return {
        "plans": PLANS,
        "stripe_live": False,
        "subscriptions_enabled": False,
        "unit_cost_model": UNIT_COST_MODEL,
        "paid_prerequisites": [
            "Owner approval to launch commercial plans",
            "Legal counsel confirmation (TCPA/CAN-SPAM/state)",
            "Approved messaging provider credentials (env/vault only)",
            "Approved AI provider credentials with spend caps",
            "Stripe product/price IDs if subscriptions are launched later",
        ],
    }


def quota_for(plan_code: str) -> dict[str, int]:
    plan = PLANS.get((plan_code or "starter").lower()) or PLANS["starter"]
    return dict(plan["quotas"])
