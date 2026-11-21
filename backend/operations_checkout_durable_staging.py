"""Isolated staging TEST checkout with a separately restricted durable receipt ledger.

Never imports app.main. Synthetic .invalid leads only. Local disposable SQLite
contains only the marketing lead binding; durable orders and paid receipts are
written to isolated PostgreSQL using a restricted account only after explicit
configuration and successful fail-closed role validation. No customer work,
production payment, notifications or workers. Do not use existing sandbox URL.
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
        and os.getenv("NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED", "").strip().lower() == "true"
        and os.getenv("APP_ENV", "").strip().lower() == "staging"
        and os.getenv("AMICOR_ENVIRONMENT", "").strip().lower() == "staging"
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
    raise RuntimeError("Operations durable receipt sandbox requires isolated SQLite, restricted PostgreSQL, test Stripe, and all live/customer processing disabled")

# Ensure every database session stays inside the explicitly disposable sandbox.
if os.environ.get("DATABASE_URL") not in (None, "", _SANDBOX_DB):
    raise RuntimeError("Operations Checkout sandbox DATABASE_URL mismatch")
os.environ["DATABASE_URL"] = _SANDBOX_DB

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, HTMLResponse  # noqa: E402
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
    # Fail closed if the restricted durable PostgreSQL account lacks exactly the
    # required grants; never create or migrate durable database objects.
    from operations_checkout_durable_receipts import _dedicated_staging_engine, verify_store_ready
    receipt_engine = _dedicated_staging_engine()
    try:
        verify_store_ready(receipt_engine)
    finally:
        receipt_engine.dispose()
    # This isolated SQLite table holds synthetic test lead records only.
    Path(_SANDBOX_DB[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine, tables=[MarketingWebsiteLead.__table__])


@app.middleware("http")
async def synthetic_only_guard(request: Request, call_next):
    path = request.url.path
    if not _safe_configuration():
        return JSONResponse(status_code=503, content={"detail": "Sandbox unavailable"})
    if path == "/nova/anonymous-agent" and request.method == "GET":
        # Stripe Checkout returns here after payment/cancel. Never interpret
        # query arguments as payment proof: only the signed webhook updates DB.
        outcome = request.query_params.get("checkout", "")
        if outcome in {"success", "cancelled"}:
            title = "Stripe test checkout returned" if outcome == "success" else "Stripe test checkout cancelled"
            message = (
                "Stripe redirected back from the test checkout. Payment confirmation is handled separately by the signed Stripe webhook."
                if outcome == "success" else
                "The test checkout was cancelled. No payment is confirmed by this page."
            )
            html = (
                "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<meta name='robots' content='noindex,nofollow'>"
                "<title>AMICOR Operations Test Checkout</title></head>"
                "<body style='font:16px system-ui;max-width:580px;margin:48px auto;padding:20px'>"
                "<h1>" + title + "</h1><p>" + message + "</p>"
                "<p><a href='/sandbox-test'>Back to synthetic checkout test</a></p></body></html>"
            )
            return HTMLResponse(html, headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
            })
    if path == "/sandbox-test" and request.method == "GET":
        # UI contains no secrets; the token is entered locally by the owner.
        html = Path(__file__).with_name("operations_checkout_sandbox_ui.html").read_text(encoding="utf-8")
        return HTMLResponse(html, headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        })
    if path == "/health":
        return JSONResponse({
            "status": "durable_receipt_staging_only",
            "stripe_live": False,
            "synthetic_orders_only": True,
            "customer_processing": False,
            "private_delivery": False,
            "receipt_store": "restricted_postgres",
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
