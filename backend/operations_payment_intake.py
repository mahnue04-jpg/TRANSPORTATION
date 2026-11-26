"""Dedicated Operations payment event intake. Sales routes are registered separately."""

import os
from contextlib import asynccontextmanager

import psycopg2
import stripe
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

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


@asynccontextmanager
async def lifespan(app):
    database_url = os.getenv("NOVA_OPERATIONS_DATABASE_URL")
    if database_url:
        await run_in_threadpool(verify_writer, database_url)
    yield


app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
EVENT_TYPES = frozenset({
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed", "customer.subscription.updated",
    "customer.subscription.deleted", "invoice.paid", "invoice.payment_failed",
    "charge.refunded", "charge.dispute.created", "charge.dispute.closed",
})


@app.get("/health")
def health():
    return {"service": "nova-operations", "status": "running"}


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


@app.post("/payments/stripe/webhook")
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
        event = stripe.Webhook.construct_event(bytes(payload), signature, secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid signed event")
    if event.get("livemode") is not True or event.get("account"):
        raise HTTPException(400, "Expected a direct live account event")
    if event.type not in EVENT_TYPES:
        return {"received": True}
    object_id = event.data.object.get("id")
    if not isinstance(object_id, str) or not object_id or not event.id.startswith("evt_"):
        raise HTTPException(400, "Invalid event identifiers")
    try:
        await run_in_threadpool(record_event, database_url, event.id, event.type, object_id)
    except psycopg2.Error:
        raise HTTPException(503, "Payment event storage is unavailable")
    return {"received": True}
