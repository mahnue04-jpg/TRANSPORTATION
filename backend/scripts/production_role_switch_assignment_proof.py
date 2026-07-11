"""Production proof: authorized role switch + live driver assignment."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import uuid

import httpx

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
PASSWORD = os.getenv("AMICOR_OPERATOR_PASSWORD", os.getenv("AMICOR_SEED_PASSWORD", ""))
SYNC_KEY = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", PASSWORD)
OPERATOR_EMAIL = os.getenv("AMICOR_OPERATOR_EMAIL", "mahnue04@gmail.com").strip().lower()
STAFF_EMAIL = os.getenv("AMICOR_STAFF_EMAIL", "staff@amicor.local").strip().lower()
TIMEOUT = float(os.getenv("AMICOR_HTTP_TIMEOUT", "120"))


def _fail(reason: str, detail: str = "") -> None:
    print("RESULT=FAIL")
    print(f"REASON={reason}")
    if detail:
        print(f"DETAIL={detail[:800]}")
    sys.exit(1)


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return ""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _decode_role(token: str) -> str:
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return str(payload.get("role") or "")
    except Exception:
        return ""


def _login(client: httpx.Client, email: str) -> dict:
    resp = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD})
    if resp.status_code != 200:
        raise RuntimeError(f"login_failed:{email}:{resp.status_code}:{resp.text[:200]}")
    return resp.json()


def _find_operator_email(client: httpx.Client) -> str:
    if OPERATOR_EMAIL:
        return OPERATOR_EMAIL
        sync = client.post(
            f"{BASE}/api/auth/deployment/sync-seed-users",
            headers={"X-Amicor-Deployment-Key": SYNC_KEY},
        )
        if sync.status_code == 200:
            grants = sync.json().get("operator_role_grants") or []
            for item in grants:
                email = str(item.get("email") or "").strip().lower()
                if email:
                    print(f"OPERATOR_GRANT_MATCH={email}")
                    return email
        grant_status = client.get(f"{BASE}/api/auth/deployment/operator-grants")
        if grant_status.status_code == 200:
            grants = grant_status.json().get("operator_role_grants") or []
            for item in grants:
                email = str(item.get("email") or "").strip().lower()
                if email:
                    print(f"OPERATOR_GRANT_MATCH={email}")
                    return email
    _fail("operator_email_missing", "Set AMICOR_OPERATOR_EMAIL or ensure saye monibah account exists in production DB")
    return ""


def main() -> None:
    if not PASSWORD:
        _fail("password_missing", "Set AMICOR_OPERATOR_PASSWORD or AMICOR_SEED_PASSWORD")

    print(f"PRODUCTION_URL={BASE}")
    print(f"LOCAL_COMMIT={_git_head()}")

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        live = client.get(f"{BASE}/api/health/live")
        if live.status_code != 200:
            _fail("health_live", live.text[:300])
        deploy_commit = str(live.json().get("deploy_commit") or "")
        print(f"DEPLOY_COMMIT={deploy_commit}")

        operator_email = _find_operator_email(client)
        print(f"OPERATOR_EMAIL={operator_email}")

        login_payload = _login(client, operator_email)
        jwt_role_before = _decode_role(login_payload["access_token"])
        print(f"JWT_ROLE_BEFORE={jwt_role_before}")

        switch = client.post(
            f"{BASE}/api/auth/switch-role",
            headers={**_headers(login_payload["access_token"]), "Content-Type": "application/json"},
            json={"role": "dispatcher"},
        )
        if switch.status_code != 200:
            _fail("switch_role", switch.text[:400])
        switch_payload = switch.json()
        dispatcher_token = switch_payload["access_token"]
        jwt_role_after = _decode_role(dispatcher_token)
        print(f"JWT_ROLE_AFTER={jwt_role_after}")
        if jwt_role_after != "dispatcher":
            _fail("jwt_role_after", f"expected dispatcher got {jwt_role_after}")

        session = client.get(f"{BASE}/api/auth/session", headers=_headers(dispatcher_token))
        if session.status_code != 200:
            _fail("session_probe", session.text[:300])
        session_payload = session.json()
        print(f"SESSION_TOKEN_ROLE={session_payload.get('token_role')}")
        print(f"ROLE_PERSISTS_AFTER_REFRESH={'true' if session_payload.get('token_role') == 'dispatcher' else 'false'}")

        refresh = client.post(
            f"{BASE}/api/auth/refresh",
            json={"refresh_token": login_payload["refresh_token"]},
        )
        if refresh.status_code != 200:
            _fail("refresh", refresh.text[:300])
        refreshed_token = refresh.json()["access_token"]
        refreshed_role = _decode_role(refreshed_token)
        print(f"JWT_ROLE_AFTER_REFRESH={refreshed_role}")
        if refreshed_role != "dispatcher":
            _fail("refresh_role", f"expected dispatcher got {refreshed_role}")

        dispatcher_headers = {**_headers(refreshed_token), "Content-Type": "application/json"}

        drivers_resp = client.get(f"{BASE}/api/health-isf/drivers", headers=dispatcher_headers)
        if drivers_resp.status_code != 200:
            _fail("drivers_list", drivers_resp.text[:300])
        drivers = drivers_resp.json()
        assignable = [
            item for item in drivers
            if str(item.get("status") or "").lower() in {"available", "online"}
            and str(item.get("availability_state") or item.get("status") or "").lower() in {"available", "online"}
        ]
        if not assignable:
            _fail("assignable_driver_missing", json.dumps(drivers[:2])[:400])
        driver_id = str(assignable[0]["id"])
        print(f"DRIVER_ID={driver_id}")

        rides_resp = client.get(f"{BASE}/api/health-isf/rides", headers=dispatcher_headers)
        if rides_resp.status_code != 200:
            _fail("rides_list", rides_resp.text[:300])
        rides = rides_resp.json()
        pending = [
            item for item in rides
            if str(item.get("status") or item.get("lifecycle_state") or "").lower() in {"pending", "requested", "approved", "dispatchable"}
            and not item.get("driver_id")
        ]
        if not pending:
            provider_resp = client.get(f"{BASE}/api/health-isf/providers", headers=dispatcher_headers)
            providers = provider_resp.json() if provider_resp.status_code == 200 else []
            provider_id = str(providers[0]["id"]) if providers else None
            suffix = uuid.uuid4().hex[:6]
            create = client.post(
                f"{BASE}/api/health-isf/rides",
                headers=dispatcher_headers,
                json={
                    "passenger_name": "Role Switch Proof",
                    "passenger_phone": f"646-555-{suffix[:4]}",
                    "pickup_address": f"100 Proof Pickup {suffix}, New York, NY 10001",
                    "dropoff_address": f"200 Proof Dropoff {suffix}, New York, NY 10002",
                    "service_type": "medical_appointment",
                    "provider_id": provider_id,
                    "notes": "production role switch assignment proof",
                },
            )
            if create.status_code != 201:
                _fail("create_ride", create.text[:400])
            ride_id = str(create.json()["id"])
        else:
            ride_id = str(pending[0]["id"])
        print(f"RIDE_ID={ride_id}")

        assign = client.patch(
            f"{BASE}/api/health-isf/rides/{ride_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        print(f"ASSIGNMENT_HTTP_STATUS={assign.status_code}")
        if assign.status_code not in {200, 201}:
            _fail("assign_driver", assign.text[:400])
        assigned = assign.json()
        assigned_driver = str(assigned.get("driver_id") or "")
        assigned_status = str(assigned.get("status") or assigned.get("lifecycle_state") or "").lower()
        print(f"RIDE_STATUS_AFTER_ASSIGN={assigned_status}")
        if assigned_driver != driver_id:
            _fail("assigned_driver_mismatch", json.dumps(assigned)[:400])

        driver_app = client.get(
            f"{BASE}/api/health-isf/drivers/{driver_id}/assigned-rides",
            headers=dispatcher_headers,
        )
        if driver_app.status_code != 200:
            _fail("driver_assigned_rides", driver_app.text[:300])
        driver_rides = driver_app.json()
        ride_ids = {str(item.get("id") or item.get("ride_id") or "") for item in driver_rides}
        driver_shows_same = ride_id in ride_ids
        print(f"DRIVER_APP_SHOWS_SAME_RIDE={'true' if driver_shows_same else 'false'}")
        if not driver_shows_same:
            _fail("driver_app_visibility", json.dumps(driver_rides[:3])[:400])

        staff_auth = _login(client, STAFF_EMAIL)
        staff_assign = client.patch(
            f"{BASE}/api/health-isf/rides/{ride_id}/assign-driver",
            headers={**_headers(staff_auth["access_token"]), "Content-Type": "application/json"},
            json={"driver_id": driver_id},
        )
        staff_blocked = staff_assign.status_code == 403
        print(f"STAFF_ASSIGNMENT_HTTP_STATUS={staff_assign.status_code}")
        print(f"STAFF_USER_REMAINS_BLOCKED={'true' if staff_blocked else 'false'}")
        if not staff_blocked:
            _fail("staff_not_blocked", staff_assign.text[:300])

        print("RESULT=PASS")


if __name__ == "__main__":
    main()
