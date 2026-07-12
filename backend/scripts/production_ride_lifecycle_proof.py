"""Production ride lifecycle end-to-end proof.

Runs the full lifecycle against Render production APIs:
pending -> offered -> accepted -> en_route_pickup -> arrived_pickup ->
rider_loaded -> trip_in_progress -> arrived_destination -> completed + billing.

Requires AMICOR_SEED_PASSWORD (or successful deployment sync key).
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid

import httpx

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "").strip()
SYNC_KEY = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", PASSWORD).strip()
TIMEOUT = float(os.getenv("AMICOR_HTTP_TIMEOUT", "120"))
PROOF_LABEL = os.getenv("AMICOR_LIFECYCLE_PROOF_LABEL", "PILOT LIFECYCLE PROOF")


def _fail(step: str, detail: str = "") -> None:
    print("RESULT=FAIL")
    print(f"FAIL_STEP={step}")
    if detail:
        print(f"DETAIL={detail[:900]}")
    sys.exit(1)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client: httpx.Client, email: str) -> dict:
    resp = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD})
    if resp.status_code != 200:
        raise httpx.HTTPStatusError(
            f"login failed for {email}: {resp.status_code} {resp.text[:200]}",
            request=resp.request,
            response=resp,
        )
    return resp.json()


def _find_james(client: httpx.Client, headers: dict[str, str]) -> tuple[str, str]:
    rows = client.get(f"{BASE}/api/health-isf/drivers?limit=200", headers=headers)
    if rows.status_code != 200:
        _fail("driver_lookup", rows.text[:300])
    for row in rows.json() if isinstance(rows.json(), list) else []:
        name = str(row.get("name") or "").strip()
        phone = re.sub(r"\D", "", str(row.get("phone") or ""))
        if name.lower() == "james smith" or phone.endswith("5551001"):
            return str(row.get("id") or ""), name
    _fail("driver_lookup", "James Smith driver not found")
    return "", ""


def _route_progress(client: httpx.Client, headers: dict[str, str], driver_id: str, ride_id: str, target_state: str) -> tuple[int, dict]:
    resp = client.post(
        f"{BASE}/api/health-isf/drivers/{driver_id}/route-progress",
        headers={**headers, "Content-Type": "application/json"},
        json={"ride_id": ride_id, "target_state": target_state},
    )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text[:400]}
    print(f"LIFECYCLE_{target_state.upper()}_HTTP={resp.status_code}")
    return resp.status_code, body


def main() -> None:
    print(f"PRODUCTION_URL={BASE}")
    if not PASSWORD:
        _fail("auth_config", "Set AMICOR_SEED_PASSWORD to the Render runtime value.")

    transitions: list[tuple[str, int]] = []

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            rider_auth = _login(client, "rider@amicor.local")
            dispatcher_auth = _login(client, "dispatcher@amicor.local")
        except httpx.HTTPStatusError:
            if SYNC_KEY:
                sync = client.post(
                    f"{BASE}/api/auth/deployment/sync-seed-users",
                    headers={"X-Amicor-Deployment-Key": SYNC_KEY},
                )
                print(f"SEED_SYNC_HTTP={sync.status_code}")
            rider_auth = _login(client, "rider@amicor.local")
            dispatcher_auth = _login(client, "dispatcher@amicor.local")

        rider_headers = _headers(rider_auth["access_token"])
        dispatcher_headers = _headers(dispatcher_auth["access_token"])

        driver_id, driver_name = _find_james(client, dispatcher_headers)
        print(f"TEST_DRIVER_ID={driver_id}")
        print(f"TEST_DRIVER_NAME={driver_name}")

        client.post(
            f"{BASE}/api/health-isf/drivers/{driver_id}/set-status",
            headers={**dispatcher_headers, "Content-Type": "application/json"},
            json={"status": "available", "availability_state": "available", "is_online": True, "auth_state": "active"},
        )

        suffix = uuid.uuid4().hex[:8]
        digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
        create = client.post(
            f"{BASE}/api/health-isf/customer-requests",
            headers={**rider_headers, "Content-Type": "application/json"},
            json={
                "rider_name": f"{PROOF_LABEL} {suffix}",
                "rider_phone": f"+1 646-555-{digits}",
                "pickup_address": f"100 Lifecycle Pickup {suffix}, New York, NY 10001",
                "dropoff_address": f"200 Lifecycle Dropoff {suffix}, New York, NY 10002",
                "ride_type": "healthcare",
                "recurring": False,
                "notes": PROOF_LABEL,
            },
        )
        if create.status_code != 201:
            _fail("rider_create", create.text[:400])
        request_row = create.json()
        ride_id = str(request_row["ride_id"])
        request_id = str(request_row["id"])
        print(f"TEST_RIDE_ID={ride_id}")

        approve = client.post(
            f"{BASE}/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
            headers=dispatcher_headers,
        )
        print(f"APPROVE_HTTP={approve.status_code}")

        ride_before = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
        if ride_before.status_code != 200:
            _fail("ride_lookup", ride_before.text[:300])
        if str(ride_before.json().get("driver_id") or "") != driver_id:
            assign = client.post(
                f"{BASE}/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
                headers={**dispatcher_headers, "Content-Type": "application/json"},
                json={"driver_id": driver_id},
            )
            print(f"ASSIGN_HTTP={assign.status_code}")
            if assign.status_code != 200:
                _fail("assign_driver", assign.text[:400])

        driver_after_assign = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}", headers=dispatcher_headers)
        if driver_after_assign.status_code == 200:
            d = driver_after_assign.json()
            print(f"DRIVER_AFTER_ASSIGN_STATUS={d.get('status')}")
            print(f"DRIVER_AFTER_ASSIGN_AVAILABILITY={d.get('availability_state')}")

        available = client.get(f"{BASE}/api/health-isf/drivers/available", headers=dispatcher_headers)
        available_ids = [str(row.get("id")) for row in (available.json() if available.status_code == 200 else [])]
        print(f"DRIVER_IN_AVAILABLE_LIST_AFTER_ASSIGN={str(driver_id in available_ids).lower()}")
        if driver_id in available_ids:
            _fail("driver_available_leak", "Assigned driver still appears in available drivers list")

        accept = client.post(
            f"{BASE}/api/health-isf/drivers/{driver_id}/accept-ride",
            headers={**dispatcher_headers, "Content-Type": "application/json"},
            json={"ride_id": ride_id},
        )
        print(f"ACCEPT_HTTP={accept.status_code}")
        transitions.append(("accept", accept.status_code))
        if accept.status_code != 200:
            _fail("accept_ride", accept.text[:400])

        duplicate_accept = client.post(
            f"{BASE}/api/health-isf/drivers/{driver_id}/accept-ride",
            headers={**dispatcher_headers, "Content-Type": "application/json"},
            json={"ride_id": ride_id},
        )
        print(f"DUPLICATE_ACCEPT_HTTP={duplicate_accept.status_code}")
        if duplicate_accept.status_code not in {409, 400}:
            _fail("duplicate_accept_guard", duplicate_accept.text[:300])

        for target_state in (
            "en_route_pickup",
            "arrived_pickup",
            "rider_loaded",
            "trip_in_progress",
            "arrived_destination",
            "completed",
        ):
            code, _ = _route_progress(client, dispatcher_headers, driver_id, ride_id, target_state)
            transitions.append((target_state, code))
            if code != 200:
                _fail(f"route_progress_{target_state}", json.dumps(_)[:400])

        ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
        if ride.status_code != 200:
            _fail("final_ride", ride.text[:300])
        ride_payload = ride.json()
        print(f"FINAL_RIDE_STATUS={ride_payload.get('status')}")
        print(f"FINAL_RIDE_LIFECYCLE={ride_payload.get('lifecycle_state')}")

        billing = client.get(f"{BASE}/api/health-isf/billing/operations-ledger?limit=50", headers=dispatcher_headers)
        ledger_rows = billing.json() if billing.status_code == 200 and isinstance(billing.json(), list) else []
        ride_billing = [row for row in ledger_rows if str(row.get("ride_id") or "") == ride_id]
        print(f"BILLING_RECORD_COUNT={len(ride_billing)}")
        if len(ride_billing) != 1:
            _fail("billing_duplicate_or_missing", json.dumps(ride_billing)[:400])
        bill = ride_billing[0]
        print(f"GROSS_CHARGE={bill.get('ride_price_usd') or bill.get('gross_amount_usd')}")
        print(f"DRIVER_PAYOUT={bill.get('driver_pay_usd') or bill.get('driver_payout_usd')}")
        print(f"PLATFORM_REVENUE={bill.get('platform_revenue_usd')}")
        print(f"BILLING_RECORD_ID={bill.get('id') or bill.get('handoff_id')}")

        driver_final = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}", headers=dispatcher_headers)
        if driver_final.status_code == 200:
            d = driver_final.json()
            print(f"FINAL_DRIVER_STATUS={d.get('status')}")
            print(f"FINAL_DRIVER_AVAILABILITY={d.get('availability_state')}")
            if str(d.get("status") or "").lower() != "available" or str(d.get("availability_state") or "").lower() != "available":
                _fail("driver_not_released", json.dumps(d)[:300])

        active_assignments = client.get(
            f"{BASE}/api/health-isf/dispatch/active-assignments?limit=200",
            headers=dispatcher_headers,
        )
        active_rows = active_assignments.json() if active_assignments.status_code == 200 else []
        active_for_ride = [row for row in active_rows if str(row.get("ride_id") or "") == ride_id]
        print(f"ACTIVE_ASSIGNMENTS_FOR_RIDE={len(active_for_ride)}")
        if active_for_ride:
            _fail("active_queue_leak", json.dumps(active_for_ride)[:300])

        active_ride = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
        if active_ride.status_code == 200:
            payload = active_ride.json()
            print(f"DRIVER_ACTIVE_RIDE={str(payload.get('has_active_ride')).lower()}")

        print("TRANSITIONS=" + json.dumps(transitions))
        print("RESULT=PASS")


if __name__ == "__main__":
    main()
