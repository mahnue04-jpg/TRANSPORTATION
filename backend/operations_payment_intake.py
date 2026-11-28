"""Dedicated Operations payment event intake. Sales routes are registered separately.

The same router is mounted on ``app.main:app`` (Render) and on this module's
standalone FastAPI app. The webhook path remains ``POST /payments/stripe/webhook``.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

import psycopg2
import stripe
from fastapi import APIRouter, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

EVENT_TYPES = frozenset({
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed", "customer.subscription.updated",
    "customer.subscription.deleted", "invoice.paid", "invoice.payment_failed",
    "charge.refunded", "charge.dispute.created", "charge.dispute.closed",
})

# Exact hosted path — distinct from Ride/Deliver ``POST /api/payments/stripe/webhook``.
WEBHOOK_PATH = "/payments/stripe/webhook"
READINESS_PATH = "/payments/operations/readiness"

router = APIRouter(tags=["nova-operations-payment-intake"])


def signed_event_payload(payload: bytes, signature: str, secret: str) -> dict:
    """Verify the Stripe signature, then return a plain dict of the event.

    ``construct_event`` enforces the signature. Newer stripe-python Event
    objects are not dicts and reject ``.get``, so parse the already-verified
    payload bytes instead of calling deprecated Event conversion helpers.
    """
    stripe.Webhook.construct_event(payload, signature, secret)
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unsupported Stripe event payload") from exc
    if type(parsed) is not dict:
        raise ValueError("Unsupported Stripe event payload")
    return parsed


def verify_writer(database_url):
    connection = psycopg2.connect(database_url, connect_timeout=5)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT current_user = 'nova_ops_event_writer'
                    AND current_database() = 'amicor'
                    AND has_column_privilege('public.nova_operations_payment_events', 'event_id', 'SELECT')
                    AND has_column_privilege('public.nova_operations_payment_events', 'event_id', 'INSERT')
                    AND has_column_privilege('public.nova_operations_payment_events', 'event_type', 'INSERT')
                    AND has_column_privilege('public.nova_operations_payment_events', 'object_id', 'INSERT')
                    AND NOT has_table_privilege('public.nova_operations_payment_events', 'DELETE')"""
            )
            if cursor.fetchone() != (True,):
                raise RuntimeError("Operations payment writer permissions do not match")
    finally:
        connection.close()


def record_event(database_url, event_id, event_type, object_id):
    connection = psycopg2.connect(database_url, connect_timeout=5)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO nova_operations_payment_events (event_id, event_type, object_id)
                   VALUES (%s, %s, %s) ON CONFLICT (event_id) DO NOTHING""",
                (event_id, event_type, object_id),
            )
    finally:
        connection.close()


def _env_present(*names: str) -> bool:
    return all(bool(os.getenv(name, "").strip()) for name in names)


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def operations_production_readiness(*, probe_database: bool = True) -> dict:
    """Return non-secret production readiness booleans for Operations hosting.

    Never includes credential values, webhook secrets, bucket names, or URLs.
    """
    secret = os.getenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", "")
    database_url = os.getenv("NOVA_OPERATIONS_DATABASE_URL", "").strip()
    writer_ok: bool | None = None
    writer_error = False
    if probe_database and database_url:
        try:
            verify_writer(database_url)
            writer_ok = True
        except Exception:
            writer_ok = False
            writer_error = True

    private_configured = _env_present(
        "NOVA_OPERATIONS_PRIVATE_S3_BUCKET",
        "NOVA_OPERATIONS_PRIVATE_S3_REGION",
        "NOVA_OPERATIONS_PRIVATE_S3_ACCESS_KEY",
        "NOVA_OPERATIONS_PRIVATE_S3_SECRET_KEY",
    )
    separate_bucket: bool | None = None
    production_runtime = False
    private_storage_ok: bool | None = None
    try:
        from app.core.nova.work_revenue.operations_private_storage import (
            OperationsStorageSettings,
            is_production_artifact_runtime,
        )

        production_runtime = is_production_artifact_runtime()
        if production_runtime and private_configured:
            try:
                OperationsStorageSettings.from_environment()
                private_storage_ok = True
                separate_bucket = True
            except Exception:
                private_storage_ok = False
                # Distinct failure from shared-bucket vs missing fields is not leaked.
                doc_bucket = (
                    os.getenv("AMICOR_DOCUMENT_S3_BUCKET", "").strip()
                    or os.getenv("AMICOR_DOCUMENT_BUCKET", "").strip()
                )
                ops_bucket = os.getenv("NOVA_OPERATIONS_PRIVATE_S3_BUCKET", "").strip()
                if doc_bucket and ops_bucket:
                    separate_bucket = ops_bucket.casefold() != doc_bucket.casefold()
    except Exception:
        production_runtime = False

    starter_mode = None
    binding_mode = None
    delivery_mode = None
    revenue_mode = None
    try:
        from app.core.nova.billing.starter_authenticated_access import starter_access_mode
        from app.core.nova.work_revenue.operations_customer_delivery import (
            customer_delivery_mode,
        )
        from app.core.nova.work_revenue.operations_revenue_recording import (
            operations_revenue_mode,
        )
        from app.core.nova.work_revenue.operations_starter_payment_binding import (
            starter_binding_mode,
        )

        starter_mode = starter_access_mode()
        binding_mode = starter_binding_mode()
        delivery_mode = customer_delivery_mode()
        revenue_mode = operations_revenue_mode()
    except Exception:
        pass

    live_sales = _truthy("NOVA_STRIPE_LIVE_ENABLED") and _truthy(
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED"
    )
    from app.core.nova.billing.stripe_client import (
        nova_billing_webhook_secret,
        stripe_webhook_secret_configured,
    )
    from app.core.nova.work_revenue.operations_webhook_contract import (
        operations_webhook_contract,
    )
    from app.modules.marketing.operations_billing import agent_webhook_secret

    webhooks = operations_webhook_contract()
    webhooks["marketing"]["secret_configured"] = stripe_webhook_secret_configured(
        agent_webhook_secret()
    )
    webhooks["saas"]["secret_configured"] = stripe_webhook_secret_configured(
        nova_billing_webhook_secret()
    )
    webhooks["payment_intake_not_fulfillment"]["secret_configured"] = (
        stripe_webhook_secret_configured(secret)
    )

    return {
        "service": "nova-operations",
        "live_sales_enabled": live_sales,
        "payment_receiver": {
            "webhook_path": WEBHOOK_PATH,
            "distinct_from_customer_payments_path": "/api/payments/stripe/webhook",
            "webhook_secret_configured": stripe_webhook_secret_configured(secret),
            "database_url_configured": bool(database_url),
            "writer_permissions_ok": writer_ok,
            "writer_probe_error": writer_error,
        },
        "private_storage": {
            "production_runtime_markers": production_runtime,
            "dedicated_credentials_configured": private_configured,
            "settings_ok": private_storage_ok,
            "separate_from_document_bucket": separate_bucket,
        },
        "authentication_gates": {
            "starter_access_mode": starter_mode,
            "starter_binding_mode": binding_mode,
            "customer_delivery_mode": delivery_mode,
            "revenue_recording_mode": revenue_mode,
        },
        "required_configuration": {
            "app_env_production": os.getenv("APP_ENV", "").strip() == "production",
            "amicor_environment_production": (
                os.getenv("AMICOR_ENVIRONMENT", "").strip() == "production"
            ),
            "stripe_live_flag": _truthy("NOVA_STRIPE_LIVE_ENABLED"),
            "customer_sales_flag": _truthy("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED"),
            "starter_price_matches_catalog": (
                os.getenv("NOVA_STRIPE_PRICE_STARTER", "").strip()
                == "price_1UfWpDBCDlIbm4gm7kY4yIva"
            ),
            "billing_trial_disabled": (
                os.getenv("NOVA_BILLING_CHECKOUT_TRIAL_ENABLED", "").strip() == "false"
            ),
        },
        "stripe_webhooks": webhooks,
    }


@asynccontextmanager
async def lifespan(app):
    database_url = os.getenv("NOVA_OPERATIONS_DATABASE_URL")
    if database_url:
        await run_in_threadpool(verify_writer, database_url)
    yield


@router.get(READINESS_PATH)
def payment_intake_readiness():
    """Non-secret Operations production readiness for hosted Render entry."""
    return operations_production_readiness(probe_database=True)


@router.post(WEBHOOK_PATH)
async def receive_event(request: Request):
    signature = request.headers.get("stripe-signature")
    if not signature:
        raise HTTPException(400, "Stripe signature required")
    secret = os.getenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", "")
    database_url = os.getenv("NOVA_OPERATIONS_DATABASE_URL", "")
    if not secret.startswith("whsec_") or not database_url:
        raise HTTPException(503, "Payment intake is unavailable")
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > 1024 * 1024:
            raise HTTPException(413, "Event too large")
        payload.extend(chunk)
    try:
        event = signed_event_payload(bytes(payload), signature, secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid signed event")
    if event.get("livemode") is not True or event.get("account"):
        raise HTTPException(400, "Expected a direct live account event")
    event_type = event.get("type")
    if event_type not in EVENT_TYPES:
        return {"received": True}
    data = event.get("data")
    obj = data.get("object") if isinstance(data, dict) else None
    object_id = obj.get("id") if isinstance(obj, dict) else None
    event_id = event.get("id")
    if (
        not isinstance(object_id, str)
        or not object_id
        or not isinstance(event_id, str)
        or not event_id.startswith("evt_")
        or not isinstance(event_type, str)
    ):
        raise HTTPException(400, "Invalid event identifiers")
    try:
        await run_in_threadpool(record_event, database_url, event_id, event_type, object_id)
    except psycopg2.Error:
        raise HTTPException(503, "Payment event storage is unavailable")
    return {"received": True}


app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    return {"service": "nova-operations", "status": "running"}
