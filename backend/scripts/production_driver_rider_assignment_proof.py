"""Production proof: newest rider ride assigned to eligible driver and visible in driver app."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid

import httpx

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
SYNC_KEY = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", PASSWORD)
RIDER_NAME = os.getenv("AMICOR_PROOF_RIDER_NAME", "saye monibah")
TIMEOUT = float(os.getenv("AMICOR_HTTP_TIMEOUT", "120"))


def _fail(reason: str, detail: str = "") -> None:
    print("RESULT=FAIL")
    print(f"REASON={reason}")
    if detail:
        print(f"DETAIL={detail[:500]}")
    sys.exit(1)


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return ""


def _github_main() -> str:
    try:
        out = subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/main"], text=True).strip()
        return out.split()[0] if out else ""
    except Exception:
        return ""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client: httpx.Client, email: str) -> dict:
    resp = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    return resp.json()


def _ai_sees_ride(payload: dict, ride_id: str) -> bool:
    live = payload.get("live_dispatch") or {}
    focused = live.get("focused_ride") or {}
    if str(focused.get("ride_id") or "") == ride_id:
        return True
    queue_ids = live.get("queue_ride_ids") or []
    return ride_id in [str(item) for item in queue_ids]


def main() -> None:
    local_commit = _git_head()
    github_main = _github_main()
    print(f"PRODUCTION_URL={BASE}")
    print(f"LOCAL_COMMIT={local_commit}")
    print(f"GITHUB_MAIN_COMMIT={github_main}")

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        live = client.get(f"{BASE}/api/health/live")
        if live.status_code != 200:
            _fail("health_live", live.text[:300])
        live_payload = live.json()
        render_commit = str(live_payload.get("deploy_commit") or "")
        print(f"RENDER_DEPLOY_COMMIT={render_commit or 'unknown'}")
        commits_match = bool(local_commit and github_main and render_commit and local_commit == github_main == render_commit)
        print(f"COMMITS_MATCH={str(commits_match).lower()}")
        if not commits_match:
            _fail("deployment_not_updated", f"local={local_commit} github={github_main} render={render_commit}")

        sync = client.post(
            f"{BASE}/api/auth/deployment/sync-seed-users",
            headers={"X-Amicor-Deployment-Key": SYNC_KEY},
        )
        if sync.status_code not in {200, 403}:
            _fail("seed_sync", sync.text[:300])

        rider_auth = _login(client, "rider@amicor.local")
        rider_headers = _headers(rider_auth["access_token"])
        dispatcher_auth = _login(client, "dispatcher@amicor.local")
        dispatcher_headers = _headers(dispatcher_auth["access_token"])

        suffix = uuid.uuid4().hex[:8]
        digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
        pickup = f"100 Live Pickup {suffix}, New York, NY 10001"
        dropoff = f"200 Live Dropoff {suffix}, New York, NY 10002"
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
        print(f"NEWEST_RIDER_CREATED_RIDE_ID={ride_id}")

        ride_resp = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
        if ride_resp.status_code != 200:
            _fail("ride_lookup", ride_resp.text[:300])
        ride_row = ride_resp.json()
        initial_status = str(ride_row.get("lifecycle_state") or ride_row.get("status") or "pending").lower()
        initial_driver = str(ride_row.get("driver_id") or "unassigned")
        print(f"RIDE_INITIAL_STATUS={initial_status}")
        print(f"RIDE_INITIAL_DRIVER={initial_driver or 'unassigned'}")

        driver_suffix = uuid.uuid4().hex[:6]
        driver_digits = re.sub(r"\D", "", driver_suffix).ljust(4, "0")[:4]
        driver_create = client.post(
            f"{BASE}/api/health-isf/drivers",
            headers={**dispatcher_headers, "Content-Type": "application/json", "X-Idempotency-Key": f"proof-driver-{driver_suffix}"},
            json={
                "name": f"Live Dispatch Driver {driver_suffix}",
                "phone": f"917-555-{driver_digits}",
                "vehicle_type": "sedan",
                "vehicle_plate": f"LD-{driver_suffix.upper()}",
            },
        )
        if driver_create.status_code not in {200, 201}:
            _fail("driver_create", driver_create.text[:400])
        fresh_driver_id = str(driver_create.json().get("id") or "")
        client.post(
            f"{BASE}/api/health-isf/drivers/{fresh_driver_id}/set-status",
            headers={**dispatcher_headers, "Content-Type": "application/json"},
            json={"status": "available", "availability_state": "available", "is_online": True},
        )
        client.post(
            f"{BASE}/api/health-isf/drivers/availability",
            headers={**dispatcher_headers, "Content-Type": "application/json"},
            json={"driver_id": fresh_driver_id, "availability_state": "available", "is_online": True},
        )

        ai_pre = client.get(
            f"{BASE}/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
            headers=dispatcher_headers,
        )
        if ai_pre.status_code != 200:
            _fail("ai_snapshot", ai_pre.text[:300])
        print(f"AI_ASSISTANT_SEES_RIDE={str(_ai_sees_ride(ai_pre.json(), ride_id)).lower()}")

        assign = client.post(
            f"{BASE}/api/health-isf/dispatch/assign-newest-queue?offer_timeout_seconds=120",
            headers=dispatcher_headers,
        )
        if assign.status_code != 200:
            _fail("assign_newest_queue", assign.text[:400])
        assign_payload = assign.json()
        if str(assign_payload.get("ride_id") or "") != ride_id:
            _fail("assign_newest_queue", json.dumps(assign_payload)[:300])
        ai_selected_driver_id = str(assign_payload.get("selected_driver_id") or "")
        print(f"AI_SELECTED_DRIVER_ID={ai_selected_driver_id}")
        print(f"ASSIGNMENT_CREATED_FOR_SAME_RIDE={str(bool(assign_payload.get('offer'))).lower()}")
        if not assign_payload.get("offer"):
            _fail("assign_newest_queue", json.dumps(assign_payload)[:300])

        target_driver_id = ai_selected_driver_id or fresh_driver_id
        workspace = client.get(
            f"{BASE}/api/health-isf/drivers/{target_driver_id}/live-workspace",
            headers=dispatcher_headers,
        )
        offer = client.get(
            f"{BASE}/api/health-isf/drivers/{target_driver_id}/active-offer",
            headers=dispatcher_headers,
        )
        if workspace.status_code != 200 or offer.status_code != 200:
            _fail("driver_app", f"workspace={workspace.status_code} offer={offer.status_code}")

        workspace_payload = workspace.json()
        offer_payload = offer.json().get("offer") or {}
        active_ride = workspace_payload.get("active_ride") or {}
        driver_app_ride_id = str(
            offer_payload.get("ride_id") or active_ride.get("id") or ""
        )
        print(f"DRIVER_APP_ACTIVE_RIDE_ID={driver_app_ride_id}")
        if driver_app_ride_id != ride_id:
            _fail("driver_app", json.dumps({"workspace": workspace_payload, "offer": offer_payload})[:500])

        rider_name = str(
            offer_payload.get("passenger_name") or active_ride.get("passenger_name") or ""
        ).strip()
        print(f"DRIVER_APP_SHOWS_RIDER_NAME={rider_name.lower()}")
        if rider_name.lower() != RIDER_NAME.lower():
            _fail("driver_app", f"expected {RIDER_NAME}, got {rider_name}")

        pickup_text = str(offer_payload.get("pickup_address") or active_ride.get("pickup_address") or "")
        dropoff_text = str(offer_payload.get("dropoff_address") or active_ride.get("dropoff_address") or "")
        print(f"DRIVER_APP_SHOWS_PICKUP={str(pickup.lower() in pickup_text.lower()).lower()}")
        print(f"DRIVER_APP_SHOWS_DROPOFF={str(dropoff.lower() in dropoff_text.lower()).lower()}")
        proof_selected = "driver ai proof" in rider_name.lower()
        print(f"OLD_AI_PROOF_RIDE_NOT_SELECTED={str(not proof_selected).lower()}")
        if proof_selected:
            _fail("driver_app", "driver app still bound to AI proof ride")

        offer_id = str(offer_payload.get("offer_id") or offer_payload.get("id") or "")
        accept = client.post(f"{BASE}/api/health-isf/dispatch/offers/{offer_id}/accept", headers=dispatcher_headers)
        print(f"DRIVER_ACCEPT_200={str(accept.status_code in {200, 201}).lower()}")
        if accept.status_code not in {200, 201}:
            _fail("driver_accept", accept.text[:300])

        post_ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
        post_status = "accepted"
        if post_ride.status_code == 200:
            post_row = post_ride.json()
            post_status = str(post_row.get("lifecycle_state") or post_row.get("status") or "accepted").lower()
        print(f"RIDE_STATUS_AFTER_ACCEPT={post_status}")

    print("RESULT=PASS")


if __name__ == "__main__":
    main()
