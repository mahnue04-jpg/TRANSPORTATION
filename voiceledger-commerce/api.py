"""Standalone test-only API; not mounted in production AMICOR services."""
from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, HTMLResponse
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



# This page is deliberately informational. Stripe's redirect does not confer
# an entitlement or send a license.
@app.get("/complete", response_class=HTMLResponse)
def complete_page():
    page = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>VoiceLedger Pro — Test Checkout</title>
<style>body{font-family:system-ui,sans-serif;background:#f4f8fb;color:#10283f;padding:24px}
main{max-width:640px;background:white;padding:28px;margin:40px auto;border-radius:15px}
h1{margin-top:0}#status{padding:16px;background:#edf5f6;border-radius:8px}
a{color:#087569}small{color:#566978}</style></head><body>
<main><h1>VoiceLedger Pro — test checkout</h1>
<p>This is a Stripe <strong>test-mode</strong> transaction, not a real purchase.</p>
<p id="status" role="status" aria-live="polite">Checking your test order status…</p>
<p>If you paid successfully in test mode, the download is released only after
our server verifies payment with Stripe. The current staging system queues
delivery for manual review; it does not email files automatically.</p>
<p><a href="https://voiceledger-pro-staging-v15.onrender.com/">Back to VoiceLedger free preview</a></p>
<small>No customer finances are uploaded by this page. Keep your local ledger backup safe.</small>
</main><script>
(function(){
const id=new URLSearchParams(location.search).get('session_id')||'';
const out=document.getElementById('status');
if(!/^cs_test_[A-Za-z0-9_]{1,160}$/.test(id)){
 out.textContent='No valid test checkout session was supplied. Nothing has been delivered.';
 return;
}
fetch('/api/voiceledger/orders/'+encodeURIComponent(id),{credentials:'omit',cache:'no-store'})
 .then(r=>r.ok?r.json():Promise.reject(new Error('lookup')))
 .then(data=>{
  if(data.status==='paid')out.textContent='Test payment verified. Delivery is queued for manual staging review.';
  else out.textContent='Test payment not yet verified. No download has been released.';
 })
 .catch(()=>{out.textContent='Cannot confirm test payment. No download has been released. Please contact the test operator.';});
})();
</script></body></html>"""
    return HTMLResponse(
        content=page,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        },
    )


@app.get("/cancel", response_class=HTMLResponse)
def cancel_page():
    return HTMLResponse(
        content='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"><title>VoiceLedger test checkout cancelled</title></head><body><main><h1>Test checkout cancelled</h1><p>No file was delivered. Return to the <a href="https://voiceledger-pro-staging-v15.onrender.com/">free VoiceLedger preview</a>.</p></main></body></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )

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
