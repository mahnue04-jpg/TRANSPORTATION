#!/usr/bin/env python3
"""Verify production provider visibility on Render."""

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


def main() -> int:
    print("=== Production provider verification ===")
    print("base:", BASE)

    health_status, health = _request("GET", "/api/health")
    print("health:", health_status, health if isinstance(health, dict) else str(health)[:120])
    if health_status != 200:
        print("PROVIDERS_VISIBLE=false")
        print("PROVIDER_API_OK=false")
        print("RIDE_CREATE_UNBLOCKED=false")
        print("READY_TO_CONTINUE_E2E_TEST=false")
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
        print("PROVIDERS_VISIBLE=false")
        print("PROVIDER_API_OK=false")
        print("RIDE_CREATE_UNBLOCKED=false")
        print("READY_TO_CONTINUE_E2E_TEST=false")
        return 1

    token = login.get("access_token")
    org_id = login.get("organization_id")
    if not token:
        print("PROVIDERS_VISIBLE=false")
        print("PROVIDER_API_OK=false")
        print("RIDE_CREATE_UNBLOCKED=false")
        print("READY_TO_CONTINUE_E2E_TEST=false")
        return 1

    provider_path = "/api/health-isf/providers"
    if org_id:
        provider_path += f"?organization_id={org_id}"
    provider_status, providers = _request(
        "GET",
        provider_path,
        headers={"Authorization": f"Bearer {token}"},
    )
    count = len(providers) if isinstance(providers, list) else 0
    names = []
    if isinstance(providers, list):
        names = [str(item.get("name", item.get("id", ""))) for item in providers[:5] if isinstance(item, dict)]
    print("providers:", provider_status, "count=", count, "sample=", names)

    providers_visible = provider_status == 200 and count > 0
    provider_api_ok = provider_status == 200
    ride_create_unblocked = providers_visible
    ready = providers_visible and provider_api_ok

    print("PROVIDERS_VISIBLE=" + ("true" if providers_visible else "false"))
    print("PROVIDER_API_OK=" + ("true" if provider_api_ok else "false"))
    print("RIDE_CREATE_UNBLOCKED=" + ("true" if ride_create_unblocked else "false"))
    print("READY_TO_CONTINUE_E2E_TEST=" + ("true" if ready else "false"))
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
