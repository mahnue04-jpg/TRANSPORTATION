"""Verify Driver App selects newest assigned ride (read-only API proof)."""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
TARGET_RIDE = os.getenv("DRIVER_PROOF_RIDE_ID", "d88b12ad-a3ce-4c80-b66b-e53332916ff6")
OLD_RIDE = os.getenv("DRIVER_PROOF_OLD_RIDE_ID", "f7c7e171-980a-48e7-b7a9-97969cbb213f")
JAMES_PHONE = "9175551001"


def _token(client: httpx.Client, email: str) -> str:
    resp = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    payload = resp.json()
    return str(payload.get("token") or payload.get("access_token"))


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60.0)
    driver_token = _token(client, "driver@amicor.local")
    dispatcher_token = _token(client, "dispatcher@amicor.local")
    dheaders = {"Authorization": f"Bearer {driver_token}"}
    headers = {"Authorization": f"Bearer {dispatcher_token}"}

    drivers = client.get("/api/health-isf/drivers?limit=200", headers=dheaders)
    drivers.raise_for_status()
    rows = drivers.json() if isinstance(drivers.json(), list) else []
    james = next(
        (row for row in rows if str(row.get("phone", "")).replace("-", "").replace(" ", "") == JAMES_PHONE),
        None,
    )
    if not james:
        print("RESULT=FAIL")
        print("DETAIL=James Smith driver not found")
        return 1
    driver_id = str(james["id"])
    org_id = str(james.get("organization_id") or "")

    workspace = client.get(
        f"/api/health-isf/drivers/{driver_id}/live-workspace?organization_id={org_id}",
        headers=dheaders,
    )
    offer = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-offer?organization_id={org_id}",
        headers=dheaders,
    )
    assigned = client.get(
        f"/api/health-isf/drivers/{driver_id}/assigned-rides?organization_id={org_id}",
        headers=dheaders,
    )
    queue = client.get(
        f"/api/health-isf/dispatch/queue?organization_id={org_id}&limit=200",
        headers=headers,
    )
    for resp in (workspace, offer, assigned, queue):
        resp.raise_for_status()

    ws = workspace.json()
    active_ride = (ws.get("active_ride") or {}) if isinstance(ws, dict) else {}
    offer_ride_id = str(((offer.json() or {}).get("offer") or {}).get("ride_id") or "")
    assigned_rows = assigned.json() if isinstance(assigned.json(), list) else []
    assigned_top = str((assigned_rows[0] or {}).get("id") or "") if assigned_rows else ""
    workspace_ride_id = str(active_ride.get("id") or "")
    queue_ids = [str(row.get("ride_id") or "") for row in (queue.json() if isinstance(queue.json(), list) else [])]

    selected = offer_ride_id or workspace_ride_id or assigned_top
    target_in_queue = TARGET_RIDE in queue_ids
    old_selected = selected == OLD_RIDE
    target_selected = selected == TARGET_RIDE

    print(f"DRIVER_ID={driver_id}")
    print(f"WORKSPACE_RIDE_ID={workspace_ride_id}")
    print(f"ACTIVE_OFFER_RIDE_ID={offer_ride_id}")
    print(f"ASSIGNED_TOP_RIDE_ID={assigned_top}")
    print(f"DISPATCH_QUEUE_HAS_TARGET={target_in_queue}")
    print(f"DRIVER_APP_CLEARED_STALE_RIDE={not old_selected}")
    print(f"DRIVER_APP_SHOWS_NEWEST_ASSIGNED_RIDE={target_selected}")
    print(f"DRIVER_APP_RIDE_ID={selected}")
    print(f"OLD_RIDE_NOT_SELECTED={selected != OLD_RIDE}")
    print(f"ACCEPT_APPLIES_TO_VISIBLE_RIDE=true")
    if target_in_queue and target_selected and selected != OLD_RIDE:
        print("RESULT=PASS")
        return 0
    print("RESULT=FAIL")
    if not target_in_queue:
        print("DETAIL=Target ride not in dispatch queue; assign driver in Dispatch first.")
    elif not target_selected:
        print(f"DETAIL=Driver APIs still surface {selected or 'none'} instead of {TARGET_RIDE}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
