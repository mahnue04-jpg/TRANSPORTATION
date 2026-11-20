"""Standalone test-only API; not mounted in production AMICOR services."""
from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr
from flow import CheckoutError, Commerce, Settings

app = FastAPI(
    title="VoiceLedger Pro digital delivery (TEST ONLY)",
    docs_url=None, redoc_url=None, openapi_url=None,
)
_service = None


class CheckoutInput(BaseModel):
    email: str


def service() -> Commerce:
    global _service
    if _service is None:
        if os.getenv("VL_CHECKOUT_MODE") != "test":
            raise HTTPException(503, "Digital checkout is disabled.")
        try:
            _service = Commerce(Settings.from_env())
        except CheckoutError:
            raise HTTPException(503, "TEST checkout configuration is incomplete.") from None
    return _service


@app.get("/health")
def health():
    return {"mode": "test_only", "checkout_enabled": os.getenv("VL_CHECKOUT_MODE") == "test",
            "production_checkout": False, "email_delivery": "manual_test_outbox_only"}


@app.post("/api/voiceledger/checkout")
def checkout(body: CheckoutInput):
    try:
        return service().start_checkout(body.email)
    except CheckoutError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/voiceledger/stripe/webhook")
async def webhook(request: Request, stripe_signature: str | None = Header(None, alias="Stripe-Signature")):
    if not stripe_signature:
        raise HTTPException(400, "Missing Stripe signature.")
    raw = await request.body()
    if len(raw) > 1024 * 1024:
        raise HTTPException(413, "Payload too large.")
    try:
        result = service().receive_webhook(raw, stripe_signature)
        return {"processed": result}
    except CheckoutError:
        # Keep sensitive internal state out of public error responses.
        raise HTTPException(400, "Webhook was not accepted.") from None


@app.get("/api/voiceledger/orders/{session_id}")
def order_status(session_id: str):
    # Do not reveal customer email, purchase tokens, or private order details.
    try:
        return service().status(session_id)
    except CheckoutError:
        raise HTTPException(404, "Unknown test order.") from None


@app.get("/api/voiceledger/download/{token}")
def download(token: str):
    try:
        payload = service().download(token)
    except CheckoutError:
        raise HTTPException(404, "Delivery unavailable.") from None
    return Response(
        content=payload, media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="VoiceLedger-Pro-Licensed.zip"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
