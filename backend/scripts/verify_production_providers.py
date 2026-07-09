#!/usr/bin/env python3
"""Verify production provider and driver visibility on Render."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
EMAIL = os.getenv("AMICOR_VERIFY_EMAIL", "dispatcher@amicor.local")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
SYNC_KEY = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", PASSWORD)


def _request(method: str, path: str, *, body: dict | None = None, headers: dict | None = None) -> tuple[int, object]:
    url = BASE + path
    data = None
    req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = raw
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload


def _list_count(status: int, payload: object) -> tuple[int, list[str]]:
    if status != 200 or not isinstance(payload, list):
        return 0, []
    names = [str(item.get("name", item.get("id", ""))) for item in payload[:8] if isinstance(item, dict)]
    return len(payload), names


def main() -> int:
    print("=== Production ops verification ===")
    print("base:", BASE)

    health_status, _health = _request("GET", "/api/health")
    print("health:", health_status)
    if health_status != 200:
        _print_flags(False)
        return 1

    sync_status, sync_body = _request(
        "POST",
        "/api/auth/deployment/sync-seed-users",
        headers={"X-Amicor-Deployment-Key": SYNC_KEY},
    )
    print("deployment_sync:", sync_status, sync_body if isinstance(sync_body, dict) else str(sync_body)[:200])

    login_status, login = _request("POST", "/api/auth/login", body={"email": EMAIL, "password": PASSWORD})
    print("login:", login_status)
    if login_status != 200 or not isinstance(login, dict):
        _print_flags(False)
        return 1

    token = login.get("access_token")
    org_id = login.get("organization_id")
    if not token:
        _print_flags(False)
        return 1

    auth_headers = {"Authorization": f"Bearer {token}"}
    org_q = f"?organization_id={org_id}" if org_id else ""

    provider_status, providers = _request("GET", f"/api/health-isf/providers{org_q}", headers=auth_headers)
    provider_count, provider_names = _list_count(provider_status, providers)
    print("providers:", provider_status, "count=", provider_count, "sample=", provider_names)

    driver_status, drivers = _request("GET", f"/api/health-isf/drivers{org_q}", headers=auth_headers)
    driver_count, driver_names = _list_count(driver_status, drivers)
    print("drivers:", driver_status, "count=", driver_count, "sample=", driver_names)

    ride_status, rides = _request("GET", f"/api/health-isf/rides{org_q}", headers=auth_headers)
    pending = 0
    if ride_status == 200 and isinstance(rides, list):
        pending = sum(1 for ride in rides if str(ride.get("status", "")).lower() == "pending")
    print("rides:", ride_status, "pending=", pending)

    assignable = 0
    if isinstance(drivers, list):
        for driver in drivers:
            if not isinstance(driver, dict):
                continue
            availability = str(driver.get("availability_state", "")).lower()
            status = str(driver.get("status", "")).lower()
            if availability == "available" or status in {"available", "unavailable"}:
                assignable += 1

    providers_visible = provider_status == 200 and provider_count > 0
    drivers_visible = driver_status == 200 and driver_count >= 3
    dispatch_pending = ride_status == 200 and pending > 0
    assign_dropdown = assignable > 0
    driver_dropdown = driver_count >= 3
    ready = all([
        providers_visible,
        drivers_visible,
        assign_dropdown,
        driver_dropdown,
    ])

    print("PROVIDERS_VISIBLE=" + ("true" if providers_visible else "false"))
    print("DRIVERS_VISIBLE=" + ("true" if drivers_visible else "false"))
    print("DISPATCH_RIDE_PENDING=" + ("true" if dispatch_pending else "false"))
    print("DRIVER_ASSIGN_DROPDOWN_POPULATED=" + ("true" if assign_dropdown else "false"))
    print("DRIVER_PAGE_DROPDOWN_POPULATED=" + ("true" if driver_dropdown else "false"))
    print("PROVIDER_API_OK=" + ("true" if provider_status == 200 else "false"))
    print("RIDE_CREATE_UNBLOCKED=" + ("true" if providers_visible else "false"))
    print("READY_TO_CONTINUE_E2E_TEST=" + ("true" if ready else "false"))
    return 0 if ready else 1


def _print_flags(ok: bool) -> None:
    val = "true" if ok else "false"
    print("PROVIDERS_VISIBLE=" + val)
    print("DRIVERS_VISIBLE=" + val)
    print("DISPATCH_RIDE_PENDING=" + val)
    print("DRIVER_ASSIGN_DROPDOWN_POPULATED=" + val)
    print("DRIVER_PAGE_DROPDOWN_POPULATED=" + val)
    print("PROVIDER_API_OK=" + val)
    print("RIDE_CREATE_UNBLOCKED=" + val)
    print("READY_TO_CONTINUE_E2E_TEST=" + val)


if __name__ == "__main__":
    sys.exit(main())
