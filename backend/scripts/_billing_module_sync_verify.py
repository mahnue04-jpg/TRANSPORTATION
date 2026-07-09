"""Verify Billing is source of truth after one completed production ride."""
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

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PWD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
DRIVER = os.getenv("AMICOR_PROD_DRIVER_ID", "4bc0e517-d60d-4d45-bc20-a14b1e4aa407")


def tok(client: httpx.Client, email: str) -> str:
    body = client.post("/api/auth/login", json={"email": email, "password": PWD}).json()
    return str(body.get("token") or body.get("access_token"))


def clear_driver(client: httpx.Client, headers: dict) -> None:
    for _ in range(6):
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
    client = httpx.Client(base_url=BASE, timeout=90)
    dh = {"Authorization": f"Bearer {tok(client, 'dispatcher@amicor.local')}"}
    rh = {"Authorization": f"Bearer {tok(client, 'rider@amicor.local')}"}
    ah = {"Authorization": f"Bearer {tok(client, 'admin@amicor.local')}"}

    clear_driver(client, dh)

    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    name = f"BILL_SYNC_{stamp}"
    phone = f"647{stamp[-7:]}"[-10:]
    created = client.post(
        "/api/health-isf/customer-requests",
        headers=rh,
        json={
            "rider_name": name,
            "rider_phone": phone,
            "pickup_address": "10 Billing Sync Ave, Minneapolis, MN 55411",
            "dropoff_address": "20 Billing Sync St, Minneapolis, MN 55415",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "billing module sync verification",
        },
    )
    created.raise_for_status()
    body = created.json()
    ride_id = str(body.get("ride_id") or "")
    req_id = str(body.get("id") or "")
    print(f"CREATED {ride_id} {name}", flush=True)

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
                raise RuntimeError(f"assign failed {assign.status_code} {reassign.status_code}")

    for _ in range(20):
        ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
        if str(ride.get("driver_id") or "") == DRIVER:
            break
        time.sleep(0.4)

    accept = client.post(
        f"/api/health-isf/drivers/{DRIVER}/accept-ride",
        headers=dh,
        json={"ride_id": ride_id},
    )
    if accept.status_code >= 400:
        raise RuntimeError(f"accept failed: {accept.status_code} {accept.text[:300]}")
    for step in ("arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
        resp = client.post(
            f"/api/health-isf/drivers/{DRIVER}/route-progress",
            headers=dh,
            json={"ride_id": ride_id, "target_state": step},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"{step} failed: {resp.status_code} {resp.text[:300]}")
    complete = client.post(
        f"/api/health-isf/drivers/{DRIVER}/dropoff-complete",
        headers=dh,
        json={"ride_id": ride_id},
    )
    if complete.status_code >= 400:
        raise RuntimeError(f"complete failed: {complete.status_code} {complete.text[:400]}")
    print(f"COMPLETED {ride_id}", flush=True)
    time.sleep(1.0)

    fin = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=dh)
    finj = fin.json() if fin.status_code < 400 else {}
    docs_ride = client.get(f"/api/health-isf/rides/{ride_id}/trip-documents", headers=dh).json()
    billing = client.get(
        "/api/health-isf/operations/billing-handoffs", headers=dh, params={"limit": 200}
    ).json()
    rev = client.get("/api/health-isf/operations/admin-revenue", headers=ah).json()
    earn = client.get(f"/api/health-isf/drivers/{DRIVER}/earnings", headers=dh).json()
    snap = client.get(
        f"/api/health-isf/drivers/{DRIVER}/completion-snapshot",
        headers=dh,
        params={"limit": 50},
    ).json()
    completed = client.get(
        f"/api/health-isf/drivers/{DRIVER}/completed-rides",
        headers=dh,
        params={"limit": 50},
    ).json()
    hist = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=dh,
        params={"rider_phone": phone, "limit": 30},
    ).json()
    queue = client.get("/api/health-isf/dispatch/queue", headers=dh, params={"limit": 300}).json()
    active = client.get(
        "/api/health-isf/dispatch/active-assignments", headers=dh, params={"limit": 300}
    ).json()
    docs_org = client.get(
        "/api/health-isf/operations/trip-documents", headers=dh, params={"limit": 200}
    ).json()

    bill_row = next((b for b in billing if str(b.get("ride_id")) == ride_id), None)
    hist_row = next((h for h in hist.get("history", []) if str(h.get("ride_id")) == ride_id), None)
    in_completed = any(str(r.get("id")) == ride_id for r in completed)
    in_snap = any(str(r.get("id")) == ride_id for r in snap.get("completed_rides", []))
    in_queue = any(str(q.get("ride_id")) == ride_id for q in queue)
    in_active = any(str(a.get("ride_id")) == ride_id for a in active)
    docs_for_ride = [d for d in docs_org if str(d.get("ride_id")) == ride_id]
    snap_docs = [d for d in snap.get("documents", []) if str(d.get("ride_id")) == ride_id]

    fare = float((finj or {}).get("ride_price_usd") or (bill_row or {}).get("fare_amount") or 0)
    driver_pay = float((finj or {}).get("driver_pay_usd") or (bill_row or {}).get("driver_pay") or 0)
    platform = float(
        (finj or {}).get("platform_revenue_usd") or (bill_row or {}).get("platform_revenue") or 0
    )

    checks = {
        "ride_completed": str(
            client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json().get("lifecycle_state")
            or ""
        ).lower()
        == "completed",
        "financial_summary": bool(finj.get("financial_record_id")),
        "billing_handoff": bill_row is not None,
        "payment_record": bool(
            (finj or {}).get("payment_transaction_id")
            or (bill_row or {}).get("payment_transaction_id")
        ),
        "payout_record": bool((finj or {}).get("payout_id") or (bill_row or {}).get("payout_id")),
        "fare_matches_billing": bill_row is not None
        and abs(float(bill_row.get("fare_amount") or 0) - fare) < 0.01,
        "pay_matches_billing": bill_row is not None
        and abs(float(bill_row.get("driver_pay") or 0) - driver_pay) < 0.01,
        "platform_matches_billing": bill_row is not None
        and abs(float(bill_row.get("platform_revenue") or 0) - platform) < 0.01,
        "driver_history": in_completed and in_snap,
        "rider_history_completed": hist_row is not None
        and str(hist_row.get("dispatch_status") or "").lower() == "completed",
        "docs_generated": len(docs_ride) >= 3 and len(docs_for_ride) >= 3 and len(snap_docs) >= 3,
        "removed_from_dispatch_queue": not in_queue,
        "removed_from_ai_active": not in_active,
        "admin_revenue_includes_completed": int(rev.get("completed_trip_count") or 0) >= 1,
        "earnings_lifetime_positive": float(earn.get("earnings_lifetime_usd") or 0) > 0,
    }

    report = {
        "ride_id": ride_id,
        "passenger": name,
        "fare": fare,
        "driver_pay": driver_pay,
        "platform": platform,
        "doc_types": sorted({str(d.get("document_type")) for d in docs_for_ride}),
        "admin_completed_trip_count": rev.get("completed_trip_count"),
        "admin_platform_revenue": rev.get("platform_revenue_total_usd"),
        "admin_ride_revenue": rev.get("ride_revenue_total_usd"),
        "driver_earnings_lifetime": earn.get("earnings_lifetime_usd"),
        "driver_trip_count": earn.get("trip_count"),
        "billing_total": len(billing),
        "checks": checks,
        "PASS": all(checks.values()),
    }
    print(json.dumps(report, indent=2), flush=True)
    print(f"RESULT={'PASS' if report['PASS'] else 'FAIL'}", flush=True)
    return 0 if report["PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
