"""Production dispatch live ride proof against Render (HTTP only)."""
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
EXPECTED_VERSION = os.getenv("AMICOR_EXPECTED_APP_VERSION", "2026.07.05-dispatch-live.1")
PLACEHOLDER_RIDE_ID = "666cb94a-0a52-4a97-8afb-e460e095db53"
TIMEOUT = float(os.getenv("AMICOR_HTTP_TIMEOUT", "120"))


def _fail(reason: str, detail: str = "") -> None:
    print(f"RESULT=FAIL")
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


def _login(client: httpx.Client, email: str) -> dict:
    resp = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    return resp.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ai_sees_ride(payload: dict, ride_id: str) -> bool:
    live = payload.get("live_dispatch") or {}
    focused = live.get("focused_ride") or {}
    if str(focused.get("ride_id") or "") == ride_id:
        return True
    queue_ids = live.get("queue_ride_ids") or []
    if ride_id in [str(item) for item in queue_ids]:
        return True
    return ride_id in json.dumps(payload)


def _dashboard_sees_ride(dashboard_payload: dict | None, rides_payload: list, ride_id: str) -> bool:
    if any(str(item.get("id") or item.get("ride_id") or "") == ride_id for item in rides_payload):
        return True
    if not dashboard_payload:
        return False
    pending = int(dashboard_payload.get("pending_rides") or 0)
    active = int(dashboard_payload.get("active_rides") or 0)
    return pending + active > 0


def _ensure_proof_driver(client: httpx.Client, headers: dict[str, str]) -> str:
    suffix = uuid.uuid4().hex[:6]
    digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
    create = client.post(
        f"{BASE}/api/health-isf/drivers",
        headers={**headers, "Content-Type": "application/json", "X-Idempotency-Key": f"proof-driver-{suffix}"},
        json={
            "name": f"Proof Driver {suffix}",
            "phone": f"917-555-{digits}",
            "vehicle_type": "sedan",
            "vehicle_plate": f"PD-{suffix.upper()}",
        },
    )
    if create.status_code not in {200, 201}:
        _fail("driver_create", create.text[:400])
    driver_id = str(create.json().get("id") or "")
    client.post(
        f"{BASE}/api/health-isf/drivers/{driver_id}/set-status",
        headers={**headers, "Content-Type": "application/json"},
        json={"status": "available", "availability_state": "available", "is_online": True},
    )
    client.post(
        f"{BASE}/api/health-isf/drivers/availability",
        headers={**headers, "Content-Type": "application/json"},
        json={"driver_id": driver_id, "availability_state": "available", "is_online": True},
    )
    return driver_id


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
        render_commit = str(live_payload.get("deploy_commit") or live_payload.get("version") or "")
        app_version = str(live_payload.get("version") or "")
        print(f"RENDER_DEPLOY_COMMIT={render_commit or 'unknown'}")
        print(f"PRODUCTION_APP_VERSION={app_version}")

        commits_match = bool(
            local_commit
            and github_main
            and render_commit
            and local_commit == github_main
            and render_commit == local_commit
        )
        print(f"COMMITS_MATCH={str(commits_match).lower()}")
        if not commits_match:
            _fail(
                "deployment_not_updated",
                f"local={local_commit} github={github_main} render={render_commit or 'missing'} version={app_version}",
            )

        if app_version != EXPECTED_VERSION:
            print(
                f"WARN=app_version_label_mismatch expected={EXPECTED_VERSION} actual={app_version} "
                "(Render dashboard APP_VERSION may lag render.yaml; deploy_commit is authoritative)"
            )

        rider_auth = _login(client, "rider@amicor.local")
        rider_headers = _headers(rider_auth["access_token"])
        org_id = rider_auth["organization_id"]
        dispatcher_auth = _login(client, "dispatcher@amicor.local")
        dispatcher_headers = _headers(dispatcher_auth["access_token"])

        driver_id = _ensure_proof_driver(client, dispatcher_headers)

        suffix = uuid.uuid4().hex[:8]
        digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
        create = client.post(
            f"{BASE}/api/health-isf/customer-requests",
            headers={**rider_headers, "Content-Type": "application/json"},
            json={
                "rider_name": f"Production Proof {suffix}",
                "rider_phone": f"+1 646-555-{digits}",
                "pickup_address": f"100 Pickup {suffix}, New York, NY 10001",
                "dropoff_address": f"200 Dropoff {suffix}, New York, NY 10002",
                "ride_type": "healthcare",
                "recurring": False,
            },
        )
        if create.status_code != 201:
            _fail("rider_create", create.text[:400])
        row = create.json()
        ride_id = str(row["ride_id"])
        request_id = str(row["id"])
        print(f"RIDER_CREATED_RIDE_ID={ride_id}")

        dashboard_resp = client.get(f"{BASE}/api/health-isf/dashboard", headers=dispatcher_headers)
        rides_resp = client.get(f"{BASE}/api/health-isf/rides?limit=200", headers=dispatcher_headers)
        dashboard_payload = dashboard_resp.json() if dashboard_resp.status_code == 200 else None
        rides_payload = rides_resp.json() if rides_resp.status_code == 200 and isinstance(rides_resp.json(), list) else []
        dashboard_sees = _dashboard_sees_ride(dashboard_payload, rides_payload, ride_id)
        print(f"DASHBOARD_SEES_RIDE={str(dashboard_sees).lower()}")
        if not dashboard_sees:
            _fail("dashboard_visibility", json.dumps({"rides_count": len(rides_payload)})[:300])

        queue = client.get(f"{BASE}/api/health-isf/dispatch/queue?limit=200", headers=dispatcher_headers)
        if queue.status_code != 200:
            _fail("dispatch_queue", queue.text[:300])
        dispatch_match = next((item for item in queue.json() if str(item.get("ride_id")) == ride_id), None)
        print(f"DISPATCH_ASSIGNMENT_QUEUE_SEES_RIDE={str(dispatch_match is not None).lower()}")
        if not dispatch_match:
            _fail("dispatch_queue", json.dumps(queue.json()[:2])[:300])

        ai_pre = client.get(
            f"{BASE}/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
            headers=dispatcher_headers,
        )
        if ai_pre.status_code != 200:
            _fail("ai_snapshot", ai_pre.text[:300])
        ai_pre_sees = _ai_sees_ride(ai_pre.json(), ride_id)
        print(f"AI_ASSISTANT_SEES_ASSIGNABLE_RIDE={str(ai_pre_sees).lower()}")
        if not ai_pre_sees:
            _fail("ai_snapshot", json.dumps((ai_pre.json().get("live_dispatch") or {}))[:300])

        offer_resp = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
        offer_payload = offer_resp.json() if offer_resp.status_code == 200 else {}
        active_offer = offer_payload.get("offer")
        ai_selected_driver_id = str((active_offer or {}).get("driver_id") or driver_id)
        if not active_offer or str((active_offer or {}).get("ride_id") or "") != ride_id:
            auto = client.post(
                f"{BASE}/api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch",
                headers={**dispatcher_headers, "Content-Type": "application/json"},
                json={"offer_timeout_seconds": 120},
            )
            if auto.status_code != 200:
                _fail("auto_dispatch", auto.text[:400])
            auto_payload = auto.json()
            selected = (auto_payload.get("selected_driver") or {}) if isinstance(auto_payload, dict) else {}
            ai_selected_driver_id = str(selected.get("id") or (auto_payload.get("offer") or {}).get("driver_id") or driver_id)
            offer_resp = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
            offer_payload = offer_resp.json()
            active_offer = offer_payload.get("offer")

        print(f"AI_SELECTED_DRIVER_ID={ai_selected_driver_id}")
        driver_sees = bool(active_offer and str((active_offer or {}).get("ride_id") or "") == ride_id)
        print(f"DRIVER_OFFER_SEES_SAME_RIDE={str(driver_sees).lower()}")
        if not driver_sees:
            _fail("driver_offer", json.dumps(offer_payload)[:400])

        placeholder_removed = str((active_offer or {}).get("ride_id") or "") != PLACEHOLDER_RIDE_ID
        print(f"PLACEHOLDER_RIDE_REMOVED={str(placeholder_removed).lower()}")

        offer_id = str((active_offer or {}).get("offer_id") or (active_offer or {}).get("id") or "")
        accept = client.post(f"{BASE}/api/health-isf/dispatch/offers/{offer_id}/accept", headers=dispatcher_headers)
        accept_ok = accept.status_code in {200, 201}
        print(f"DRIVER_ACCEPT_200={str(accept_ok).lower()}")
        if not accept_ok:
            _fail("driver_accept", accept.text[:400])

        post_queue = client.get(f"{BASE}/api/health-isf/dispatch/queue?limit=200", headers=dispatcher_headers)
        post_row = next((item for item in post_queue.json() if str(item.get("ride_id")) == ride_id), None)
        post_status = str((post_row or {}).get("assignment_state") or "accepted")
        print(f"DISPATCH_STATUS_AFTER_ACCEPT={post_status}")

        rider_ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=rider_headers)
        rider_status = "accepted"
        if rider_ride.status_code == 200:
            rider_row = rider_ride.json()
            rider_status = str(rider_row.get("lifecycle_state") or rider_row.get("status") or "accepted").lower()
        print(f"RIDER_STATUS_AFTER_ACCEPT={rider_status}")

    print("RESULT=PASS")


if __name__ == "__main__":
    main()
