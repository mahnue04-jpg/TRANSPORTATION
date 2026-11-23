"""Isolated hosted Stripe TEST to private download acceptance. Synthetic fixtures only."""
from __future__ import annotations

import hmac
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from uuid import UUID

database = urlsplit(os.environ["DATABASE_URL"])
storage = urlsplit(os.environ["AMICOR_DOCUMENT_S3_ENDPOINT"])
operator_token = os.environ["NOVA_OPS_REHEARSAL_TOKEN"]
if (
    os.getenv("NOVA_OPS_REHEARSAL_ENABLED") != "true"
    or any(os.getenv(key) != "staging" for key in ("APP_ENV", "AMICOR_ENVIRONMENT"))
    or any(os.getenv(key) != "false" for key in (
        "NOVA_STRIPE_LIVE_ENABLED", "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED",
    ))
    or database.scheme != "postgresql"
    or database.path != "/operations_rehearsal"
    or database.hostname != os.environ["NOVA_OPS_REHEARSAL_DB_HOST"]
    or not database.hostname.endswith(".neon.tech")
    or storage.scheme != "https"
    or storage.hostname != os.environ["NOVA_OPS_REHEARSAL_STORAGE_HOST"]
    or not storage.hostname.endswith(".neon.tech")
    or os.getenv("AMICOR_DOCUMENT_S3_BUCKET") != "starter-synthetic-private"
    or not os.getenv("STRIPE_SECRET_KEY", "").startswith(("rk_test_", "sk_test_"))
    or not os.getenv("STRIPE_NOVA_AGENT_WEBHOOK_SECRET", "").startswith("whsec_")
    or os.getenv("NOVA_OPERATIONS_STARTER_TEST_PRICE_ID") != "price_1UdwuEBCDlIbm4gm4Ggt7nuI"
    or len(operator_token) < 32
):
    raise RuntimeError("Synthetic staging rehearsal configuration required")

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from app.auth import create_access_token  # noqa: E402
from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs  # noqa: E402
from app.core.nova.work_revenue import operations_customer_delivery as delivery  # noqa: E402
from app.core.nova.work_revenue.operations_starter_payment_binding import (  # noqa: E402
    bind_paid_starter, starter_bindings,
)
from app.db.models import User  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.modules.marketing import routes as marketing  # noqa: E402
from app.modules.marketing.models import MarketingWebsiteLead  # noqa: E402

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(marketing.router)
app.include_router(delivery.customer_delivery_router)
marketing.send_lead_notification = lambda lead: {"attempted": False, "sent": False}

OWNER_ORG = "synthetic-rehearsal-owner-org"
OWNER_ID = "synthetic-rehearsal-owner"
TASK = "synthetic-starter-csv"
API = "/api/marketing"
CUSTOMER = "/api/nova/work/operations/customer/deliveries"
CSV = b"Name,Status\nSynthetic Customer,Active\nSynthetic Customer,Active\n"


@app.on_event("startup")
def initialize_disposable_schema():
    for table in (User.__table__, MarketingWebsiteLead.__table__, starter_bindings, jobs.jobs, delivery.grants):
        table.create(engine, checkfirst=True)


def is_operator(request: Request) -> bool:
    value = request.headers.get("x-nova-rehearsal", "")
    return value.isascii() and hmac.compare_digest(value, operator_token)


@app.middleware("http")
async def isolate_routes(request: Request, call_next):
    path, method = request.url.path, request.method
    if method == "GET" and (
        path in {"/health", "/rehearsal", "/nova/anonymous-agent"} or path.startswith(CUSTOMER + "/")
    ):
        return await call_next(request)
    if method == "POST" and path == API + "/nova-agent/stripe/webhook":
        try:
            event = await request.json()
        except ValueError:
            return JSONResponse({"detail": "Invalid test event"}, status_code=400)
        if not isinstance(event, dict) or event.get("livemode") is not False:
            return JSONResponse({"detail": "Stripe test events only"}, status_code=403)
        return await call_next(request)
    if method == "POST" and is_operator(request):
        if path == API + "/leads":
            try:
                data = await request.json()
            except ValueError:
                return JSONResponse({"detail": "Invalid synthetic input"}, status_code=400)
            if (isinstance(data, dict) and data.get("lead_type") == "anonymous_operations"
                    and data.get("service_plan") == "starter_49"
                    and str(data.get("work_email", "")).endswith("@example.invalid")
                    and data.get("organization_name") == "AMICOR Synthetic Rehearsal"):
                return await call_next(request)
        if (path.startswith(API + "/leads/") and path.endswith("/checkout")) or (
            path.startswith("/rehearsal/") and path.endswith(("/fulfill", "/revoke"))
        ):
            return await call_next(request)
    return JSONResponse({"detail": "Rehearsal route unavailable"}, status_code=404)


@app.get("/health")
def health():
    return {"status": "synthetic_staging_only", "stripe_live": False, "customer_sales": False}


@app.get("/rehearsal", response_class=HTMLResponse)
def rehearsal_page():
    return HTMLResponse(
        Path(__file__).with_name("operations_starter_delivery_rehearsal.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow",
                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"},
    )


@app.get("/nova/anonymous-agent", response_class=HTMLResponse)
def return_from_checkout():
    return "Stripe sandbox returned. The signed Stripe event is the payment record."


def _test_user(db: Session, user_id: str, email: str, org: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=email, organization_id=org, role="staff",
                    hashed_password="synthetic-user-no-password", is_active=True, is_verified=True)
        db.add(user)
        db.commit()
    return user


@app.post("/rehearsal/{lead_id}/fulfill")
def fulfill(lead_id: UUID, db: Session = Depends(get_db)):
    lead_id = str(lead_id)
    lead = db.get(MarketingWebsiteLead, lead_id)
    if (lead is None or not lead.work_email.endswith("@example.invalid")
            or not (lead.stripe_checkout_session_id or "").startswith("cs_test_")):
        raise HTTPException(404, "Synthetic Stripe order unavailable")
    engagement_id = lead_id.replace("-", "")
    bind_paid_starter(db, lead_id=lead_id, organization_id=OWNER_ORG, owner_user_id=OWNER_ID,
                      engagement_id=engagement_id, task_id=TASK, client_name="AMICOR Synthetic Rehearsal")
    buyer = _test_user(db, lead_id, lead.work_email, "synthetic-buyer-org")
    other = _test_user(db, "synthetic-other", "other-rehearsal@example.invalid", "synthetic-other-org")
    result = jobs.submit_review_job(db, org=OWNER_ORG, owner=OWNER_ID, engagement_id=engagement_id,
                                    task_id=TASK, request_key=lead_id, raw=CSV)
    job_id = result["job_id"]
    if result["status"] == "AWAITING_REVIEW":
        jobs.review_job(db, job_id=job_id, org=OWNER_ORG, owner=OWNER_ID, approve=True)
    delivery.issue_grant(db, job_id=job_id, owner_org=OWNER_ORG, owner_id=OWNER_ID,
                         recipient_user_id=buyer.id)
    return JSONResponse({
        "download": CUSTOMER + "/" + job_id, "sha256": result["output_sha256"],
        "buyer": create_access_token({"sub": buyer.id, "nonce": secrets.token_hex(8)}),
        "other": create_access_token({"sub": other.id, "nonce": secrets.token_hex(8)}),
    }, headers={"Cache-Control": "no-store"})


@app.post("/rehearsal/{job_id}/revoke")
def revoke(job_id: UUID, db: Session = Depends(get_db)):
    return delivery.revoke_grant(db, job_id=str(job_id), owner_org=OWNER_ORG, owner_id=OWNER_ID)
