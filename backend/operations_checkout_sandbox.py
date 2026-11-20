"""Isolated, explicitly opted-in Stripe TEST checkout validation for Operations.

Not a customer deployment. Does not import app.main. Uses only a disposable
SQLite database and synthetic .invalid leads. No fulfillment or worker routes.
Start only after owner review and isolated service configuration.
"""
from __future__ import annotations

import os
from pathlib import Path

# Must run before app.db.session or app.modules.marketing is imported.
_DB_PREFIX = "sqlite:////tmp/amicor-operations-sandbox-"
_SANDBOX_DB = os.getenv("NOVA_OPERATIONS_SANDBOX_DB_URL", "").strip()


def _safe_configuration() -> bool:
    stripe_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    return (
        os.getenv("NOVA_OPERATIONS_SANDBOX_ENABLED", "").strip().lower() == "true"
        and _SANDBOX_DB.startswith(_DB_PREFIX)
        and _SANDBOX_DB.endswith(".sqlite")
        and ".." not in _SANDBOX_DB
        and stripe_key.startswith(("sk_test_", "rk_test_"))
        and os.getenv("STRIPE_NOVA_AGENT_WEBHOOK_SECRET", "").startswith("whsec_")
        and os.getenv("NOVA_OPERATIONS_STARTER_TEST_PRICE_ID", "").startswith("price_")
        and os.getenv("APP_ENV", "staging").strip().lower() != "production"
        and os.getenv("AMICOR_ENVIRONMENT", "staging").strip().lower() != "production"
        and os.getenv("NOVA_STRIPE_LIVE_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED", "").strip().lower() != "true"
        and os.getenv("NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED", "").strip().lower() != "true"
    )


if not _safe_configuration():
    raise RuntimeError("Operations Checkout sandbox requires isolated SQLite, test Stripe, and all live/customer processing disabled")

# Ensure every database session stays inside the explicitly disposable sandbox.
if os.environ.get("DATABASE_URL") not in (None, "", _SANDBOX_DB):
    raise RuntimeError("Operations Checkout sandbox DATABASE_URL mismatch")
os.environ["DATABASE_URL"] = _SANDBOX_DB

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from app.db.session import Base, engine  # noqa: E402
from app.modules.marketing.models import MarketingWebsiteLead  # noqa: E402
from app.modules.marketing import routes as marketing_routes  # noqa: E402

# No notification email, production leads, or customer contact from rehearsal.
marketing_routes.send_lead_notification = lambda lead: {
    "attempted": False, "sent": False, "reason": "sandbox_disabled",
}

app = FastAPI(
    title="AMICOR Operations Stripe sandbox",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(marketing_routes.router)


@app.on_event("startup")
def initialize_disposable_sandbox() -> None:
    if not _safe_configuration():
        raise RuntimeError("Operations sandbox is not safely configured")
    # This isolated table holds synthetic test requests only.
    Path(_SANDBOX_DB[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine, tables=[MarketingWebsiteLead.__table__])


@app.middleware("http")
async def synthetic_only_guard(request: Request, call_next):
    path = request.url.path
    if not _safe_configuration():
        return JSONResponse(status_code=503, content={"detail": "Sandbox unavailable"})
    if path == "/health":
        return JSONResponse({
            "status": "sandbox_only",
            "stripe_live": False,
            "synthetic_orders_only": True,
            "customer_processing": False,
            "private_delivery": False,
        }, headers={"Cache-Control": "no-store"})
    if path == "/api/marketing/nova-agent/stripe/webhook" and request.method == "POST":
        # Signature must still pass the existing route's Stripe verifier.
        return await call_next(request)
    if path == "/api/marketing/nova-agent/checkout-status" and request.method == "GET":
        return await call_next(request)

    access_token = os.getenv("NOVA_OPERATIONS_SANDBOX_ACCESS_TOKEN", "").strip()
    if len(access_token) < 24 or request.headers.get("x-amicor-sandbox-token") != access_token:
        return JSONResponse(status_code=403, content={"detail": "Sandbox access denied"})

    if path == "/api/marketing/leads" and request.method == "POST":
        try:
            data = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid test request"})
        if (
            not isinstance(data, dict)
            or data.get("lead_type") != "anonymous_operations"
            or data.get("service_plan") != "starter_49"
            or not str(data.get("work_email", "")).endswith(".invalid")
            or str(data.get("lead_source", "sandbox")) not in {"sandbox", "sandbox_checkout"}
        ):
            return JSONResponse(status_code=403, content={"detail": "Only synthetic Starter requests are allowed"})
        return await call_next(request)

    if (path.startswith("/api/marketing/leads/") and path.endswith("/checkout")
            and request.method == "POST"):
        return await call_next(request)

    return JSONResponse(status_code=404, content={"detail": "Sandbox route unavailable"})
