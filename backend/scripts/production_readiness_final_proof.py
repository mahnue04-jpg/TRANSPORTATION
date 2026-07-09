"""Final local production-readiness proof before Render deploy.

Clean test artifacts -> one fresh ride -> full driver lifecycle ->
assert single billing/payment/document set and cleared active queues.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from server_runtime import ensure_server_running  # noqa: E402

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PWD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
DRIVER = os.getenv("AMICOR_PROD_DRIVER_ID", "4bc0e517-d60d-4d45-bc20-a14b1e4aa407")


def tok(client: httpx.Client, email: str) -> str:
    body = client.post("/api/auth/login", json={"email": email, "password": PWD}).json()
    return str(body.get("token") or body.get("access_token"))


def clear_driver(client: httpx.Client, headers: dict) -> None:
    for _ in range(8):
        active = client.get(f"/api/health-isf/drivers/{DRIVER}/active-ride", headers=headers).json()
        assigned = client.get(f"/api/health-isf/drivers/{DRIVER}/assigned-rides", headers=headers).json()
        if not active.get("has_active_ride") and not assigned:
            return
        ride_id = str(
            (active.get("ride") or {}).get("id")
            or (assigned[0].get("id") if assigned else "")
            or ""
        )
        if not ride_id:
            return
        client.post(
            f"/api/health-isf/drivers/{DRIVER}/accept-ride",
            headers=headers,
            json={"ride_id": ride_id},
        )
        for step in ("arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
            client.post(
                f"/api/health-isf/drivers/{DRIVER}/route-progress",
                headers=headers,
                json={"ride_id": ride_id, "target_state": step},
            )
        client.post(
            f"/api/health-isf/drivers/{DRIVER}/dropoff-complete",
            headers=headers,
            json={"ride_id": ride_id},
        )
        time.sleep(0.2)


def main() -> int:
    ensure_server_running(force_restart=True)
    client = httpx.Client(base_url=BASE, timeout=120)
    dh = {"Authorization": f"Bearer {tok(client, 'dispatcher@amicor.local')}"}
    rh = {"Authorization": f"Bearer {tok(client, 'rider@amicor.local')}"}
    ah = {"Authorization": f"Bearer {tok(client, 'admin@amicor.local')}"}

    # Role/session sanity: all roles can authenticate and hit live APIs.
    for label, headers in (("dispatcher", dh), ("rider", rh), ("admin", ah)):
        ping = client.get("/api/health-isf/operations/admin-revenue", headers=headers)
        if label == "rider":
            ping = client.get("/api/health-isf/customer-requests?limit=1", headers=headers)
        if ping.status_code >= 400:
            print(f"SESSION_FAIL role={label} status={ping.status_code}", flush=True)
            print("RESULT=NOT_READY", flush=True)
            return 1

    purge = client.post("/api/health-isf/ops/purge-test-artifacts", headers=dh)
    if purge.status_code >= 400:
        print(f"CLEANUP_FAIL {purge.status_code} {purge.text[:300]}", flush=True)
        print("CLEANUP_DONE=false", flush=True)
        print("RESULT=NOT_READY", flush=True)
        return 1
    print("CLEANUP_DONE=true", flush=True)
    print("PURGE", json.dumps(purge.json(), default=str)[:800], flush=True)

    clear_driver(client, dh)
    driver = client.get(f"/api/health-isf/drivers/{DRIVER}", headers=dh).json()
    driver_available = str(driver.get("status") or "").lower() == "available"
    print(f"DRIVER_RESET={'true' if driver_available else 'false'}", flush=True)

    before_billing = client.get(
        "/api/health-isf/operations/billing-handoffs", headers=dh, params={"limit": 300}
    ).json()
    before_rev = client.get("/api/health-isf/operations/admin-revenue", headers=ah).json()
    before_earn = client.get(f"/api/health-isf/drivers/{DRIVER}/earnings", headers=dh).json()
    before_billing_count = len(before_billing)
    before_platform = float(before_rev.get("platform_revenue_total_usd") or 0)
    before_earnings = float(before_earn.get("earnings_lifetime_usd") or 0)

    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    name = f"RENDER_READY_{stamp}"
    phone = f"648{stamp[-7:]}"[-10:]
    created = client.post(
        "/api/health-isf/customer-requests",
        headers=rh,
        json={
            "rider_name": name,
            "rider_phone": phone,
            "pickup_address": "100 Render Ready Pickup Ave, Minneapolis, MN 55411",
            "dropoff_address": "200 Render Ready Dropoff St, Minneapolis, MN 55415",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "final local production readiness ride",
        },
    )
    created.raise_for_status()
    body = created.json()
    ride_id = str(body.get("ride_id") or "")
    req_id = str(body.get("id") or "")
    print(f"FINAL_LOCAL_RIDE_ID={ride_id}", flush=True)

    time.sleep(1.0)
    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
    if str(ride.get("driver_id") or "") != DRIVER:
        client.post(f"/api/health-isf/dispatcher/customer-requests/{req_id}/approve", headers=dh)
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{req_id}/assign-driver",
            headers=dh,
            json={"driver_id": DRIVER},
        )
        if assign.status_code >= 400:
            reassign = client.patch(
                f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
                headers=dh,
                json={"driver_id": DRIVER},
            )
            if reassign.status_code >= 400:
                print("ASSIGN_FAIL", assign.text[:200], reassign.text[:200], flush=True)
                print("RESULT=NOT_READY", flush=True)
                return 1

    for _ in range(20):
        ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
        if str(ride.get("driver_id") or "") == DRIVER:
            break
        time.sleep(0.4)

    # Driver App endpoint lifecycle only (accept -> progress -> complete).
    accept = client.post(
        f"/api/health-isf/drivers/{DRIVER}/accept-ride",
        headers=dh,
        json={"ride_id": ride_id},
    )
    if accept.status_code >= 400:
        print("ACCEPT_FAIL", accept.text[:300], flush=True)
        print("RESULT=NOT_READY", flush=True)
        return 1
    for step in ("arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
        resp = client.post(
            f"/api/health-isf/drivers/{DRIVER}/route-progress",
            headers=dh,
            json={"ride_id": ride_id, "target_state": step},
        )
        if resp.status_code >= 400:
            print(f"STEP_FAIL {step}", resp.text[:300], flush=True)
            print("RESULT=NOT_READY", flush=True)
            return 1
    complete = client.post(
        f"/api/health-isf/drivers/{DRIVER}/dropoff-complete",
        headers=dh,
        json={"ride_id": ride_id},
    )
    if complete.status_code >= 400:
        print("COMPLETE_FAIL", complete.text[:400], flush=True)
        print("RESULT=NOT_READY", flush=True)
        return 1
    time.sleep(1.0)

    # Idempotent re-complete must not create duplicates.
    client.post(
        f"/api/health-isf/drivers/{DRIVER}/dropoff-complete",
        headers=dh,
        json={"ride_id": ride_id},
    )
    time.sleep(0.5)

    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
    fin = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=dh).json()
    docs = client.get(f"/api/health-isf/rides/{ride_id}/trip-documents", headers=dh).json()
    billing = client.get(
        "/api/health-isf/operations/billing-handoffs", headers=dh, params={"limit": 300}
    ).json()
    rev = client.get("/api/health-isf/operations/admin-revenue", headers=ah).json()
    earn = client.get(f"/api/health-isf/drivers/{DRIVER}/earnings", headers=dh).json()
    driver = client.get(f"/api/health-isf/drivers/{DRIVER}", headers=dh).json()
    active = client.get(f"/api/health-isf/drivers/{DRIVER}/active-ride", headers=dh).json()
    assigned = client.get(f"/api/health-isf/drivers/{DRIVER}/assigned-rides", headers=dh).json()
    queue = client.get("/api/health-isf/dispatch/queue", headers=dh, params={"limit": 300}).json()
    active_asg = client.get(
        "/api/health-isf/dispatch/active-assignments", headers=dh, params={"limit": 300}
    ).json()

    bill_for_ride = [b for b in billing if str(b.get("ride_id")) == ride_id]
    doc_types = {str(d.get("document_type")) for d in docs}
    billing_delta = len(billing) - before_billing_count
    platform_delta = float(rev.get("platform_revenue_total_usd") or 0) - before_platform
    earnings_delta = float(earn.get("earnings_lifetime_usd") or 0) - before_earnings
    ride_in_queue = any(str(q.get("ride_id")) == ride_id for q in queue)
    ride_in_active = any(str(a.get("ride_id")) == ride_id for a in active_asg)

    flags = {
        "DUPLICATE_BILLING_FIXED": len(bill_for_ride) == 1,
        "BILLING_CREATED": len(bill_for_ride) == 1 and billing_delta == 1,
        "DRIVER_EARNINGS_UPDATED": earnings_delta > 0,
        "PLATFORM_REVENUE_UPDATED": platform_delta > 0,
        "DOCUMENTS_CREATED": doc_types
        >= {"trip_receipt", "driver_payout_statement", "billing_record"}
        and len(docs) == 3,
        "ACTIVE_QUEUES_CLEARED": (not ride_in_queue)
        and (not ride_in_active)
        and (not active.get("has_active_ride"))
        and len(assigned) == 0,
        "DRIVER_RESET": str(driver.get("status") or "").lower() == "available",
        "PAYMENT_CREATED": bool(fin.get("payment_transaction_id")),
        "RIDE_COMPLETED": str(ride.get("lifecycle_state") or "").lower() == "completed",
    }

    for key, value in flags.items():
        print(f"{key}={'true' if value else 'false'}", flush=True)

    print(
        json.dumps(
            {
                "ride_id": ride_id,
                "passenger": name,
                "billing_delta": billing_delta,
                "bill_rows_for_ride": len(bill_for_ride),
                "doc_types": sorted(doc_types),
                "doc_count": len(docs),
                "earnings_delta": round(earnings_delta, 2),
                "platform_delta": round(platform_delta, 2),
                "driver_status": driver.get("status"),
                "queue_total": len(queue),
                "active_asg_total": len(active_asg),
                "fare": fin.get("ride_price_usd"),
                "driver_pay": fin.get("driver_pay_usd"),
                "platform": fin.get("platform_revenue_usd"),
            },
            indent=2,
        ),
        flush=True,
    )

    ready = all(flags.values())
    print(f"RESULT={'READY_FOR_RENDER' if ready else 'NOT_READY'}", flush=True)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
