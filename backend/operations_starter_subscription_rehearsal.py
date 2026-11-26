"""Private synthetic Starter subscription rehearsal; never a production app."""
import os
import secrets
from urllib.parse import urlparse

# Check isolation before importing application modules or opening any database.
def safe_configuration():
    price = os.getenv("NOVA_STRIPE_PRICE_STARTER", "")
    token = os.getenv("NOVA_OPERATIONS_SANDBOX_ACCESS_TOKEN", "")
    origin = urlparse(os.getenv("RENDER_EXTERNAL_URL", ""))
    return (
        os.getenv("APP_ENV") == "staging"
        and os.getenv("AMICOR_ENVIRONMENT") == "staging"
        and os.getenv("NOVA_STRIPE_LIVE_ENABLED") == "false"
        and os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") == "false"
        and os.getenv("NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED") == "false"
        and os.getenv("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED") == "true"
        and os.getenv("NOVA_BILLING_CHECKOUT_TRIAL_ENABLED") == "false"
        and os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_test_", "rk_test_"))
        and price.startswith("price_")
        and price == os.getenv("NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID")
        and len(token) >= 24
        and os.getenv("DATABASE_URL") == "sqlite:////tmp/nova-starter-999-rehearsal.db"
        and origin.scheme == "https"
        and origin.hostname == "nova-operations-checkout-sandbox.onrender.com"
        and not origin.username and not origin.password
    )

if not safe_configuration():
    raise RuntimeError("Isolated Starter sandbox configuration required")

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.auth import UserContext
from app.db.session import get_db
from app.core.nova.billing.models import NovaTenantSubscription
from app.core.nova.billing.schema_ensure import ensure_nova_billing_schema
from app.core.nova.billing.service import start_checkout, BillingError
from app.core.nova.billing.stripe_client import LiveNovaBillingStripeClient
from app.core.nova.billing.starter_authenticated_access import authenticated_starter_access
from app.core.nova.billing.starter_feature_routes import router, get_current_user_context
from app.core.nova.billing.starter_subscription_evidence import verify_starter_feature
from app.core.nova.billing.subscription_reversal_evidence import verify_current_invoice_payment
from datetime import datetime, timezone
from types import SimpleNamespace

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
ORIGIN = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
os.environ["NOVA_BILLING_SUCCESS_URL"] = ORIGIN + "/sandbox-test"
os.environ["NOVA_BILLING_CANCEL_URL"] = ORIGIN + "/sandbox-test"

def owner(x_amicor_sandbox_token: str = Header(default="")):
    if not safe_configuration() or not secrets.compare_digest(
        x_amicor_sandbox_token, os.environ["NOVA_OPERATIONS_SANDBOX_ACCESS_TOKEN"]
    ):
        raise HTTPException(403, "Sandbox access denied")
    return UserContext(user_id="starter-999-synthetic-owner",
        email="starter-999@example.invalid", role="admin",
        organization_id="starter-999-synthetic-tenant")

app.dependency_overrides[get_current_user_context] = owner
app.include_router(router)

@app.on_event("startup")
def startup():
    ensure_nova_billing_schema()

@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response

@app.get("/health")
def health():
    return {"status": "sandbox_only", "stripe_live": False,
            "customer_sales": False, "plan": "starter", "amount_cents": 999}

# Isolated recovery uses Stripe JSON responses directly, not SDK objects.
# This transport has no write methods or caller-supplied URLs.
import requests
import re
import logging
logger = logging.getLogger("nova.starter.recovery")

class StripeReadError(Exception):
    def __init__(self, status):
        self.http_status = status

class StripeReadResource:
    def __init__(self, transport, resource, prefix):
        self.transport, self.resource, self.prefix = transport, resource, prefix

    def retrieve(self, identifier, params=None):
        if not isinstance(identifier, str) or not re.fullmatch(self.prefix + r"[A-Za-z0-9_]+", identifier):
            raise ValueError("Invalid Stripe identifier")
        return self.transport.get(self.resource + "/" + identifier, params)

    def list(self, params):
        return self.transport.get(self.resource, params)

class StripeReadTransport:
    def __init__(self, key):
        if not key.startswith(("sk_test_", "rk_test_")):
            raise ValueError("Test key required")
        self.key = key
        self.v1 = SimpleNamespace(
            checkout=SimpleNamespace(sessions=StripeReadResource(self, "checkout/sessions", "cs_test_")),
            subscriptions=StripeReadResource(self, "subscriptions", "sub_"),
            invoice_payments=StripeReadResource(self, "invoice_payments", "inpay_"),
            payment_intents=StripeReadResource(self, "payment_intents", "pi_"),
            charges=StripeReadResource(self, "charges", "ch_"),
        )

    def get(self, resource, params=None):
        query = []
        for k, v in (params or {}).items():
            if isinstance(v, list):
                query.extend((k + "[]", item) for item in v)
            else:
                query.append((k, v))
        response = requests.get("https://api.stripe.com/v1/" + resource,
            headers={"Authorization": "Bearer " + self.key,
                     "Stripe-Version": "2025-06-30.basil"},
            params=query, timeout=15, allow_redirects=False)
        if response.status_code != 200:
            raise StripeReadError(response.status_code)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Non-object provider response")
        return payload

def plain(obj):
    if not isinstance(obj, dict):
        raise ValueError("Expected provider JSON object")
    return obj

def client():
    return StripeReadTransport(os.environ["STRIPE_SECRET_KEY"])

def rehearsal_feature_access(db, authenticated_user, feature):
    if not safe_configuration() or authenticated_user.email != "starter-999@example.invalid":
        return False
    try:
        row = db.execute(select(NovaTenantSubscription).where(
            NovaTenantSubscription.tenant_id == authenticated_user.organization_id
        )).scalar_one_or_none()
        if row is None or row.stripe_subscription_id != os.getenv("NOVA_STARTER_RECOVERY_SUBSCRIPTION_ID"):
            return False
        stripe = client()
        subscription = stripe.v1.subscriptions.retrieve(row.stripe_subscription_id, {"expand": ["latest_invoice"]})
        return (verify_starter_feature(feature=feature, tenant_id=authenticated_user.organization_id,
            row=row, subscription=subscription, now=datetime.now(timezone.utc))
            and verify_current_invoice_payment(stripe, plan="starter", customer_id=row.stripe_customer_id,
                subscription=subscription))
    except Exception as exc:
        logger.warning("starter_workspace_failure exception_type=%s", type(exc).__name__)
        return False

# Only this standalone process overrides the staging route adapter.
import app.core.nova.billing.starter_feature_routes as feature_routes
feature_routes.authenticated_starter_access = rehearsal_feature_access

# Recovery revision deliberately cannot create another checkout.
@app.post("/sandbox/checkout")
def checkout(user: UserContext = Depends(owner)):
    raise HTTPException(409, "New checkout disabled; recover existing test payment")

def checkout_matches(checkout, user, customer_id):
    metadata = checkout.get("metadata") or {}
    return (
        str(checkout.get("id", "")).startswith("cs_test_")
        and checkout.get("livemode") is False
        and checkout.get("mode") == "subscription"
        and checkout.get("status") == "complete"
        and checkout.get("payment_status") == "paid"
        and checkout.get("customer") == customer_id
        and checkout.get("client_reference_id") == user.organization_id
        and metadata.get("nova_plan_key") == "starter"
        and metadata.get("nova_tenant_id") == user.organization_id
        and metadata.get("nova_user_id") == user.user_id
        and metadata.get("nova_product") == "nova_saas"
    )

class RecoveryError(Exception):
    """Only fixed, non-sensitive diagnostic codes are exposed."""
    def __init__(self, code):
        self.code = code

def require_recovery(condition, code):
    if not condition:
        raise RecoveryError(code)

def read_provider(fn, stage):
    try:
        return plain(fn())
    except Exception as exc:
        status = getattr(exc, "http_status", None)
        suffix = {401: "authentication", 403: "permission", 404: "not_found",
                  429: "rate_limit"}.get(status, "provider_error")
        raise RecoveryError(stage + "_" + suffix) from None

def recover_checkout(stripe, user):
    session_id = os.getenv("NOVA_STARTER_RECOVERY_CHECKOUT_ID", "").strip()
    customer_id = os.getenv("NOVA_STARTER_RECOVERY_CUSTOMER_ID", "").strip()
    subscription_id = os.getenv("NOVA_STARTER_RECOVERY_SUBSCRIPTION_ID", "").strip()
    require_recovery(session_id.startswith("cs_test_") and customer_id.startswith("cus_")
                     and subscription_id.startswith("sub_"), "recovery_configuration")
    checkout = read_provider(lambda: stripe.v1.checkout.sessions.retrieve(session_id),
                             "checkout_read")
    require_recovery(checkout.get("id") == session_id, "checkout_id")
    require_recovery(checkout.get("livemode") is False, "checkout_mode_live")
    require_recovery(checkout.get("subscription") == subscription_id, "checkout_subscription")
    require_recovery(checkout.get("customer") == customer_id, "checkout_customer")
    require_recovery(checkout.get("mode") == "subscription", "checkout_mode")
    require_recovery(checkout.get("status") == "complete" and checkout.get("payment_status") == "paid",
                     "checkout_payment_status")
    require_recovery(checkout.get("amount_total") == 999 and checkout.get("currency") == "usd",
                     "checkout_amount")
    # Independently verify the exact subscription and its paid invoice in
    # reconcile(). The fixed owner-only locator is not a public account claim.
    # A missing Checkout metadata field is allowed ONLY when no supplied
    # field contradicts the synthetic identity and the subscription itself
    # has all required tenant metadata (checked by verify_starter_feature).
    metadata = checkout.get("metadata") or {}
    expected = {"nova_plan_key": "starter", "nova_tenant_id": user.organization_id,
                "nova_user_id": user.user_id, "nova_product": "nova_saas"}
    require_recovery(all(k not in metadata or metadata[k] == v for k, v in expected.items()),
                     "checkout_metadata_conflict")
    require_recovery(checkout.get("client_reference_id") in (None, "", user.organization_id),
                     "checkout_reference_conflict")
    return checkout


@app.post("/sandbox/reconcile")
def reconcile(user: UserContext = Depends(owner), db: Session = Depends(get_db)):
    stage = "local_record"
    try:
        row = db.execute(select(NovaTenantSubscription).where(
            NovaTenantSubscription.tenant_id == user.organization_id)).scalar_one_or_none()
        stripe = client()
        stage = "exact_test_checkout_recovery"
        checkout = recover_checkout(stripe, user)
        if row is not None and row.stripe_checkout_session_id not in (None, checkout["id"]):
            raise RecoveryError("stored_checkout_conflict")
        customer_id = checkout["customer"]
        price_id = os.environ["NOVA_STRIPE_PRICE_STARTER"]
        stage = "local_binding"
        if row is not None and (
            row.stripe_customer_id not in (None, customer_id)
            or row.stripe_price_id not in (None, price_id)
            or row.plan_key not in (None, "starter")
        ):
            raise ValueError("conflicting local record")
        stage = "subscription_binding"
        sub_id = checkout["subscription"]
        if not isinstance(sub_id, str) or not sub_id.startswith("sub_"):
            raise ValueError("invalid subscription")
        if row is not None and row.stripe_subscription_id not in (None, sub_id):
            raise ValueError("conflicting subscription")
        stage = "stripe_subscription_retrieval"
        subscription = read_provider(lambda: stripe.v1.subscriptions.retrieve(sub_id, {"expand": ["latest_invoice"]}), "subscription_read")
        candidate = SimpleNamespace(tenant_id=user.organization_id, plan_key="starter",
            subscription_status="active", stripe_customer_id=customer_id,
            stripe_subscription_id=sub_id, stripe_price_id=price_id)
        stage = "subscription_and_invoice_evidence"
        if not verify_starter_feature(feature="basic_workspace", tenant_id=user.organization_id,
                row=candidate, subscription=subscription, now=datetime.now(timezone.utc)):
            raise ValueError("invalid subscription evidence")
        stage = "invoice_payment_and_reversal_evidence"
        if not verify_current_invoice_payment(stripe, plan="starter",
                customer_id=customer_id, subscription=subscription):
            raise ValueError("invalid payment evidence")
        stage = "persist_verified_record"
        if row is None:
            row = NovaTenantSubscription(tenant_id=user.organization_id)
            db.add(row)
        row.plan_key = "starter"
        row.stripe_customer_id = customer_id
        row.stripe_price_id = price_id
        row.stripe_checkout_session_id = checkout["id"]
        row.stripe_subscription_id = sub_id
        row.subscription_status = "active"
        db.commit()
        return {"verified": True, "plan": "starter", "managed_tasks": 0}
    except RecoveryError as exc:
        logger.warning("starter_recovery_failure code=%s", exc.code)
        db.rollback()
        raise HTTPException(409, {"stage": exc.code, "message": "Existing payment not yet verified"})
    except Exception as exc:
        logger.warning("starter_recovery_failure stage=%s exception_type=%s", stage, type(exc).__name__)
        db.rollback()
        # Fixed diagnostic category only; no raw provider errors or identifiers.
        raise HTTPException(409, {"stage": stage, "message": "Existing payment not yet verified"})


# Signed notification rehearsal only. Never use event payloads to grant access.
# The existing owner-only reconcile path remains the sole activation path;
# every feature request checks fresh provider evidence, including reversals.
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from app.core.nova.billing.models import NovaBillingWebhookEvent
import json
import stripe as stripe_sdk

@app.post("/api/marketing/nova-agent/stripe/webhook")
async def starter_webhook(request: Request, db: Session = Depends(get_db)):
    if not safe_configuration() or os.getenv("NOVA_STARTER_SIGNED_WEBHOOK_STAGING_ENABLED") != "true":
        raise HTTPException(503, "Staging webhook disabled")
    secret = os.getenv("STRIPE_NOVA_AGENT_WEBHOOK_SECRET", "")
    signature = request.headers.get("Stripe-Signature", "")
    if not secret.startswith("whsec_"):
        raise HTTPException(503, "Signing secret unavailable")
    if not signature:
        raise HTTPException(400, "Signature required")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > 262144:
            raise HTTPException(413, "Event too large")
    try:
        stripe_sdk.Webhook.construct_event(bytes(payload), signature, secret, tolerance=300)
        event = json.loads(payload)
    except Exception:
        raise HTTPException(400, "Invalid signed event") from None
    if not isinstance(event, dict) or event.get("livemode") is not False or event.get("account"):
        raise HTTPException(400, "Unexpected event mode or account")
    event_id = event.get("id")
    kind = event.get("type")
    data = event.get("data")
    obj = data.get("object") if isinstance(data, dict) else None
    if not isinstance(event_id, str) or not re.fullmatch(r"evt_[A-Za-z0-9_]{1,120}", event_id) or not isinstance(obj, dict):
        raise HTTPException(400, "Malformed event")
    customer_id = os.getenv("NOVA_STARTER_RECOVERY_CUSTOMER_ID", "")
    subscription_id = os.getenv("NOVA_STARTER_RECOVERY_SUBSCRIPTION_ID", "")
    checkout_id = os.getenv("NOVA_STARTER_RECOVERY_CHECKOUT_ID", "")
    if not (customer_id.startswith("cus_") and subscription_id.startswith("sub_") and checkout_id.startswith("cs_test_")):
        raise HTTPException(503, "Synthetic identifiers unavailable")
    # Accept only the exact configured rehearsal object. Other billing events
    # are acknowledged as ignored; this endpoint never processes other plans.
    if kind == "checkout.session.completed":
        matched = (obj.get("id") == checkout_id and obj.get("customer") == customer_id
                   and obj.get("subscription") == subscription_id)
    elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
        matched = obj.get("id") == subscription_id and obj.get("customer") == customer_id
    elif kind in ("invoice.paid", "invoice.payment_failed"):
        parent = obj.get("parent") or {}
        details = parent.get("subscription_details") or {} if isinstance(parent, dict) else {}
        sub = details.get("subscription") if isinstance(details, dict) else None
        matched = obj.get("customer") == customer_id and sub == subscription_id
    else:
        matched = False
    if not matched or obj.get("livemode") is not False:
        return {"received": True, "result": "ignored"}
    # Receipt-only audit. A signed notification is not payment proof; do not
    # mutate entitlement or revenue state from a potentially stale snapshot.
    existing = db.execute(select(NovaBillingWebhookEvent).where(
        NovaBillingWebhookEvent.stripe_event_id == event_id)).scalar_one_or_none()
    if existing:
        if existing.event_type != kind:
            raise HTTPException(409, "Event identity conflict")
        return {"received": True, "result": "duplicate"}
    db.add(NovaBillingWebhookEvent(stripe_event_id=event_id, event_type=kind,
        tenant_id="starter-999-synthetic-tenant", processing_result="receipt_only"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(select(NovaBillingWebhookEvent).where(
            NovaBillingWebhookEvent.stripe_event_id == event_id)).scalar_one_or_none()
        if existing and existing.event_type == kind:
            return {"received": True, "result": "duplicate"}
        raise HTTPException(503, "Receipt persistence unavailable")
    return {"received": True, "result": "receipt_only"}


@app.get("/sandbox-test", response_class=HTMLResponse)
def page():
    return HTMLResponse("""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Starter subscription test</title>
<style>body{font:17px system-ui;max-width:640px;margin:40px auto;padding:20px}button,input,textarea{font:inherit;margin:8px 0;padding:10px}input,textarea{width:95%}button{display:block}pre{white-space:pre-wrap}</style>
<h1>Operations $9.99/month sandbox</h1><p>Private synthetic test only. No real payments or managed tasks.</p>
<label>Private sandbox access token<input id="token" type="password" autocomplete="off"></label>
<button id="checkout" disabled>New checkout disabled</button><a id="pay" hidden rel="noreferrer">Open Stripe test checkout</a>
<button id="verify">Verify paid subscription</button><button id="workspace">Check workspace</button>
<label>Test planning goal<textarea id="goal" maxlength="500">Prepare a weekly review</textarea></label>
<button id="plan">Test planning</button><button id="templates">Test templates</button><button id="assistance">Test guidance</button><pre id="result" role="status"></pre>
<script>
const el=id=>document.getElementById(id);
async function call(path,body,method="POST"){const r=await fetch(path,{method,headers:{"x-amicor-sandbox-token":el("token").value,"Content-Type":"application/json"},body:method==="POST"?JSON.stringify(body||{}):undefined,cache:"no-store"});if(!r.ok){let d=await r.json().catch(()=>({}));throw Error("Request denied or not ready ("+r.status+")"+(d.detail?.stage?" — "+d.detail.stage:""));}return r.json();}
async function run(fn){el("result").textContent="Checking existing test payment or workspace…";try{el("result").textContent=JSON.stringify(await fn(),null,2)}catch(e){el("result").textContent=e.message}}
el("checkout").onclick=()=>run(async()=>{let d=await call("/sandbox/checkout");let u=new URL(d.checkout_url);if(u.origin!=="https://checkout.stripe.com")throw Error("Unexpected checkout origin");el("pay").href=u.href;el("pay").hidden=false;return "Synthetic checkout created"});
el("verify").onclick=()=>run(()=>call("/sandbox/reconcile"));
el("workspace").onclick=()=>run(()=>call("/api/nova/starter/workspace",null,"GET"));
el("plan").onclick=()=>run(()=>call("/api/nova/starter/plan",{goal:el("goal").value}));
el("templates").onclick=()=>run(()=>call("/api/nova/starter/templates",null,"GET"));
el("assistance").onclick=()=>run(()=>call("/api/nova/starter/assistance",null,"GET"));
</script></html>""",headers={"Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})
