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

def plain(obj):
    return obj.to_dict_recursive() if hasattr(obj, "to_dict_recursive") else obj

def client():
    return LiveNovaBillingStripeClient(api_key=os.environ["STRIPE_SECRET_KEY"])._build_client()

@app.post("/sandbox/checkout")
def checkout(user: UserContext = Depends(owner), db: Session = Depends(get_db)):
    try:
        price = plain(client().v1.prices.retrieve(os.environ["NOVA_STRIPE_PRICE_STARTER"]))
        if not (price["livemode"] is False and price["active"] is True
                and price["unit_amount"] == 999 and price["currency"] == "usd"
                and price["recurring"]["interval"] == "month"
                and price["recurring"]["interval_count"] == 1):
            raise ValueError("Incorrect price")
        result = start_checkout(db, user=user, plan_key="starter")
        if not result["checkout_session_id"].startswith("cs_test_") or result["trial_applied"]:
            raise ValueError("Incorrect checkout mode")
        return {"checkout_url": result["checkout_url"]}
    except Exception:
        db.rollback()
        raise HTTPException(409, "Synthetic checkout unavailable")

@app.post("/sandbox/reconcile")
def reconcile(user: UserContext = Depends(owner), db: Session = Depends(get_db)):
    # Never trust redirect parameters; fetch the previously stored exact session.
    # Reconcile on demand, independently of any webhook on the older sandbox.
    try:
        row = db.execute(select(NovaTenantSubscription).where(
            NovaTenantSubscription.tenant_id == user.organization_id)).scalar_one()
        stripe = client()
        checkout = plain(stripe.v1.checkout.sessions.retrieve(row.stripe_checkout_session_id))
        if not (checkout["id"] == row.stripe_checkout_session_id
                and checkout["livemode"] is False and checkout["mode"] == "subscription"
                and checkout["status"] == "complete" and checkout["payment_status"] == "paid"
                and checkout["customer"] == row.stripe_customer_id
                and checkout["client_reference_id"] == row.tenant_id
                and checkout["metadata"]["nova_plan_key"] == "starter"
                and checkout["metadata"]["nova_tenant_id"] == row.tenant_id
                and checkout["metadata"]["nova_product"] == "nova_saas"):
            raise ValueError("Unverified checkout")
        sub_id = checkout["subscription"]
        if not isinstance(sub_id, str) or not sub_id.startswith("sub_"):
            raise ValueError("Invalid subscription")
        if row.stripe_subscription_id and row.stripe_subscription_id != sub_id:
            raise ValueError("Conflicting subscription")
        subscription = plain(stripe.v1.subscriptions.retrieve(sub_id, {"expand": ["latest_invoice"]}))
        candidate = SimpleNamespace(tenant_id=row.tenant_id, plan_key=row.plan_key,
            subscription_status="active", stripe_customer_id=row.stripe_customer_id,
            stripe_subscription_id=sub_id, stripe_price_id=row.stripe_price_id)
        if not verify_starter_feature(feature="basic_workspace", tenant_id=row.tenant_id,
                row=candidate, subscription=subscription, now=datetime.now(timezone.utc)):
            raise ValueError("Invalid subscription")
        if not verify_current_invoice_payment(stripe, plan="starter",
                customer_id=row.stripe_customer_id, subscription=subscription):
            raise ValueError("Invalid payment")
        row.stripe_subscription_id = sub_id
        row.subscription_status = "active"
        db.commit()
        return {"verified": True, "plan": "starter", "managed_tasks": 0}
    except Exception:
        db.rollback()
        raise HTTPException(409, "Verified paid subscription not available")

@app.get("/sandbox-test", response_class=HTMLResponse)
def page():
    return HTMLResponse("""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Starter subscription test</title>
<style>body{font:17px system-ui;max-width:640px;margin:40px auto;padding:20px}button,input,textarea{font:inherit;margin:8px 0;padding:10px}input,textarea{width:95%}button{display:block}pre{white-space:pre-wrap}</style>
<h1>Operations $9.99/month sandbox</h1><p>Private synthetic test only. No real payments or managed tasks.</p>
<label>Private sandbox access token<input id="token" type="password" autocomplete="off"></label>
<button id="checkout">Create $9.99 test checkout</button><a id="pay" hidden rel="noreferrer">Open Stripe test checkout</a>
<button id="verify">Verify paid subscription</button><button id="workspace">Check workspace</button>
<label>Test planning goal<textarea id="goal" maxlength="500">Prepare a weekly review</textarea></label>
<button id="plan">Test planning</button><button id="templates">Test templates</button><button id="assistance">Test guidance</button><pre id="result" role="status"></pre>
<script>
const el=id=>document.getElementById(id);
async function call(path,body,method="POST"){const r=await fetch(path,{method,headers:{"x-amicor-sandbox-token":el("token").value,"Content-Type":"application/json"},body:method==="POST"?JSON.stringify(body||{}):undefined,cache:"no-store"});if(!r.ok)throw Error("Request denied or not ready ("+r.status+")");return r.json();}
async function run(fn){try{el("result").textContent=JSON.stringify(await fn(),null,2)}catch(e){el("result").textContent=e.message}}
el("checkout").onclick=()=>run(async()=>{let d=await call("/sandbox/checkout");let u=new URL(d.checkout_url);if(u.origin!=="https://checkout.stripe.com")throw Error("Unexpected checkout origin");el("pay").href=u.href;el("pay").hidden=false;return "Synthetic checkout created"});
el("verify").onclick=()=>run(()=>call("/sandbox/reconcile"));
el("workspace").onclick=()=>run(()=>call("/api/nova/starter/workspace",null,"GET"));
el("plan").onclick=()=>run(()=>call("/api/nova/starter/plan",{goal:el("goal").value}));
el("templates").onclick=()=>run(()=>call("/api/nova/starter/templates",null,"GET"));
el("assistance").onclick=()=>run(()=>call("/api/nova/starter/assistance",null,"GET"));
</script></html>""",headers={"Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})
