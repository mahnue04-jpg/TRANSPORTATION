"""Three consecutive production rides with cross-module sync validation.

No proof-only naming. Uses real rider intake → AI/auto assignment → driver
lifecycle → billing/earnings/history/queue checks after each ride.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PWD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
# Prefer James Smith — clean available driver for consecutive production runs.
DRIVER_ID = os.getenv("AMICOR_PROD_DRIVER_ID", "4bc0e517-d60d-4d45-bc20-a14b1e4aa407")


def _tok(client: httpx.Client, email: str) -> str:
    body = client.post("/api/auth/login", json={"email": email, "password": PWD}).json()
    return str(body.get("token") or body.get("access_token"))


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _norm(v: object) -> str:
    return str(v or "").strip().lower().replace("ridestatus.", "").replace("driverstatus.", "")


def cancel_stale_orphans(client: httpx.Client, headers: dict) -> list[str]:
    """Cancel non-terminal orphan rides that block consecutive production runs."""
    rides = client.get("/api/health-isf/rides", headers=headers, params={"limit": 300}).json()
    cancelled: list[str] = []
    for ride in rides:
        ride_id = str(ride.get("id") or "")
        lifecycle = _norm(ride.get("lifecycle_state") or ride.get("status"))
        if lifecycle in {"completed", "cancelled", "failed"}:
            continue
        passenger = str(ride.get("passenger_name") or "")
        if passenger.upper().startswith("PROD_SYNC_"):
            continue
        resp = client.patch(
            f"/api/health-isf/dispatcher/rides/{ride_id}/cancel",
            headers=headers,
            params={"reason": "orphan_assignment_cleanup_before_production_sync"},
        )
        if resp.status_code >= 400:
            print(f"STALE_CANCEL_FAIL {ride_id} {resp.status_code} {resp.text[:160]}", flush=True)
            continue
        cancelled.append(ride_id)
        print(f"STALE_CANCELLED {ride_id} {passenger} {lifecycle}", flush=True)
    return cancelled


def clear_driver(client: httpx.Client, headers: dict, driver_id: str) -> None:
    for _ in range(8):
        active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=headers).json()
        if not active.get("has_active_ride"):
            assigned = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides", headers=headers).json()
            if not assigned:
                break
            ride_id = str(assigned[0].get("id") or "")
        else:
            ride_id = str(
                (active.get("ride") or {}).get("id")
                or (active.get("active_assignment") or {}).get("ride_id")
                or ""
            )
        if not ride_id:
            break
        client.post(
            f"/api/health-isf/drivers/{driver_id}/accept-ride",
            headers=headers,
            json={"ride_id": ride_id},
        )
        for step in ("arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
            client.post(
                f"/api/health-isf/drivers/{driver_id}/route-progress",
                headers=headers,
                json={"ride_id": ride_id, "target_state": step},
            )
        client.post(
            f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
            headers=headers,
            json={"ride_id": ride_id},
        )
        time.sleep(0.3)


def create_and_assign(
    client: httpx.Client,
    rider_headers: dict,
    dispatcher_headers: dict,
    *,
    driver_id: str,
    index: int,
) -> tuple[str, str, str]:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    phone = f"646{index}{stamp[-6:]}"[-10:]
    name = f"PROD_SYNC_{index}_{stamp}"
    created = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": name,
            "rider_phone": phone,
            "pickup_address": f"{100 + index} Production Pickup Ave, Minneapolis, MN 55411",
            "dropoff_address": f"{200 + index} Production Dropoff St, Minneapolis, MN 55415",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": f"production sync consecutive ride {index}",
        },
    )
    created.raise_for_status()
    body = created.json()
    ride_id = str(body.get("ride_id") or "")
    req_id = str(body.get("id") or "")
    if not ride_id or not req_id:
        raise RuntimeError(f"create missing ids: {body}")

    # Allow intake auto-assign a moment, then ensure AI/dispatcher assignment to target driver.
    time.sleep(1.0)
    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers).json()
    if str(ride.get("driver_id") or "") != driver_id:
        # Approve if needed, then assign / reassign to production driver.
        client.post(
            f"/api/health-isf/dispatcher/customer-requests/{req_id}/approve",
            headers=dispatcher_headers,
        )
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{req_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        if assign.status_code >= 400:
            reassign = client.patch(
                f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
                headers=dispatcher_headers,
                json={"driver_id": driver_id},
            )
            if reassign.status_code >= 400:
                raise RuntimeError(
                    f"assign failed: {assign.status_code} {assign.text[:200]} | "
                    f"{reassign.status_code} {reassign.text[:200]}"
                )

    for _ in range(20):
        ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers).json()
        if str(ride.get("driver_id") or "") == driver_id:
            break
        time.sleep(0.5)
    if str(ride.get("driver_id") or "") != driver_id:
        raise RuntimeError(f"ride {ride_id} not assigned to {driver_id}")
    return ride_id, phone, name


def run_driver_lifecycle(client: httpx.Client, headers: dict, driver_id: str, ride_id: str) -> None:
    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    )
    if accept.status_code >= 400:
        raise RuntimeError(f"accept failed: {accept.status_code} {accept.text[:300]}")
    for step in ("arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
        resp = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": step},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"route-progress {step}: {resp.status_code} {resp.text[:300]}")
    complete = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    if complete.status_code >= 400:
        raise RuntimeError(f"dropoff-complete: {complete.status_code} {complete.text[:300]}")


def snapshot_modules(
    client: httpx.Client,
    headers: dict,
    *,
    driver_id: str,
    ride_ids: list[str],
    phones: dict[str, str],
) -> dict:
    ride_rows = {
        rid: client.get(f"/api/health-isf/rides/{rid}", headers=headers).json() for rid in ride_ids
    }
    earn = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=headers).json()
    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=headers).json()
    assigned = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides", headers=headers).json()
    completed = client.get(
        f"/api/health-isf/drivers/{driver_id}/completed-rides",
        headers=headers,
        params={"limit": 100},
    ).json()
    billing = client.get(
        "/api/health-isf/operations/billing-handoffs",
        headers=headers,
        params={"limit": 200},
    ).json()
    rev = client.get("/api/health-isf/operations/admin-revenue", headers=headers).json()
    queue = client.get("/api/health-isf/dispatch/queue", headers=headers, params={"limit": 300}).json()
    active_assignments = client.get(
        "/api/health-isf/dispatch/active-assignments",
        headers=headers,
        params={"limit": 300},
    ).json()
    driver = client.get(f"/api/health-isf/drivers/{driver_id}", headers=headers).json()

    completed_ids = [str(r.get("id") or "") for r in completed]
    billing_for_rides = [b for b in billing if str(b.get("ride_id") or "") in set(ride_ids)]
    queue_for_rides = [q for q in queue if str(q.get("ride_id") or "") in set(ride_ids)]
    active_for_rides = [a for a in active_assignments if str(a.get("ride_id") or "") in set(ride_ids)]

    rider_hist_completed = 0
    for rid, phone in phones.items():
        hist = client.get(
            "/api/health-isf/customers/workspace/history",
            headers=headers,
            params={"rider_phone": phone, "limit": 30},
        ).json()
        row = next((h for h in hist.get("history", []) if str(h.get("ride_id") or "") == rid), None)
        if row and _norm(row.get("dispatch_status")) == "completed":
            rider_hist_completed += 1

    # Stale scan across DB-facing APIs
    all_rides = client.get("/api/health-isf/rides", headers=headers, params={"limit": 300}).json()
    stale_states = []
    for ride in all_rides:
        rid = str(ride.get("id") or "")
        lifecycle = _norm(ride.get("lifecycle_state") or ride.get("status"))
        if lifecycle == "completed":
            # completed must not appear as active/assigned/reassignment_pending
            continue
        if rid in set(ride_ids) and lifecycle not in {"completed", "cancelled", "failed"}:
            stale_states.append((rid, lifecycle, ride.get("status")))

    # assignment stale for completed production rides
    reassignment_pending_completed = []
    for rid in ride_ids:
        for row in active_assignments:
            if str(row.get("ride_id") or "") == rid:
                reassignment_pending_completed.append(rid)
        # also check queue assignment_state
        for row in queue:
            if str(row.get("ride_id") or "") == rid and _norm(row.get("assignment_state")) in {
                "reassignment_pending",
                "assigned",
                "accepted",
                "offered",
            }:
                reassignment_pending_completed.append(rid)

    billing_ride_ids = [str(b.get("ride_id") or "") for b in billing_for_rides]
    billing_dupes = [rid for rid, count in Counter(billing_ride_ids).items() if count > 1]
    completed_dupes = [rid for rid, count in Counter(completed_ids).items() if count > 1 and rid in set(ride_ids)]

    return {
        "ride_rows": {rid: _norm(row.get("lifecycle_state") or row.get("status")) for rid, row in ride_rows.items()},
        "driver_status": _norm(driver.get("status")),
        "driver_available": _norm(driver.get("status")) == "available",
        "active_cleared": not bool(active.get("has_active_ride")),
        "assigned_cleared": len(assigned) == 0,
        "earnings_lifetime": float(earn.get("earnings_lifetime_usd") or 0),
        "earnings_today": float(earn.get("earnings_today_usd") or 0),
        "trip_count": int(earn.get("trip_count") or 0),
        "trip_count_today": int(earn.get("trip_count_today") or 0),
        "completed_ids": completed_ids,
        "completed_contains_all": all(rid in completed_ids for rid in ride_ids),
        "billing_count_for_rides": len(billing_for_rides),
        "billing_ready_all": all(_norm(b.get("billing_status")) == "ready" for b in billing_for_rides)
        and len(billing_for_rides) == len(ride_ids),
        "billing_dupes": billing_dupes,
        "completed_dupes": completed_dupes,
        "platform_revenue": float(rev.get("platform_revenue_total_usd") or 0),
        "gross_revenue": float(rev.get("ride_revenue_total_usd") or 0),
        "queue_contains_any": len(queue_for_rides) > 0,
        "active_assignment_contains_any": len(active_for_rides) > 0,
        "rider_hist_completed": rider_hist_completed,
        "stale_production_states": stale_states,
        "reassignment_pending_completed": sorted(set(reassignment_pending_completed)),
        "billing_total": len(billing),
        "queue_total": len(queue),
        "active_assignment_total": len(active_assignments),
    }


def verify_ride(
    snap: dict,
    *,
    ride_id: str,
    before_earnings: float,
    before_platform: float,
    before_trips: int,
    expected_completed_count: int,
) -> dict[str, bool]:
    return {
        "ride_completed": snap["ride_rows"].get(ride_id) == "completed",
        "dispatch_queue_removed": ride_id not in [
            # reconstructed via queue_contains_any for all rides; per-ride checked below
        ]
        or True,  # placeholder replaced in caller
        "driver_available": snap["driver_available"],
        "active_cleared": snap["active_cleared"],
        "assigned_cleared": snap["assigned_cleared"],
        "earnings_increased": snap["earnings_lifetime"] > before_earnings,
        "platform_increased": snap["platform_revenue"] > before_platform,
        "trip_count_increased": snap["trip_count"] > before_trips,
        "completed_history_has_ride": ride_id in snap["completed_ids"],
        "billing_ready_all_so_far": snap["billing_ready_all"]
        or snap["billing_count_for_rides"] >= expected_completed_count,
        "rider_hist_ok": snap["rider_hist_completed"] >= expected_completed_count,
        "no_queue_for_completed_set": not snap["queue_contains_any"],
        "no_active_assignment_for_completed_set": not snap["active_assignment_contains_any"],
        "no_billing_dupes": len(snap["billing_dupes"]) == 0,
        "no_completed_dupes": len(snap["completed_dupes"]) == 0,
        "no_reassignment_pending": len(snap["reassignment_pending_completed"]) == 0,
        "no_stale_production": len(snap["stale_production_states"]) == 0,
    }


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120)
    dh = _hdr(_tok(client, "dispatcher@amicor.local"))
    rh = _hdr(_tok(client, "rider@amicor.local"))

    print("=== ORPHAN CLEANUP ===", flush=True)
    cancelled = cancel_stale_orphans(client, dh)
    clear_driver(client, dh, DRIVER_ID)
    print(f"cancelled_orphans={len(cancelled)}", flush=True)

    baseline = snapshot_modules(client, dh, driver_id=DRIVER_ID, ride_ids=[], phones={})
    print(
        "BASELINE",
        json.dumps(
            {
                "earnings": baseline["earnings_lifetime"],
                "trips": baseline["trip_count"],
                "platform": baseline["platform_revenue"],
                "billing_total": baseline["billing_total"],
                "queue_total": baseline["queue_total"],
                "driver": baseline["driver_status"],
            },
            indent=2,
        ),
        flush=True,
    )

    ride_ids: list[str] = []
    phones: dict[str, str] = {}
    names: dict[str, str] = {}
    results: list[dict] = []

    for index in (1, 2, 3):
        print(f"\n=== RIDE {index} ===", flush=True)
        before_earn = float(
            client.get(f"/api/health-isf/drivers/{DRIVER_ID}/earnings", headers=dh).json().get(
                "earnings_lifetime_usd"
            )
            or 0
        )
        before_platform = float(
            client.get("/api/health-isf/operations/admin-revenue", headers=dh).json().get(
                "platform_revenue_total_usd"
            )
            or 0
        )
        before_trips = int(
            client.get(f"/api/health-isf/drivers/{DRIVER_ID}/earnings", headers=dh).json().get("trip_count")
            or 0
        )

        ride_id, phone, name = create_and_assign(
            client, rh, dh, driver_id=DRIVER_ID, index=index
        )
        ride_ids.append(ride_id)
        phones[ride_id] = phone
        names[ride_id] = name
        print(f"CREATED {ride_id} {name}", flush=True)

        run_driver_lifecycle(client, dh, DRIVER_ID, ride_id)
        print(f"COMPLETED_LIFECYCLE {ride_id}", flush=True)
        time.sleep(0.8)

        snap = snapshot_modules(
            client, dh, driver_id=DRIVER_ID, ride_ids=ride_ids, phones=phones
        )
        queue = client.get("/api/health-isf/dispatch/queue", headers=dh, params={"limit": 300}).json()
        checks = {
            "ride_completed": snap["ride_rows"].get(ride_id) == "completed",
            "dispatch_queue_removed": not any(str(q.get("ride_id") or "") == ride_id for q in queue),
            "driver_available": snap["driver_available"],
            "active_cleared": snap["active_cleared"],
            "assigned_cleared": snap["assigned_cleared"],
            "earnings_increased": snap["earnings_lifetime"] > before_earn,
            "platform_increased": snap["platform_revenue"] > before_platform,
            "trip_count_increased": snap["trip_count"] > before_trips,
            "completed_history_has_ride": ride_id in snap["completed_ids"],
            "billing_ready_for_all_so_far": snap["billing_count_for_rides"] == len(ride_ids)
            and snap["billing_ready_all"],
            "rider_hist_completed_all": snap["rider_hist_completed"] == len(ride_ids),
            "ai_active_queue_cleared": not snap["queue_contains_any"]
            and not snap["active_assignment_contains_any"],
            "no_billing_dupes": len(snap["billing_dupes"]) == 0,
            "no_completed_dupes": len(snap["completed_dupes"]) == 0,
            "no_reassignment_pending": len(snap["reassignment_pending_completed"]) == 0,
            "no_stale_production": len(snap["stale_production_states"]) == 0,
        }
        ok = all(checks.values())
        results.append(
            {
                "index": index,
                "ride_id": ride_id,
                "passenger": name,
                "pass": ok,
                "checks": checks,
                "snap": {
                    "earnings": snap["earnings_lifetime"],
                    "trips": snap["trip_count"],
                    "platform": snap["platform_revenue"],
                    "billing_for_rides": snap["billing_count_for_rides"],
                    "rider_hist": snap["rider_hist_completed"],
                    "completed_contains_all": snap["completed_contains_all"],
                },
            }
        )
        print(f"RIDE_{index} {'PASS' if ok else 'FAIL'}", json.dumps(checks, indent=2), flush=True)
        if not ok:
            print("SNAP_DETAIL", json.dumps(snap, indent=2, default=str)[:2500], flush=True)
            # Continue to attempt remaining rides only if we can recover driver.
            clear_driver(client, dh, DRIVER_ID)

    final = snapshot_modules(client, dh, driver_id=DRIVER_ID, ride_ids=ride_ids, phones=phones)
    # Cross-module equality for the three production rides
    module_counts = {
        "driver_completed_trips_for_set": sum(1 for rid in ride_ids if rid in final["completed_ids"]),
        "billing_handoffs_for_set": final["billing_count_for_rides"],
        "rider_history_completed_for_set": final["rider_hist_completed"],
        "dispatch_queue_for_set": 0 if not final["queue_contains_any"] else -1,
        "ai_active_for_set": 0 if not final["active_assignment_contains_any"] else -1,
    }
    expected = len(ride_ids)
    counts_match = (
        module_counts["driver_completed_trips_for_set"] == expected
        and module_counts["billing_handoffs_for_set"] == expected
        and module_counts["rider_history_completed_for_set"] == expected
        and module_counts["dispatch_queue_for_set"] == 0
        and module_counts["ai_active_for_set"] == 0
        and len(final["billing_dupes"]) == 0
        and len(final["completed_dupes"]) == 0
        and len(final["reassignment_pending_completed"]) == 0
    )

    print("\n=== FINAL REPORT ===", flush=True)
    for row in results:
        print(f"Ride {row['index']} {'PASS' if row['pass'] else 'FAIL'} ride_id={row['ride_id']} passenger={row['passenger']}")
    print(f"Driver Earnings Total={final['earnings_lifetime']}")
    print(f"Platform Revenue Total={final['platform_revenue']}")
    print(f"Completed Ride Count (driver API)={final['trip_count']}")
    print(f"Billing Count (all)={final['billing_total']}")
    print(f"History Count (driver completed list)={len(final['completed_ids'])}")
    print(f"Production set completed={module_counts['driver_completed_trips_for_set']}")
    print(f"Production set billing={module_counts['billing_handoffs_for_set']}")
    print(f"Production set rider history={module_counts['rider_history_completed_for_set']}")
    print(f"Dispatch queue remaining for set={module_counts['dispatch_queue_for_set']}")
    print(f"AI/active assignments remaining for set={module_counts['ai_active_for_set']}")
    print(f"MODULE_COUNTS_MATCH={'YES' if counts_match else 'NO'}")
    all_pass = all(r["pass"] for r in results) and counts_match and len(results) == 3
    print(f"RESULT={'PASS' if all_pass else 'FAIL'}")
    print(
        json.dumps(
            {
                "ride_ids": ride_ids,
                "names": names,
                "module_counts": module_counts,
                "final": {
                    "earnings": final["earnings_lifetime"],
                    "platform": final["platform_revenue"],
                    "trips": final["trip_count"],
                    "billing_total": final["billing_total"],
                    "history_count": len(final["completed_ids"]),
                },
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
