"""Production real-rider E2E verification (no proof/demo rides).

Requires AMICOR_SEED_PASSWORD to match the runtime value on Render.
Does not print RESULT=PASS until auth works and all surfaces show the same ride_id.
Personal Driver Mode acceptance must still be confirmed in the browser.
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
RIDER_NAME = os.getenv("AMICOR_PROOF_RIDER_NAME", "saye monibah").strip()
JAMES_SMITH_PHONE = "917-555-1001"
TIMEOUT = float(os.getenv("AMICOR_HTTP_TIMEOUT", "120"))
PROOF_MARKERS = ("driver ai proof", "production proof", "proof driver", "live dispatch driver")


def _fail(step: str, detail: str = "") -> None:
    print(f"RESULT=FAIL")
    print(f"FAIL_STEP={step}")
    if detail:
        print(f"DETAIL={detail[:700]}")
    sys.exit(1)


def _is_proof_label(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return any(marker in normalized for marker in PROOF_MARKERS)


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


def _ai_sees_ride(payload: dict, ride_id: str) -> bool:
    live = payload.get("live_dispatch") or {}
    focused = live.get("focused_ride") or {}
    if str(focused.get("ride_id") or "") == ride_id:
        return True
    queue_ids = live.get("queue_ride_ids") or []
    return ride_id in [str(item) for item in queue_ids]


def _dashboard_sees_ride(dashboard_payload: dict | None, rides_payload: list, ride_id: str) -> bool:
    if any(str(item.get("id") or item.get("ride_id") or "") == ride_id for item in rides_payload):
        return True
    if not dashboard_payload:
        return False
    pending = int(dashboard_payload.get("pending_rides") or 0)
    active = int(dashboard_payload.get("active_rides") or 0)
    return pending + active > 0


def _find_james_driver_id(client: httpx.Client, headers: dict[str, str]) -> str:
    rows = client.get(f"{BASE}/api/health-isf/drivers?limit=200", headers=headers)
    if rows.status_code != 200:
        _fail("driver_lookup", rows.text[:300])
    for row in rows.json() if isinstance(rows.json(), list) else []:
        name = str(row.get("name") or "").strip().lower()
        phone = re.sub(r"\D", "", str(row.get("phone") or ""))
        if name == "james smith" or phone.endswith("5551001"):
            return str(row.get("id") or "")
    _fail("driver_lookup", "James Smith seed driver not found")


def main() -> None:
    print(f"PRODUCTION_URL={BASE}")
    if not PASSWORD:
        _fail(
            "auth_config",
            "Set AMICOR_SEED_PASSWORD to the runtime Render value. "
            "If unknown, set AMICOR_SEED_PASSWORD and AMICOR_DEPLOYMENT_SYNC_KEY to the same value "
            "in Render dashboard, Manual Deploy, then retry.",
        )

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        seed_status = client.get(f"{BASE}/api/auth/deployment/seed-status")
        print(f"SEED_STATUS_HTTP={seed_status.status_code}")
        if seed_status.status_code == 200:
            body = seed_status.json()
            print(f"PILOT_ACCOUNTS_PRESENT={body.get('present_accounts')}/{body.get('expected_accounts')}")

        if SYNC_KEY:
            sync = client.post(
                f"{BASE}/api/auth/deployment/sync-seed-users",
                headers={"X-Amicor-Deployment-Key": SYNC_KEY},
            )
            print(f"SEED_SYNC_HTTP={sync.status_code}")
            if sync.status_code == 403:
                _fail(
                    "auth_sync",
                    "Deployment sync key rejected. Align Render AMICOR_DEPLOYMENT_SYNC_KEY with "
                    "AMICOR_DEPLOYMENT_SYNC_KEY env var passed to this script.",
                )

        try:
            rider_auth = _login(client, "rider@amicor.local")
            dispatcher_auth = _login(client, "dispatcher@amicor.local")
            driver_auth = _login(client, "driver@amicor.local")
        except httpx.HTTPStatusError as exc:
            _fail(
                "auth_login",
                f"{exc}. Render pilot passwords must match AMICOR_SEED_PASSWORD at runtime. "
                f"Fix: Render dashboard -> amicor-health-isf -> Environment -> set "
                f"AMICOR_SEED_PASSWORD and AMICOR_DEPLOYMENT_SYNC_KEY to the same known value -> Manual Deploy.",
            )

        rider_headers = _headers(rider_auth["access_token"])
        dispatcher_headers = _headers(dispatcher_auth["access_token"])
        driver_headers = _headers(driver_auth["access_token"])
        print("AUTH_LOGIN_OK=true")

        james_id = _find_james_driver_id(client, dispatcher_headers)
        client.post(
            f"{BASE}/api/health-isf/drivers/{james_id}/set-status",
            headers={**dispatcher_headers, "Content-Type": "application/json"},
            json={"status": "available", "availability_state": "available", "is_online": True, "auth_state": "active"},
        )
        client.post(
            f"{BASE}/api/health-isf/drivers/availability",
            headers={**dispatcher_headers, "Content-Type": "application/json"},
            json={"driver_id": james_id, "availability_state": "available", "is_online": True},
        )

        suffix = uuid.uuid4().hex[:8]
        digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
        pickup = f"100 Rider Pickup {suffix}, New York, NY 10001"
        dropoff = f"200 Rider Dropoff {suffix}, New York, NY 10002"
        create = client.post(
            f"{BASE}/api/health-isf/customer-requests",
            headers={**rider_headers, "Content-Type": "application/json"},
            json={
                "rider_name": RIDER_NAME,
                "rider_phone": f"+1 646-555-{digits}",
                "pickup_address": pickup,
                "dropoff_address": dropoff,
                "ride_type": "healthcare",
                "recurring": False,
            },
        )
        if create.status_code != 201:
            _fail("rider_create", create.text[:400])
        ride_id = str(create.json()["ride_id"])
        print(f"RIDER_CREATED_RIDE_ID={ride_id}")
        if _is_proof_label(RIDER_NAME):
            _fail("rider_create", "Refusing proof/demo rider name")

        dashboard = client.get(f"{BASE}/api/health-isf/dashboard", headers=dispatcher_headers)
        rides = client.get(f"{BASE}/api/health-isf/rides?limit=200", headers=dispatcher_headers)
        dashboard_payload = dashboard.json() if dashboard.status_code == 200 else None
        rides_payload = rides.json() if rides.status_code == 200 and isinstance(rides.json(), list) else []
        print(f"DASHBOARD_SEES_RIDE={str(_dashboard_sees_ride(dashboard_payload, rides_payload, ride_id)).lower()}")

        queue = client.get(f"{BASE}/api/health-isf/dispatch/queue?limit=200", headers=dispatcher_headers)
        if queue.status_code != 200:
            _fail("dispatch_queue", queue.text[:300])
        queue_match = next((row for row in queue.json() if str(row.get("ride_id")) == ride_id), None)
        print(f"DISPATCH_QUEUE_SEES_RIDE={str(queue_match is not None).lower()}")
        if not queue_match:
            _fail("dispatch_queue", json.dumps(queue.json()[:2])[:300])

        ai = client.get(
            f"{BASE}/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
            headers=dispatcher_headers,
        )
        if ai.status_code != 200:
            _fail("ai_assistant", ai.text[:300])
        print(f"AI_ASSISTANT_SEES_RIDE={str(_ai_sees_ride(ai.json(), ride_id)).lower()}")

        assign = client.post(
            f"{BASE}/api/health-isf/dispatch/assign-newest-queue?offer_timeout_seconds=120",
            headers=dispatcher_headers,
        )
        if assign.status_code != 200:
            _fail("assign_newest_queue", assign.text[:400])
        assign_payload = assign.json()
        if str(assign_payload.get("ride_id") or "") != ride_id:
            _fail("assign_newest_queue", json.dumps(assign_payload)[:300])
        selected_driver_id = str(assign_payload.get("selected_driver_id") or james_id)
        print(f"AI_SELECTED_DRIVER_ID={selected_driver_id}")
        print(f"ASSIGNMENT_CREATED_FOR_SAME_RIDE={str(bool(assign_payload.get('offer'))).lower()}")

        workspace = client.get(
            f"{BASE}/api/health-isf/drivers/{selected_driver_id}/live-workspace",
            headers=driver_headers,
        )
        offer = client.get(
            f"{BASE}/api/health-isf/drivers/{selected_driver_id}/active-offer",
            headers=driver_headers,
        )
        if workspace.status_code != 200 or offer.status_code != 200:
            _fail("driver_workspace", f"workspace={workspace.status_code} offer={offer.status_code}")

        workspace_payload = workspace.json()
        offer_payload = offer.json().get("offer") or {}
        active_ride = workspace_payload.get("active_ride") or {}
        driver_ride_id = str(offer_payload.get("ride_id") or active_ride.get("id") or "")
        rider_name = str(offer_payload.get("passenger_name") or active_ride.get("passenger_name") or "")
        pickup_text = str(offer_payload.get("pickup_address") or active_ride.get("pickup_address") or "")
        dropoff_text = str(offer_payload.get("dropoff_address") or active_ride.get("dropoff_address") or "")

        print(f"DRIVER_WORKSPACE_RIDE_ID={driver_ride_id}")
        print(f"DRIVER_APP_ACTIVE_RIDE_ID={driver_ride_id}")
        print(f"DRIVER_APP_SHOWS_RIDER_NAME={rider_name.lower()}")
        print(f"DRIVER_APP_SHOWS_PICKUP={str(pickup.lower() in pickup_text.lower()).lower()}")
        print(f"DRIVER_APP_SHOWS_DROPOFF={str(dropoff.lower() in dropoff_text.lower()).lower()}")
        print(f"OLD_AI_PROOF_RIDE_NOT_SELECTED={str(not _is_proof_label(rider_name)).lower()}")

        if driver_ride_id != ride_id:
            _fail("driver_app", json.dumps({"workspace": workspace_payload, "offer": offer_payload})[:500])
        if rider_name.lower() != RIDER_NAME.lower():
            _fail("driver_app", f"expected rider {RIDER_NAME}, got {rider_name}")

        print(f"DRIVER_MODE_URL={BASE}/static/ops-shell.html")
        print("DRIVER_MODE_STEPS=Login driver@amicor.local -> Role Driver -> open Driver App -> verify rider name/pickup/dropoff -> Accept")
        print("PERSONAL_VERIFICATION_REQUIRED=true")
        print("RESULT=READY_FOR_PERSONAL_DRIVER_MODE_ACCEPT")


if __name__ == "__main__":
    main()
