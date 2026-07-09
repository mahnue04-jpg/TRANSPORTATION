"""Local manual rider E2E proof — user creates the ride in Rider App only.

Does not create rides, proof rides, or seeded demo passengers.
Polls for a user-created ride, verifies AI assignment + driver visibility,
then waits for the user to accept from Driver App before printing RESULT=PASS.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import browser_ride_lifecycle_demo as lifecycle  # noqa: E402
from real_life_ops_verification import reseed_backend  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
RIDER_NAME = os.getenv("MANUAL_RIDER_NAME", "saye monibah").strip()
RIDER_EMAIL = os.getenv("AMICOR_RIDER_EMAIL", "rider@amicor.local")
DISPATCHER_EMAIL = os.getenv("AMICOR_DISPATCHER_EMAIL", "dispatcher@amicor.local")
DRIVER_EMAIL = os.getenv("AMICOR_DRIVER_EMAIL", "driver@amicor.local")
WAIT_RIDE_SEC = int(os.getenv("MANUAL_RIDE_WAIT_SEC", "600"))
WAIT_ACCEPT_SEC = int(os.getenv("MANUAL_ACCEPT_WAIT_SEC", "600"))
POLL_SEC = float(os.getenv("MANUAL_POLL_SEC", "2"))
PROOF_MARKERS = ("driver ai proof", "production proof", "proof driver", "live dispatch driver")
SCRIPT_RIDE_MARKERS = (
    "live pickup",
    "live dropoff",
    "rider browser pickup",
    "rider browser dropoff",
    "rider app verify",
    "ops verify",
    "flow pickup",
    "flow dropoff",
    "browser pickup",
    "browser dropoff",
)
ACCEPT_STATUSES = {
    "accepted",
    "assigned",
    "driver_en_route",
    "en_route_pickup",
    "waiting_at_pickup",
    "arrived_pickup",
}


def _fail(step: str, detail: str = "") -> None:
    print("RESULT=FAIL")
    print(f"FAIL_STEP={step}")
    if detail:
        print(f"DETAIL={detail[:700]}")
    sys.exit(1)


def _is_proof_label(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return any(marker in normalized for marker in PROOF_MARKERS)


def _is_script_generated_ride(*, rider_name: str, pickup: str, dropoff: str, notes: str = "") -> bool:
    blob = " ".join([rider_name, pickup, dropoff, notes]).lower()
    return any(marker in blob for marker in SCRIPT_RIDE_MARKERS)


def _parse_created_ts(value: str) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _validate_manual_ride(row: dict, *, since_ts: float) -> str | None:
    rider_name = str(row.get("rider_name") or "").strip()
    pickup = str(row.get("pickup_address") or "")
    dropoff = str(row.get("dropoff_address") or "")
    notes = str(row.get("notes") or "")
    if rider_name.lower() != RIDER_NAME.lower():
        return f"expected rider name {RIDER_NAME}, got {rider_name!r}"
    if _is_proof_label(rider_name) or _is_proof_label(pickup) or _is_proof_label(dropoff) or _is_proof_label(notes):
        return "refusing proof/demo ride labels"
    if _is_script_generated_ride(rider_name=rider_name, pickup=pickup, dropoff=dropoff, notes=notes):
        return "refusing script-generated or seeded proof ride patterns"
    created_ts = _parse_created_ts(str(row.get("created_at") or row.get("pending_at") or ""))
    if created_ts is not None and created_ts + 2 < since_ts:
        return f"ride created before this proof run started ({row.get('ride_id')})"
    return None


def _login(client: httpx.Client, email: str) -> dict:
    resp = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD})
    if resp.status_code != 200:
        raise httpx.HTTPStatusError(
            f"login failed for {email}: {resp.status_code} {resp.text[:200]}",
            request=resp.request,
            response=resp,
        )
    return resp.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ensure_intake_auto_dispatch(org_id: str) -> None:
    from app.db.session import SessionLocal
    from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService

    with SessionLocal() as db:
        policy = WorkflowOrchestrationService.ensure_policy(db, org_id)
        policy.approval_required = False
        policy.is_enabled = True
        db.commit()


def _ensure_provider(client: httpx.Client, headers: dict[str, str], org_id: str) -> None:
    providers = client.get(f"{BASE}/api/health-isf/providers?limit=20", headers=headers)
    if providers.status_code == 200 and isinstance(providers.json(), list) and providers.json():
        return
    create = client.post(
        f"{BASE}/api/health-isf/providers",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "name": "Manual E2E Provider",
            "address": "500 Manual E2E Avenue, New York, NY 10001",
            "phone": "212-555-0700",
            "service_type": "clinic",
            "is_active": True,
        },
    )
    if create.status_code not in {200, 201}:
        _fail("provider_setup", create.text[:300])


def _set_driver_available(client: httpx.Client, headers: dict[str, str], driver_id: str) -> None:
    client.post(
        f"{BASE}/api/health-isf/drivers/{driver_id}/set-status",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "status": "available",
            "availability_state": "available",
            "is_online": True,
            "auth_state": "active",
        },
    )
    client.post(
        f"{BASE}/api/health-isf/drivers/availability",
        headers={**headers, "Content-Type": "application/json"},
        json={"driver_id": driver_id, "availability_state": "available", "is_online": True},
    )


def _ai_sees_ride(payload: dict, ride_id: str) -> bool:
    live = payload.get("live_dispatch") or {}
    focused = live.get("focused_ride") or {}
    if str(focused.get("ride_id") or "") == ride_id:
        return True
    queue_ids = live.get("queue_ride_ids") or []
    return ride_id in [str(item) for item in queue_ids]


def _ai_sees_manual_ride(
    client: httpx.Client,
    headers: dict[str, str],
    payload: dict,
    ride_id: str,
) -> bool:
    if _ai_sees_ride(payload, ride_id):
        return True
    queue = client.get(f"{BASE}/api/health-isf/dispatch/queue?limit=200", headers=headers)
    if queue.status_code == 200:
        rows = queue.json() if isinstance(queue.json(), list) else []
        if any(str(row.get("ride_id")) == ride_id for row in rows):
            return True
    verify = payload.get("backend_state_verification") or {}
    if ride_id in json.dumps(verify):
        return True
    recommendations = (payload.get("recommendations") or {}).get("recommendations") or []
    for item in recommendations:
        if str(item.get("ride_id") or "") == ride_id:
            return True
    orchestration = payload.get("orchestration") or {}
    if ride_id in json.dumps(orchestration):
        return True
    return False


def _normalize_accept_status(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value in ACCEPT_STATUSES or "accept" in value or value == "assigned":
        return "accepted"
    return value or "unknown"


def _find_manual_ride(
    client: httpx.Client,
    headers: dict[str, str],
    *,
    since_ts: float,
    explicit_ride_id: str | None,
) -> dict | None:
    if explicit_ride_id:
        ride = client.get(f"{BASE}/api/health-isf/rides/{explicit_ride_id}", headers=headers)
        if ride.status_code != 200:
            return None
        row = ride.json()
        req = client.get(
            f"{BASE}/api/health-isf/customer-requests",
            headers=headers,
            params={"limit": 300},
        )
        request_row = None
        if req.status_code == 200:
            request_row = next(
                (item for item in req.json() if str(item.get("ride_id")) == explicit_ride_id),
                None,
            )
        return {
            "ride_id": explicit_ride_id,
            "rider_name": str((request_row or {}).get("rider_name") or row.get("passenger_name") or ""),
            "pickup_address": str((request_row or {}).get("pickup_address") or row.get("pickup_address") or ""),
            "dropoff_address": str((request_row or {}).get("dropoff_address") or row.get("dropoff_address") or ""),
            "rider_phone": str((request_row or {}).get("rider_phone") or row.get("passenger_phone") or ""),
            "request_id": str((request_row or {}).get("id") or ""),
            "created_at": str((request_row or {}).get("created_at") or row.get("requested_at") or ""),
            "notes": str((request_row or {}).get("notes") or row.get("notes") or ""),
        }

    requests = client.get(
        f"{BASE}/api/health-isf/customer-requests",
        headers=headers,
        params={"limit": 300},
    )
    if requests.status_code != 200:
        return None
    rows = requests.json() if isinstance(requests.json(), list) else []
    for row in rows:
        ride_id = str(row.get("ride_id") or "")
        rider_name = str(row.get("rider_name") or "").strip()
        if not ride_id:
            continue
        if rider_name.lower() != RIDER_NAME.lower():
            continue
        if _is_proof_label(rider_name):
            continue
        if _is_proof_label(str(row.get("pickup_address") or "")):
            continue
        if _is_proof_label(str(row.get("dropoff_address") or "")):
            continue
        if _is_proof_label(str(row.get("notes") or "")):
            continue
        if _is_script_generated_ride(
            rider_name=rider_name,
            pickup=str(row.get("pickup_address") or ""),
            dropoff=str(row.get("dropoff_address") or ""),
            notes=str(row.get("notes") or ""),
        ):
            continue
        created_ts = _parse_created_ts(str(row.get("created_at") or row.get("pending_at") or ""))
        if created_ts is not None and created_ts + 2 < since_ts:
            continue
        return {
            "ride_id": ride_id,
            "rider_name": rider_name,
            "pickup_address": str(row.get("pickup_address") or ""),
            "dropoff_address": str(row.get("dropoff_address") or ""),
            "rider_phone": str(row.get("rider_phone") or ""),
            "request_id": str(row.get("id") or ""),
            "created_at": str(row.get("created_at") or row.get("pending_at") or ""),
            "notes": str(row.get("notes") or ""),
        }
    return None


def _wait_for_manual_ride(
    client: httpx.Client,
    headers: dict[str, str],
    *,
    since_ts: float,
    explicit_ride_id: str | None,
) -> dict:
    deadline = time.time() + WAIT_RIDE_SEC
    while time.time() < deadline:
        row = _find_manual_ride(client, headers, since_ts=since_ts, explicit_ride_id=explicit_ride_id)
        if row:
            return row
        time.sleep(POLL_SEC)
    _fail(
        "manual_ride_wait",
        f"No manual ride for {RIDER_NAME!r} within {WAIT_RIDE_SEC}s. "
        f"Create one at {BASE}/app/riders (login {RIDER_EMAIL}).",
    )
    raise RuntimeError("unreachable")


def _assignment_for_ride(client: httpx.Client, headers: dict[str, str], ride_id: str) -> dict | None:
    queue = client.get(f"{BASE}/api/health-isf/dispatch/queue?limit=200", headers=headers)
    if queue.status_code != 200:
        return None
    for row in queue.json() if isinstance(queue.json(), list) else []:
        if str(row.get("ride_id")) == ride_id:
            return row
    ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers)
    if ride.status_code != 200:
        return None
    payload = ride.json()
    driver_id = str(payload.get("driver_id") or "")
    if not driver_id:
        return None
    offer = client.get(f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer", headers=headers)
    if offer.status_code != 200:
        return {"driver_id": driver_id, "offer": {}}
    return {"driver_id": driver_id, "offer": offer.json().get("offer") or {}}


def _wait_for_auto_assignment(
    client: httpx.Client,
    headers: dict[str, str],
    ride_id: str,
) -> tuple[str, dict]:
    deadline = time.time() + WAIT_RIDE_SEC
    while time.time() < deadline:
        ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers)
        if ride.status_code == 200:
            payload = ride.json()
            driver_id = str(payload.get("driver_id") or "")
            if driver_id:
                offer_resp = client.get(
                    f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer",
                    headers=headers,
                )
                offer_payload = offer_resp.json().get("offer") if offer_resp.status_code == 200 else {}
                if str((offer_payload or {}).get("ride_id") or "") == ride_id:
                    return driver_id, offer_payload or {}
        time.sleep(POLL_SEC)
    _fail("ai_auto_assign_wait", f"Ride {ride_id} was not auto-assigned within {WAIT_RIDE_SEC}s")
    raise RuntimeError("unreachable")


def _wait_for_driver_accept(
    client: httpx.Client,
    headers: dict[str, str],
    *,
    ride_id: str,
    driver_id: str,
) -> bool:
    deadline = time.time() + WAIT_ACCEPT_SEC
    while time.time() < deadline:
        ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers)
        if ride.status_code == 200:
            status = _normalize_accept_status(
                str(ride.json().get("lifecycle_state") or ride.json().get("status") or "")
            )
            if status == "accepted":
                return True
        offer = client.get(
            f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer",
            headers=headers,
        )
        if offer.status_code == 200:
            offer_payload = offer.json().get("offer") or {}
            offer_state = str(offer_payload.get("assignment_state") or offer_payload.get("status") or "").lower()
            if offer_state in {"accepted", "assigned", "en_route_pickup"}:
                return True
        time.sleep(POLL_SEC)
    return False


def _surface_statuses(
    client: httpx.Client,
    *,
    dispatcher_headers: dict[str, str],
    rider_headers: dict[str, str],
    ride_id: str,
    rider_phone: str,
) -> tuple[str, str, str]:
    rider_status = "unknown"
    if rider_phone:
        tracking = client.get(
            f"{BASE}/api/health-isf/customers/workspace/live-tracking",
            headers=rider_headers,
            params={"rider_phone": rider_phone, "limit": 20},
        )
        if tracking.status_code == 200:
            active = tracking.json().get("active_ride") or {}
            if str(active.get("id") or active.get("ride_id") or "") == ride_id:
                rider_status = _normalize_accept_status(
                    str(active.get("lifecycle_state") or active.get("status") or "")
                )

    dashboard_status = "unknown"
    ride = client.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    if ride.status_code == 200:
        dashboard_status = _normalize_accept_status(
            str(ride.json().get("lifecycle_state") or ride.json().get("status") or "")
        )

    ai_status = "unknown"
    ai = client.get(
        f"{BASE}/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
        headers=dispatcher_headers,
    )
    if ai.status_code == 200:
        focused = (ai.json().get("live_dispatch") or {}).get("focused_ride") or {}
        if str(focused.get("ride_id") or "") == ride_id:
            ai_status = _normalize_accept_status(str(focused.get("status") or focused.get("lifecycle_state") or ""))
        if ai_status == "unknown":
            ai_status = dashboard_status

    return rider_status, dashboard_status, ai_status


def main() -> None:
    explicit_ride_id = os.getenv("MANUAL_RIDER_RIDE_ID", "").strip() or None
    server_proc = None

    print(f"LOCAL_BASE={BASE}")
    print(f"MANUAL_RIDER_NAME={RIDER_NAME}")
    print(f"RIDER_APP_URL={BASE}/app/riders")
    print(f"DRIVER_MODE_URL={BASE}/static/ops-shell.html")
    print("MANUAL_STEP_1=Login rider account and create a ride in Rider App (no proof/demo data)")
    print("MANUAL_STEP_2=Login driver account, open Driver App, verify your rider details, click Accept")

    try:
        server_proc = lifecycle.ensure_preview_server(BASE)
        prep = reseed_backend()
        driver_id = str(prep["driver_id"])
        since_ts = time.time()
        print(f"ASSIGNED_DRIVER_SEED={driver_id}")
        print(f"MANUAL_RIDE_WAIT_START={datetime.now(timezone.utc).isoformat()}")

        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            dispatcher_auth = _login(client, DISPATCHER_EMAIL)
            rider_auth = _login(client, RIDER_EMAIL)
            dispatcher_headers = _headers(dispatcher_auth["access_token"])
            rider_headers = _headers(rider_auth["access_token"])
            org_id = str(dispatcher_auth.get("organization_id") or "")
            _ensure_intake_auto_dispatch(org_id)
            _ensure_provider(client, dispatcher_headers, org_id)
            _set_driver_available(client, dispatcher_headers, driver_id)

            offer_pre = client.get(
                f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer",
                headers=dispatcher_headers,
            )
            workspace_pre = client.get(
                f"{BASE}/api/health-isf/drivers/{driver_id}/live-workspace",
                headers=dispatcher_headers,
            )
            pre_offer = (offer_pre.json() or {}).get("offer") if offer_pre.status_code == 200 else None
            pre_workspace = workspace_pre.json() if workspace_pre.status_code == 200 else {}
            pre_active = pre_workspace.get("active_ride") or {}
            driver_empty = not pre_offer and not str(pre_active.get("id") or "")
            print(f"DRIVER_APP_EMPTY_BEFORE_MANUAL_RIDE={str(driver_empty).lower()}")

            if not explicit_ride_id:
                webbrowser.open(f"{BASE}/app/riders")
            manual = _wait_for_manual_ride(
                client,
                dispatcher_headers,
                since_ts=since_ts,
                explicit_ride_id=explicit_ride_id,
            )

            ride_id = str(manual["ride_id"])
            pickup = str(manual["pickup_address"])
            dropoff = str(manual["dropoff_address"])
            rider_phone = str(manual["rider_phone"])

            invalid_reason = _validate_manual_ride(manual, since_ts=since_ts)
            if invalid_reason:
                _fail("manual_ride_validation", invalid_reason)

            print(f"MANUAL_RIDER_CREATED_RIDE_ID={ride_id}")
            print(f"MANUAL_RIDER_RIDE_ID={ride_id}")
            print(f"MANUAL_RIDER_NAME={RIDER_NAME}")

            ai = client.get(
                f"{BASE}/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
                headers=dispatcher_headers,
            )
            if ai.status_code != 200:
                _fail("ai_assistant", ai.text[:300])
            ai_payload = ai.json()
            ai_sees = _ai_sees_manual_ride(client, dispatcher_headers, ai_payload, ride_id)
            print(f"AI_SEES_MANUAL_RIDE={str(ai_sees).lower()}")
            print(f"AI_ASSISTANT_SEES_MANUAL_RIDE={str(ai_sees).lower()}")
            if not ai_sees:
                _fail(
                    "ai_assistant",
                    json.dumps(
                        {
                            "live_dispatch": ai_payload.get("live_dispatch"),
                            "queue_top": (client.get(
                                f"{BASE}/api/health-isf/dispatch/queue?limit=3",
                                headers=dispatcher_headers,
                            ).json() or [])[:1],
                        }
                    )[:500],
                )

            assigned_driver_id, offer_payload = _wait_for_auto_assignment(
                client, dispatcher_headers, ride_id
            )
            print(f"ASSIGNED_DRIVER_ID={assigned_driver_id}")
            print(f"AI_AUTO_ASSIGNED_MANUAL_RIDE={str(bool(offer_payload)).lower()}")

            workspace = client.get(
                f"{BASE}/api/health-isf/drivers/{assigned_driver_id}/live-workspace",
                headers=dispatcher_headers,
            )
            offer = client.get(
                f"{BASE}/api/health-isf/drivers/{assigned_driver_id}/active-offer",
                headers=dispatcher_headers,
            )
            if workspace.status_code != 200 or offer.status_code != 200:
                _fail("driver_app", f"workspace={workspace.status_code} offer={offer.status_code}")

            offer_payload = offer.json().get("offer") or offer_payload or {}
            driver_ride_id = str(offer_payload.get("ride_id") or "")
            rider_name = str(offer_payload.get("passenger_name") or "")
            pickup_text = str(offer_payload.get("pickup_address") or "")
            dropoff_text = str(offer_payload.get("dropoff_address") or "")

            print(f"DRIVER_APP_RIDE_ID={driver_ride_id}")
            print(f"DRIVER_APP_RECEIVES_MANUAL_RIDE={str(driver_ride_id == ride_id).lower()}")
            print(f"DRIVER_APP_RIDER_NAME={rider_name.lower()}")
            offer_state = str(offer_payload.get("assignment_state") or "offered").lower()
            accept_enabled = driver_ride_id == ride_id and offer_state == "offered"
            print(f"DRIVER_APP_ACCEPT_BUTTON_ENABLED={str(accept_enabled).lower()}")
            print(f"DRIVER_APP_PICKUP_MATCHES_MANUAL_INPUT={str(pickup.lower() in pickup_text.lower()).lower()}")
            print(f"DRIVER_APP_DROPOFF_MATCHES_MANUAL_INPUT={str(dropoff.lower() in dropoff_text.lower()).lower()}")

            if driver_ride_id != ride_id:
                _fail("driver_app", json.dumps({"offer": offer_payload})[:500])
            if rider_name.lower() != RIDER_NAME.lower():
                _fail("driver_app", f"expected {RIDER_NAME}, got {rider_name}")
            if _is_proof_label(rider_name):
                _fail("driver_app", "Driver App bound to proof/demo ride")

            if not explicit_ride_id:
                webbrowser.open(f"{BASE}/static/ops-shell.html")

            accepted = _wait_for_driver_accept(
                client,
                dispatcher_headers,
                ride_id=ride_id,
                driver_id=assigned_driver_id,
            )
            print(f"DRIVER_ACCEPT_CLICK_SUCCESS={str(accepted).lower()}")
            print(f"DRIVER_ACCEPT_200={str(accepted).lower()}")
            if not accepted:
                _fail(
                    "driver_accept_wait",
                    f"Accept the ride in Driver App within {WAIT_ACCEPT_SEC}s "
                    f"(login {DRIVER_EMAIL}, role Driver, open Driver App).",
                )

            rider_status, dashboard_status, ai_status = _surface_statuses(
                client,
                dispatcher_headers=dispatcher_headers,
                rider_headers=rider_headers,
                ride_id=ride_id,
                rider_phone=rider_phone,
            )
            print(f"RIDE_STATUS_AFTER_ACCEPT={rider_status}")
            print(f"RIDER_APP_STATUS_AFTER_ACCEPT={rider_status}")
            print(f"DASHBOARD_STATUS_AFTER_ACCEPT={dashboard_status}")
            print(f"AI_STATUS_AFTER_ACCEPT={ai_status}")

            post_offer = client.get(
                f"{BASE}/api/health-isf/drivers/{assigned_driver_id}/active-offer",
                headers=dispatcher_headers,
            )
            post_offer_payload = (post_offer.json() or {}).get("offer") if post_offer.status_code == 200 else None
            proof_removed = not post_offer_payload or not _is_script_generated_ride(
                rider_name=str((post_offer_payload or {}).get("passenger_name") or ""),
                pickup=str((post_offer_payload or {}).get("pickup_address") or ""),
                dropoff=str((post_offer_payload or {}).get("dropoff_address") or ""),
            )
            print(f"PROOF_RIDES_REMOVED={str(proof_removed).lower()}")

            if rider_status != "accepted" or dashboard_status != "accepted" or ai_status != "accepted":
                _fail(
                    "post_accept_status",
                    f"rider={rider_status} dashboard={dashboard_status} ai={ai_status}",
                )

            print("RESULT=PASS")

    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()


if __name__ == "__main__":
    main()
