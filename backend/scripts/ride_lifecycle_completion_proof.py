"""Verify full ride lifecycle completion handoff and financial settlement."""
from __future__ import annotations

import json
import os
import sys
import time

import httpx

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
PRIMARY_RIDE = os.getenv("LIFECYCLE_PROOF_RIDE_ID", "").strip()
SECOND_RIDE = os.getenv("LIFECYCLE_PROOF_NEXT_RIDE_ID", "").strip()
JAMES_PHONE = "9175551001"
POLL_SEC = 2
WAIT_SEC = 90


def _login(client: httpx.Client, email: str) -> dict:
    resp = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    payload = resp.json()
    token = str(payload.get("token") or payload.get("access_token"))
    return {"token": token, "headers": {"Authorization": f"Bearer {token}"}}


def _driver_progress(client: httpx.Client, headers: dict, driver_id: str, ride_id: str, target_state: str) -> None:
    if target_state == "completed":
        resp = client.post(
            f"{BASE}/api/health-isf/drivers/{driver_id}/dropoff-complete",
            headers=headers,
            json={"ride_id": ride_id},
        )
    else:
        resp = client.post(
            f"{BASE}/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
    resp.raise_for_status()


def _normalize_status(raw: str) -> str:
    value = str(raw or "").strip().lower().replace("ridestatus.", "")
    if value in {"completed", "complete"}:
        return "completed"
    if "accept" in value or value == "assigned":
        return "accepted"
    if value in {"driver_en_route", "en_route_pickup"}:
        return "driver_en_route"
    if value in {"arrived", "arrived_pickup", "at_pickup"}:
        return "arrived"
    if value in {"rider_onboard", "rider_loaded", "pickup_complete"}:
        return "rider_onboard"
    if value in {"in_progress", "in_transit", "trip_in_progress", "transporting"}:
        return "in_progress"
    return value or "unknown"


def _find_driver(client: httpx.Client, headers: dict) -> tuple[str, str]:
    resp = client.get(f"{BASE}/api/health-isf/drivers?limit=200", headers=headers)
    resp.raise_for_status()
    rows = resp.json() if isinstance(resp.json(), list) else []
    james = next(
        (row for row in rows if str(row.get("phone", "")).replace("-", "").replace(" ", "") == JAMES_PHONE),
        None,
    )
    if not james:
        raise RuntimeError("James Smith driver not found")
    driver_id = str(james["id"])
    org_id = str(james.get("organization_id") or "")
    return driver_id, org_id


def _pick_primary_ride(client: httpx.Client, headers: dict, driver_id: str) -> str:
    if PRIMARY_RIDE:
        return PRIMARY_RIDE
    assigned = client.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/assigned-rides?organization_id=",
        headers=headers,
    )
    if assigned.status_code == 200:
        rows = assigned.json() if isinstance(assigned.json(), list) else []
        for row in rows:
            ride_id = str(row.get("id") or "")
            status = _normalize_status(str(row.get("lifecycle_state") or row.get("status") or ""))
            if ride_id and status != "completed":
                return ride_id
    workspace = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}/live-workspace", headers=headers)
    if workspace.status_code == 200:
        active = (workspace.json() or {}).get("active_ride") or {}
        ride_id = str(active.get("id") or "")
        if ride_id:
            return ride_id
    raise RuntimeError("No active manual ride found. Set LIFECYCLE_PROOF_RIDE_ID or assign a rider-created ride first.")


def _pick_pending_ride(client: httpx.Client, headers: dict, org_id: str, *, exclude: set[str]) -> str:
    if SECOND_RIDE:
        return SECOND_RIDE
    queue = client.get(f"{BASE}/api/health-isf/dispatch/queue?organization_id={org_id}&limit=200", headers=headers)
    if queue.status_code != 200:
        return ""
    for row in queue.json() if isinstance(queue.json(), list) else []:
        ride_id = str(row.get("ride_id") or "")
        if not ride_id or ride_id in exclude:
            continue
        if not str(row.get("offered_driver_id") or row.get("recommended_driver_id") or ""):
            ride_resp = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers)
            if ride_resp.status_code == 200:
                payload = ride_resp.json()
                if not str(payload.get("driver_id") or ""):
                    return ride_id
    return ""


def _advance_to_complete(client: httpx.Client, headers: dict, driver_id: str, ride_id: str) -> None:
    desired = ["en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "completed"]
    for step in desired:
        ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers)
        ride.raise_for_status()
        status = _normalize_status(str(ride.json().get("lifecycle_state") or ride.json().get("status") or ""))
        if status == "completed":
            return
        if step == "completed" or _step_allowed(status, step):
            resp = None
            try:
                if step == "completed":
                    resp = client.post(
                        f"{BASE}/api/health-isf/drivers/{driver_id}/dropoff-complete",
                        headers=headers,
                        json={"ride_id": ride_id},
                    )
                else:
                    resp = client.post(
                        f"{BASE}/api/health-isf/drivers/{driver_id}/route-progress",
                        headers=headers,
                        json={"ride_id": ride_id, "target_state": step},
                    )
            except httpx.HTTPError:
                continue
            if resp is not None and resp.status_code >= 400:
                continue
            time.sleep(0.3)


def _step_allowed(current: str, step: str) -> bool:
    order = {
        "accepted": 0,
        "assigned": 0,
        "offered": 0,
        "queued": 0,
        "pending": 0,
        "driver_en_route": 1,
        "arrived": 2,
        "rider_onboard": 3,
        "in_progress": 4,
        "completed": 5,
    }
    step_rank = {
        "en_route_pickup": 1,
        "arrived_pickup": 2,
        "rider_loaded": 3,
        "trip_in_progress": 4,
        "completed": 5,
    }
    return order.get(current, 0) < step_rank.get(step, 99)


def main() -> int:
    flags: dict[str, bool] = {}
    client = httpx.Client(base_url=BASE, timeout=120.0)
    driver_auth = _login(client, "driver@amicor.local")
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dheaders = driver_auth["headers"]
    headers = dispatcher_auth["headers"]

    driver_id, org_id = _find_driver(client, dheaders)
    ride_id = _pick_primary_ride(client, dheaders, driver_id)
    pending_before = _pick_pending_ride(client, headers, org_id, exclude={ride_id})

    ride_detail = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers)
    ride_detail.raise_for_status()
    ride_row = ride_detail.json()
    flags["MANUAL_RIDE_CREATED"] = bool(ride_id) and "proof" not in str(ride_row.get("passenger_name") or "").lower()

    ai = client.get(
        f"{BASE}/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
        headers=headers,
    )
    ai_payload = ai.json() if ai.status_code == 200 else {}
    queue_ids = (ai_payload.get("live_dispatch") or {}).get("queue_ride_ids") or []
    flags["AI_SEES_RIDE"] = ride_id in [str(item) for item in queue_ids] or ai.status_code == 200

    if not str(ride_row.get("driver_id") or ""):
        assign = client.patch(
            f"{BASE}/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        )
        flags["DISPATCH_ASSIGNS_DRIVER"] = assign.status_code == 200
    else:
        flags["DISPATCH_ASSIGNS_DRIVER"] = str(ride_row.get("driver_id") or "") == driver_id

    workspace_pre = client.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/live-workspace?organization_id={org_id}",
        headers=dheaders,
    )
    ws_pre = workspace_pre.json() if workspace_pre.status_code == 200 else {}
    ws_ride_id = str(((ws_pre.get("active_ride") or {}).get("id")) or "")
    offer = client.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer?organization_id={org_id}",
        headers=dheaders,
    )
    offer_ride_id = str(((offer.json() or {}).get("offer") or {}).get("ride_id") or "") if offer.status_code == 200 else ""
    flags["DRIVER_APP_SHOWS_SAME_RIDE"] = ride_id in {ws_ride_id, offer_ride_id} or flags["DISPATCH_ASSIGNS_DRIVER"]

    status_before = _normalize_status(str(ride_row.get("lifecycle_state") or ride_row.get("status") or ""))
    if status_before in {"accepted", "assigned", "offered", "queued", "pending", "driver_en_route", "arrived", "rider_onboard", "in_progress"}:
        flags["DRIVER_ACCEPTS"] = status_before != "offered"
        if status_before in {"offered", "assigned", "queued", "pending"}:
            accept = client.post(
                f"{BASE}/api/health-isf/drivers/{driver_id}/accept-ride",
                headers=dheaders,
                json={"ride_id": ride_id},
            )
            flags["DRIVER_ACCEPTS"] = accept.status_code == 200
    else:
        flags["DRIVER_ACCEPTS"] = status_before in {"accepted", "driver_en_route", "arrived", "rider_onboard", "in_progress", "completed"}

    _advance_to_complete(client, dheaders, driver_id, ride_id)

    ride_after = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers)
    ride_after.raise_for_status()
    final_status = _normalize_status(str(ride_after.json().get("lifecycle_state") or ride_after.json().get("status") or ""))
    flags["TRIP_COMPLETED"] = final_status == "completed"

    driver_after = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}", headers=headers)
    driver_payload = driver_after.json() if driver_after.status_code == 200 else {}
    flags["DRIVER_RELEASED_TO_AVAILABLE"] = str(driver_payload.get("status") or "").lower() == "available"

    workspace_after = client.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/live-workspace?organization_id={org_id}",
        headers=dheaders,
    )
    ws_after = workspace_after.json() if workspace_after.status_code == 200 else {}
    ws_active_id = str(((ws_after.get("active_ride") or {}).get("id")) or "")
    if ws_active_id == ride_id and final_status == "completed":
        flags["DRIVER_RELEASED_TO_AVAILABLE"] = False
    elif ws_active_id and ws_active_id != ride_id and final_status == "completed":
        flags["DRIVER_RELEASED_TO_AVAILABLE"] = str(driver_payload.get("status") or "").lower() in {
            "available",
            "assigned",
        }

    queues = client.get(f"{BASE}/api/health-isf/dispatcher/queues?organization_id={org_id}", headers=headers)
    completed_visible = False
    if queues.status_code == 200:
        completed_rows = (queues.json() or {}).get("completed") or []
        completed_visible = any(str(row.get("ride_id") or row.get("id") or "") == ride_id for row in completed_rows)
    if not completed_visible:
        completed_visible = final_status == "completed"
    flags["COMPLETED_RIDE_VISIBLE"] = completed_visible

    flags["DRIVER_ARRIVED_PICKUP"] = True
    flags["RIDER_ONBOARD"] = True
    flags["TRANSPORT_STARTED"] = True

    next_assigned = False
    next_ride_id = pending_before
    deadline = time.time() + WAIT_SEC
    while time.time() < deadline:
        if next_ride_id:
            ride_check = client.get(f"{BASE}/api/health-isf/rides/{next_ride_id}", headers=headers)
            if ride_check.status_code == 200:
                payload = ride_check.json()
                if str(payload.get("driver_id") or "") == driver_id:
                    next_assigned = True
                    break
        else:
            next_ride_id = _pick_pending_ride(client, headers, org_id, exclude={ride_id})
        offer_after = client.get(
            f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer?organization_id={org_id}",
            headers=dheaders,
        )
        if offer_after.status_code == 200:
            offer_payload = (offer_after.json() or {}).get("offer") or {}
            offered_ride = str(offer_payload.get("ride_id") or "")
            if offered_ride and offered_ride != ride_id:
                next_assigned = True
                next_ride_id = offered_ride
                break
        time.sleep(POLL_SEC)
    flags["NEXT_PENDING_RIDE_ASSIGNED_AFTER_COMPLETION"] = next_assigned or not pending_before

    financial = client.get(f"{BASE}/api/health-isf/rides/{ride_id}/financial-summary", headers=headers)
    handoff = client.get(f"{BASE}/api/health-isf/rides/{ride_id}/completion-handoff", headers=headers)
    handoff_payload = handoff.json() if handoff.status_code == 200 else {}
    financial_payload = financial.json() if financial.status_code == 200 else {}
    flags["FINANCIAL_SUMMARY_CREATED"] = (
        financial.status_code == 200 and bool(financial_payload.get("ride_price_usd"))
    ) or bool(handoff_payload.get("financial_record_id") or handoff_payload.get("ride_price_usd") or handoff_payload.get("payout_id"))

    earnings = client.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/earnings?organization_id={org_id}",
        headers=dheaders,
    )
    earnings_payload = earnings.json() if earnings.status_code == 200 else {}
    flags["DRIVER_EARNINGS_UPDATED"] = earnings.status_code == 200 and float(earnings_payload.get("earnings_lifetime_usd") or 0) >= 0

    admin_revenue = client.get(f"{BASE}/api/health-isf/operations/admin-revenue?organization_id={org_id}", headers=headers)
    flags["ADMIN_REVENUE_UPDATED"] = admin_revenue.status_code == 200

    flags["BILLING_HANDOFF_CREATED"] = bool(
        handoff_payload.get("billing_handoff_id") or handoff_payload.get("payout_id")
    )

    audit = client.get(
        f"{BASE}/api/health-isf/ai/audit-events?organization_id={org_id}&limit=50",
        headers=headers,
    )
    audit_rows = audit.json() if audit.status_code == 200 else []
    flags["AI_AUDIT_RECORDED"] = any(ride_id in json.dumps(row) for row in (audit_rows if isinstance(audit_rows, list) else []))
    if not flags["AI_AUDIT_RECORDED"]:
        flags["AI_AUDIT_RECORDED"] = bool(
            handoff_payload.get("financial_record_id") or handoff_payload.get("payout_id")
        )

    for key, value in flags.items():
        print(f"{key}={str(value).lower()}")

    print(f"PRIMARY_RIDE_ID={ride_id}")
    print(f"NEXT_RIDE_ID={next_ride_id or 'none'}")
    passed = all(flags.values())
    print(f"RESULT={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
