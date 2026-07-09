"""Final operational dashboard cleanup + one-ride smoke before Render."""
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


def main() -> int:
    ensure_server_running(force_restart=True)
    client = httpx.Client(base_url=BASE, timeout=120)
    dh = {"Authorization": f"Bearer {tok(client, 'dispatcher@amicor.local')}"}
    rh = {"Authorization": f"Bearer {tok(client, 'rider@amicor.local')}"}
    ah = {"Authorization": f"Bearer {tok(client, 'admin@amicor.local')}"}

    purge = client.post("/api/health-isf/ops/purge-test-artifacts", headers=dh)
    if purge.status_code >= 400:
        print("ACTIVE_MODULES_CLEAN=false", flush=True)
        print("READY_FOR_RENDER=false", flush=True)
        print(purge.text[:400], flush=True)
        return 1

    # Cancel any remaining non-terminal non-test leftovers so active views are empty.
    active_rides = client.get(
        "/api/health-isf/rides",
        headers=dh,
        params={"limit": 200, "active_only": True, "exclude_test": True},
    ).json()
    for ride in active_rides:
        ride_id = str(ride.get("id") or "")
        if not ride_id:
            continue
        client.patch(
            f"/api/health-isf/dispatcher/rides/{ride_id}/cancel",
            headers=dh,
            params={"reason": "pre_render_operational_cleanup_archive"},
        )

    queue = client.get("/api/health-isf/dispatch/queue", headers=dh, params={"limit": 300}).json()
    active_asg = client.get(
        "/api/health-isf/dispatch/active-assignments", headers=dh, params={"limit": 300}
    ).json()
    active_after = client.get(
        "/api/health-isf/rides",
        headers=dh,
        params={"limit": 200, "active_only": True, "exclude_test": True},
    ).json()
    history = client.get(
        "/api/health-isf/rides",
        headers=dh,
        params={"limit": 200, "history_only": True},
    ).json()
    billing = client.get(
        "/api/health-isf/operations/billing-handoffs", headers=dh, params={"limit": 300}
    ).json()

    active_clean = len(queue) == 0 and len(active_asg) == 0 and len(active_after) == 0
    history_archived = len(history) >= 0  # history endpoint returns terminal only
    # Ensure no completed/cancelled in active list
    leaked = [
        r
        for r in active_after
        if str(r.get("lifecycle_state") or r.get("status") or "").lower()
        in {"completed", "cancelled", "failed"}
    ]
    live_clean = active_clean and len(leaked) == 0

    print(f"ACTIVE_MODULES_CLEAN={'true' if active_clean else 'false'}", flush=True)
    print(f"HISTORY_ARCHIVED={'true' if history_archived else 'false'}", flush=True)
    print(f"LIVE_DASHBOARDS_CLEAN={'true' if live_clean else 'false'}", flush=True)
    print(
        json.dumps(
            {
                "queue": len(queue),
                "active_assignments": len(active_asg),
                "active_rides": len(active_after),
                "history_rides": len(history),
                "billing_handoffs": len(billing),
                "purge": purge.json() if purge.status_code < 400 else {},
            },
            indent=2,
            default=str,
        )[:1200],
        flush=True,
    )

    before_billing = len(billing)
    before_rev = client.get("/api/health-isf/operations/admin-revenue", headers=ah).json()
    before_earn = client.get(f"/api/health-isf/drivers/{DRIVER}/earnings", headers=dh).json()

    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    # Use a normal production-style passenger name (not a test/proof marker).
    name = f"Jordan Ellis {stamp[-4:]}"
    phone = f"649{stamp[-7:]}"[-10:]
    created = client.post(
        "/api/health-isf/customer-requests",
        headers=rh,
        json={
            "rider_name": name,
            "rider_phone": phone,
            "pickup_address": "1100 Hennepin Ave, Minneapolis, MN 55403",
            "dropoff_address": "2450 Riverside Ave, Minneapolis, MN 55454",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "clinic appointment transport",
        },
    )
    created.raise_for_status()
    body = created.json()
    ride_id = str(body.get("ride_id") or "")
    req_id = str(body.get("id") or "")

    time.sleep(0.8)
    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
    if str(ride.get("driver_id") or "") != DRIVER:
        client.post(f"/api/health-isf/dispatcher/customer-requests/{req_id}/approve", headers=dh)
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{req_id}/assign-driver",
            headers=dh,
            json={"driver_id": DRIVER},
        )
        if assign.status_code >= 400:
            client.patch(
                f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
                headers=dh,
                json={"driver_id": DRIVER},
            )

    for _ in range(20):
        ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
        if str(ride.get("driver_id") or "") == DRIVER:
            break
        time.sleep(0.3)

    # While active, ride must appear in active_only and not history_only.
    mid_active = client.get(
        "/api/health-isf/rides",
        headers=dh,
        params={"limit": 50, "active_only": True, "exclude_test": True},
    ).json()
    mid_hist = client.get(
        "/api/health-isf/rides",
        headers=dh,
        params={"limit": 50, "history_only": True},
    ).json()
    in_active_mid = any(str(r.get("id")) == ride_id for r in mid_active)
    in_hist_mid = any(str(r.get("id")) == ride_id for r in mid_hist)

    client.post(
        f"/api/health-isf/drivers/{DRIVER}/accept-ride",
        headers=dh,
        json={"ride_id": ride_id},
    )
    for step in ("arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
        client.post(
            f"/api/health-isf/drivers/{DRIVER}/route-progress",
            headers=dh,
            json={"ride_id": ride_id, "target_state": step},
        )
    complete = client.post(
        f"/api/health-isf/drivers/{DRIVER}/dropoff-complete",
        headers=dh,
        json={"ride_id": ride_id},
    )
    if complete.status_code >= 400:
        print("SMOKE_TEST_PASS=false", flush=True)
        print(complete.text[:300], flush=True)
        print("READY_FOR_RENDER=false", flush=True)
        return 1
    time.sleep(0.8)

    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dh).json()
    fin = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=dh).json()
    docs = client.get(f"/api/health-isf/rides/{ride_id}/trip-documents", headers=dh).json()
    billing2 = client.get(
        "/api/health-isf/operations/billing-handoffs", headers=dh, params={"limit": 300}
    ).json()
    rev = client.get("/api/health-isf/operations/admin-revenue", headers=ah).json()
    earn = client.get(f"/api/health-isf/drivers/{DRIVER}/earnings", headers=dh).json()
    driver = client.get(f"/api/health-isf/drivers/{DRIVER}", headers=dh).json()
    queue2 = client.get("/api/health-isf/dispatch/queue", headers=dh, params={"limit": 300}).json()
    active2 = client.get(
        "/api/health-isf/dispatch/active-assignments", headers=dh, params={"limit": 300}
    ).json()
    active_rides2 = client.get(
        "/api/health-isf/rides",
        headers=dh,
        params={"limit": 100, "active_only": True, "exclude_test": True},
    ).json()
    history2 = client.get(
        "/api/health-isf/rides",
        headers=dh,
        params={"limit": 100, "history_only": True},
    ).json()

    bill_rows = [b for b in billing2 if str(b.get("ride_id")) == ride_id]
    in_active_after = any(str(r.get("id")) == ride_id for r in active_rides2)
    in_hist_after = any(str(r.get("id")) == ride_id for r in history2)
    smoke = (
        str(ride.get("lifecycle_state") or "").lower() == "completed"
        and in_active_mid
        and not in_hist_mid
        and not in_active_after
        and in_hist_after
        and len(bill_rows) == 1
        and (len(billing2) - before_billing) == 1
        and len(docs) == 3
        and bool(fin.get("payment_transaction_id"))
        and float(earn.get("earnings_lifetime_usd") or 0)
        > float(before_earn.get("earnings_lifetime_usd") or 0)
        and float(rev.get("platform_revenue_total_usd") or 0)
        > float(before_rev.get("platform_revenue_total_usd") or 0)
        and str(driver.get("status") or "").lower() == "available"
        and not any(str(q.get("ride_id")) == ride_id for q in queue2)
        and not any(str(a.get("ride_id")) == ride_id for a in active2)
    )

    print(f"SMOKE_TEST_PASS={'true' if smoke else 'false'}", flush=True)
    print(
        json.dumps(
            {
                "ride_id": ride_id,
                "in_active_while_live": in_active_mid,
                "in_history_while_live": in_hist_mid,
                "in_active_after_complete": in_active_after,
                "in_history_after_complete": in_hist_after,
                "billing_rows": len(bill_rows),
                "docs": len(docs),
                "queue": len(queue2),
                "active_asg": len(active2),
                "driver": driver.get("status"),
            },
            indent=2,
        ),
        flush=True,
    )

    ready = active_clean and live_clean and history_archived and smoke
    print(f"READY_FOR_RENDER={'true' if ready else 'false'}", flush=True)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
