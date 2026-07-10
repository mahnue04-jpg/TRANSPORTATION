#!/usr/bin/env python3
"""Verify live Render production provider/driver fleet visibility."""

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

REQUIRED_PROVIDERS = {
    "Fairview Hospital",
    "HCMC",
    "North Memorial Health",
    "Amicor Test Clinic",
}
REQUIRED_DRIVERS = {
    "James Smith",
    "Maria Garcia",
    "David Chen",
    "Test Driver Four",
    "Test Driver Five",
    "Test Driver Six",
}


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
        with urllib.request.urlopen(req, timeout=120) as resp:
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


def _available_count(drivers: list[dict]) -> int:
    count = 0
    for driver in drivers:
        if not isinstance(driver, dict):
            continue
        if (
            str(driver.get("availability_state", "")).lower() == "available"
            and str(driver.get("status", "")).lower() == "available"
            and bool(driver.get("is_online"))
        ):
            count += 1
    return count


def main() -> int:
    print("=== Production fleet verification ===")
    print("base:", BASE)

    health_status, health = _request("GET", "/api/health")
    version = None
    if isinstance(health, dict):
        version = ((health.get("data") or {}).get("version")) or health.get("version")
    print("health:", health_status, "version=", version)

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
        print("RESULT=FAIL")
        return 1

    token = login.get("access_token")
    org_id = login.get("organization_id")
    if not token or not org_id:
        _print_flags(False)
        print("RESULT=FAIL")
        return 1

    auth_headers = {"Authorization": f"Bearer {token}"}
    org_q = f"?organization_id={org_id}"

    endpoints = {
        "providers": f"/api/health-isf/providers{org_q}",
        "drivers": f"/api/health-isf/drivers{org_q}",
        "driver_operations": f"/api/health-isf/driver-operations{org_q}",
        "dispatch_workspace": f"/api/health-isf/dispatch/workspace{org_q}",
        "bootstrap_status": f"/api/health-isf/operations/production-bootstrap-status{org_q}",
    }

    results: dict[str, tuple[int, object]] = {}
    for key, path in endpoints.items():
        results[key] = _request("GET", path, headers=auth_headers)

    provider_status, providers = results["providers"]
    driver_status, drivers = results["drivers"]
    driver_ops_status, driver_ops = results["driver_operations"]
    workspace_status, workspace = results["dispatch_workspace"]
    bootstrap_status, bootstrap = results["bootstrap_status"]

    provider_list = providers if isinstance(providers, list) else []
    driver_list = drivers if isinstance(drivers, list) else []
    provider_names = {str(item.get("name", "")) for item in provider_list if isinstance(item, dict)}
    driver_names = {str(item.get("name", "")) for item in driver_list if isinstance(item, dict)}
    available = _available_count(driver_list)

    print("organization_id:", org_id)
    print("database_type:", bootstrap.get("database_type") if isinstance(bootstrap, dict) else "unknown")
    print("providers:", provider_status, "count=", len(provider_list), "names=", sorted(provider_names))
    print("drivers:", driver_status, "count=", len(driver_list), "available=", available)
    print("driver_operations:", driver_ops_status)
    print("dispatch_workspace:", workspace_status)
    print("bootstrap_status:", bootstrap_status)

    providers_ok = provider_status == 200 and len(provider_list) >= 4 and REQUIRED_PROVIDERS.issubset(provider_names)
    drivers_ok = driver_status == 200 and len(driver_list) >= 6 and REQUIRED_DRIVERS.issubset(driver_names)
    assignable_ok = available >= 3
    ops_ok = driver_ops_status == 200
    workspace_ok = workspace_status == 200
    org_match = isinstance(bootstrap, dict) and str(bootstrap.get("organization_id")) == str(org_id)

    ready = all([providers_ok, drivers_ok, assignable_ok, ops_ok, workspace_ok, org_match])

    print("PRODUCTION_PROVIDER_API_STATUS=" + str(provider_status))
    print("PRODUCTION_PROVIDER_COUNT=" + str(len(provider_list)))
    print("PRODUCTION_DRIVER_API_STATUS=" + str(driver_status))
    print("PRODUCTION_DRIVER_COUNT=" + str(len(driver_list)))
    print("PRODUCTION_AVAILABLE_DRIVER_COUNT=" + str(available))
    print("PROVIDER_DROPDOWN_POPULATED=" + ("true" if providers_ok else "false"))
    print("DRIVER_DROPDOWN_POPULATED=" + ("true" if drivers_ok else "false"))
    print("DRIVER_OPERATIONS_FEED_LOADED=" + ("true" if ops_ok and drivers_ok else "false"))
    print("RECORDS_MATCH_ACTIVE_ORGANIZATION=" + ("true" if org_match else "false"))
    print("RESULT=" + ("PASS" if ready else "FAIL"))
    return 0 if ready else 1


def _print_flags(ok: bool) -> None:
    val = "true" if ok else "false"
    print("PRODUCTION_PROVIDER_API_STATUS=0")
    print("PRODUCTION_PROVIDER_COUNT=0")
    print("PRODUCTION_DRIVER_API_STATUS=0")
    print("PRODUCTION_DRIVER_COUNT=0")
    print("PRODUCTION_AVAILABLE_DRIVER_COUNT=0")
    print("PROVIDER_DROPDOWN_POPULATED=" + val)
    print("DRIVER_DROPDOWN_POPULATED=" + val)
    print("DRIVER_OPERATIONS_FEED_LOADED=" + val)
    print("RECORDS_MATCH_ACTIVE_ORGANIZATION=" + val)


if __name__ == "__main__":
    sys.exit(main())
