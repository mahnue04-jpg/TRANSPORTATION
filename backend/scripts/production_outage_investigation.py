#!/usr/bin/env python3
"""Investigate production outage: API latency, round-trip records, accept state."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.production_auth import resolve_production_tokens  # noqa: E402

BASE = "https://amicor-health-isf-py.onrender.com"
OUT_DIR = REPO / "PRODUCTION_QA_EVIDENCE"
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
RIDER_NAME = "nhya monibah"
DRIVER_1004_PHONE = "917-555-1004"
KNOWN_RIDE_IDS = (
    "fc597a7e-5d96-4b38-a3d0-2f69e236b05a",
    "377d7272-e494-40b0-9c82-0f4083317e27",
    "cbf465a3-da64-4c70-99c2-b6f750e302f5",
    "780eb4fb-0cd9-46b1-8924-9530414685b4",
)


def auth_probe(method: str, path: str, token: str, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    headers.update(kwargs.pop("headers", {}))
    url = f"{BASE}{path}"
    start = time.perf_counter()
    try:
        resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:800]
        return {
            "path": path,
            "status": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "body_preview": body if not isinstance(body, list) else {"count": len(body), "sample": body[:2]},
        }
    except requests.RequestException as exc:
        return {
            "path": path,
            "status": 0,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "error": str(exc),
        }


def driver_mobile_login(phone: str) -> dict:
    start = time.perf_counter()
    resp = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": phone},
        timeout=120,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    body = resp.json() if resp.content else {}
    return {"status": resp.status_code, "elapsed_ms": elapsed_ms, "body": body}


def main() -> int:
    auth = resolve_production_tokens()
    token = auth.get("dispatcher_token") if auth.get("ok") else ""
    if not token:
        print("ERROR: no production auth token", file=sys.stderr)
        return 1

    api_paths = [
        "/api/health/live",
        "/api/system/health",
        "/api/health/readiness",
        "/api/health-isf/dispatch/queue?limit=200",
        "/api/health-isf/dispatch/queue?limit=80&read_only=true",
        "/api/health-isf/dispatch/active-assignments?limit=200",
        "/api/health-isf/drivers?limit=120",
        "/api/health-isf/rides?limit=200&active_only=true&exclude_test=true",
        "/api/health-isf/providers?limit=200",
        "/api/health-isf/customer-requests?limit=200",
        "/api/health-isf/operations/billing-handoffs?limit=100",
        "/api/health-isf/operations/admin-revenue",
        "/api/health-isf/operations/revenue-workflow?window_hours=24",
        "/api/health-isf/activity-feed?limit=40",
    ]

    probes = [auth_probe("GET", path, token) for path in api_paths]

    rides_detail = []
    for ride_id in KNOWN_RIDE_IDS:
        row = auth_probe("GET", f"/api/health-isf/rides/{ride_id}", token)
        body = row.get("body_preview") or {}
        if isinstance(body, dict):
            rides_detail.append(
                {
                    "ride_id": ride_id,
                    "status": body.get("status") or body.get("lifecycle_state"),
                    "driver_id": body.get("driver_id"),
                    "pickup_time": body.get("pickup_time"),
                    "trip_leg": body.get("trip_leg"),
                    "round_trip_group_id": body.get("round_trip_group_id"),
                    "customer_request_id": body.get("customer_request_id"),
                    "passenger_name": body.get("passenger_name") or body.get("rider_name"),
                }
            )

    nhya_rides = []
    rides_probe = next(p for p in probes if "rides?limit=200" in p["path"])
    body = rides_probe.get("body_preview") or {}
    if isinstance(body, dict) and "sample" in body:
        for row in body.get("sample", []):
            name = str(row.get("passenger_name") or row.get("rider_name") or "").lower()
            if "nhya" in name or "monibah" in name:
                nhya_rides.append(row)
    elif isinstance(body, list):
        for row in body:
            name = str(row.get("passenger_name") or row.get("rider_name") or "").lower()
            if "nhya" in name or "monibah" in name:
                nhya_rides.append(row)

    mobile = driver_mobile_login(DRIVER_1004_PHONE)
    driver_id = None
    if isinstance(mobile.get("body"), dict):
        driver_id = mobile["body"].get("driver_id") or mobile["body"].get("id")

    upcoming = None
    if driver_id:
        upcoming = auth_probe(
            "GET",
            f"/api/health-isf/drivers/{driver_id}/upcoming-schedule",
            token,
        )

    deploy = auth_probe("GET", "/api/health/live", token)
    deploy_commit = None
    body = deploy.get("body_preview")
    if isinstance(body, dict):
        deploy_commit = body.get("deploy_commit") or body.get("git_commit")

    report = {
        "run_ts": RUN_TS,
        "base": BASE,
        "deploy_commit": deploy_commit,
        "api_probes": probes,
        "known_round_trip_rides": rides_detail,
        "nhya_rides_from_list": nhya_rides,
        "driver_1004_mobile_login": mobile,
        "driver_1004_upcoming_schedule": upcoming,
        "slowest_endpoints": sorted(
            [p for p in probes if p.get("elapsed_ms")],
            key=lambda x: x["elapsed_ms"],
            reverse=True,
        )[:5],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"PRODUCTION_OUTAGE_INVESTIGATION_{RUN_TS}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "deploy_commit": deploy_commit, "slowest": report["slowest_endpoints"][:3]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
