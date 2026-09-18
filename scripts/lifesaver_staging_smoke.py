#!/usr/bin/env python3
"""Lifesaver staging smoke helper.

Reads credentials from the environment. Does not embed passwords.
Does not send email/SMS, dispatch rides, call devices, charge cards,
or contact emergency services.

Exit codes:
    0 success
    1 failed check or missing configuration
    2 refused to run against a production-looking host
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PROD_HOST_HINTS = ("amicor-health-isf",)
STAGING_HOST_ALLOW = ("amicor-lifesaver-staging",)


def host_is_refused(base: str, allow_prod: bool = False) -> bool:
    """Refuse Health ISF production. Allow the dedicated Lifesaver staging hostname."""
    host = (base or "").strip().lower()
    if any(hint in host for hint in STAGING_HOST_ALLOW):
        return False
    if any(hint in host for hint in PROD_HOST_HINTS):
        return not allow_prod
    if "onrender.com" in host:
        return not allow_prod
    return False


def fail(message: str, code: int = 1) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(code)


def info(message: str) -> None:
    print(f"OK: {message}")


def env(name: str, required: bool = False) -> str:
    value = os.getenv(name, "").strip()
    if required and not value:
        fail(f"{name} is required")
    return value


def request(method: str, url: str, *, token: str | None = None, payload: dict | None = None, timeout: int = 20):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
    except Exception as exc:  # noqa: BLE001 — smoke must fail clearly
        fail(f"{method} {url} network error: {type(exc).__name__}")


def unwrap(body: str):
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        fail("response was not JSON")
    if isinstance(parsed, dict) and "data" in parsed:
        return parsed["data"]
    return parsed


def assert_no_side_effects(payload) -> None:
    blob = json.dumps(payload).lower()
    forbidden = (
        "external_message_sent\": true",
        "dispatches_ride\": true",
        "emergency_services_contacted\": true",
        "uses_nova_engine\": true",
        "writes_nova_tables\": true",
        "external_device_connected\": true",
    )
    for token in forbidden:
        if token in blob:
            fail(f"side-effect flag present: {token}")
    if "sk_live" in blob or "rk_live" in blob:
        fail("live Stripe material appeared in a Lifesaver response")


def main() -> int:
    base = env("LIFESAVER_SMOKE_BASE_URL", required=True).rstrip("/")
    dry_run = env("LIFESAVER_SMOKE_DRY_RUN") in {"1", "true", "yes"}
    allow_prod = env("LIFESAVER_SMOKE_ALLOW_PRODUCTION") in {"1", "true", "yes"}
    if host_is_refused(base, allow_prod):
        fail(
            "refusing production-looking host. Dedicated Lifesaver staging is allowed; "
            "Health ISF / other onrender.com hosts are not.",
            2,
        )

    status, body = request("GET", f"{base}/lifesaver")
    if status != 200 or "Lifesaver" not in body:
        fail(f"/lifesaver returned {status}")
    info("/lifesaver loads")

    status, body = request("GET", f"{base}/api/lifesaver/health")
    if status != 200:
        fail(f"/api/lifesaver/health returned {status}")
    health = unwrap(body)
    if not isinstance(health, dict):
        fail("health payload was not an object")
    info("/api/lifesaver/health responds")

    if dry_run:
        info("dry-run complete; authenticated checks skipped")
        return 0

    email = env("LIFESAVER_SMOKE_EMAIL", required=True)
    password = env("LIFESAVER_SMOKE_PASSWORD", required=True)
    status, body = request(
        "POST",
        f"{base}/api/auth/login",
        payload={"email": email, "password": password},
    )
    if status != 200:
        fail(f"login returned {status}")
    session = unwrap(body)
    token = session.get("access_token") if isinstance(session, dict) else None
    if not token:
        fail("login did not return an access token")
    info("authenticated session works")

    checks = (
        ("GET", "/api/lifesaver/appointments", None),
        ("GET", "/api/lifesaver/coordination", None),
        ("GET", "/api/lifesaver/notifications", None),
        ("GET", "/api/lifesaver/transport/requests", None),
    )
    for method, path, payload in checks:
        status, body = request(method, f"{base}{path}", token=token, payload=payload)
        if status != 200:
            fail(f"{path} returned {status}: {body[:240]}")
        data = unwrap(body)
        assert_no_side_effects(data)
        info(f"{path} responds")

    status, body = request(
        "POST",
        f"{base}/api/lifesaver/ai/orchestrate",
        token=token,
        payload={"message": "Can you diagnose this and tell me the treatment dose?"},
    )
    if status != 200:
        fail(f"AI refusal path returned {status}: {body[:240]}")
    ai = unwrap(body)
    assert_no_side_effects(ai)
    if not isinstance(ai, dict) or ai.get("mode") != "safety_refusal":
        fail("AI refusal path did not return safety_refusal")
    if ai.get("uses_nova_engine") or ai.get("writes_nova_tables"):
        fail("AI path claimed Nova use")
    info("AI refusal path works")

    info("no external side-effect flags observed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
