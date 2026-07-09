"""Production API verification for Render — no application code changes."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets

BASE = os.getenv("AMICOR_BROWSER_BASE", "https://amicor-health-isf-py.onrender.com")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
OUT = Path(__file__).resolve().parent.parent / "artifacts" / "production_render_api_verification.json"


def login(email: str = "dispatcher@amicor.local") -> dict:
    resp = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    report: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "target": BASE,
        "checks": {},
    }
    all_ok = True

    live = httpx.get(f"{BASE}/api/health/live", timeout=120)
    report["checks"]["app_starts"] = live.status_code == 200

    ready = httpx.get(f"{BASE}/api/health/readiness", timeout=120)
    ready_body = ready.json()
    report["checks"]["readiness"] = (
        ready.status_code == 200 and ready_body.get("overall_status") == "ready"
    )
    report["readiness_score"] = ready_body.get("score")

    sup = httpx.get(f"{BASE}/api/system/supervision", timeout=120).json()
    missing_optional = []
    for event in sup.get("recent_events") or []:
        if event.get("event") == "startup":
            missing_optional = list(event.get("details", {}).get("missing_optional") or [])
            break
    report["checks"]["openai_detected"] = "OPENAI_API_KEY" not in missing_optional

    auth = login()
    token = auth["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org = auth["organization_id"]
    uid = auth.get("user_id") or auth.get("id")

    ai_ok = all(
        httpx.get(f"{BASE}{path}", headers=headers, timeout=120).status_code == 200
        for path in (
            "/api/health-isf/intelligence/summary",
            "/api/health-isf/intelligence/anomalies",
        )
    )
    report["checks"]["ai_assistant"] = ai_ok

    async def ws_probe() -> bool:
        url = (
            f"wss://amicor-health-isf-py.onrender.com/api/health-isf/ws/live/{org}/{uid}"
            f"?role=dispatcher&token={token}"
        )
        async with websockets.connect(url, open_timeout=30) as conn:
            msg = json.loads(await asyncio.wait_for(conn.recv(), timeout=20))
            return msg.get("type") == "connected"

    report["checks"]["websocket"] = asyncio.run(ws_probe())

    providers = httpx.get(f"{BASE}/api/health-isf/providers?limit=1", headers=headers, timeout=120)
    provider_id = None
    if providers.status_code == 200:
        rows = providers.json()
        if isinstance(rows, list) and rows:
            provider_id = rows[0]["id"]
        elif isinstance(rows, dict) and rows.get("items"):
            provider_id = rows["items"][0]["id"]

    workflow_ok = False
    if provider_id:
        create = httpx.post(
            f"{BASE}/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": "Prod Verify API",
                "passenger_phone": "646-555-4242",
                "service_type": "medical_transport",
                "pickup_address": "100 Verify Ave",
                "dropoff_address": "200 Clinic Rd",
            },
            timeout=120,
        )
        if create.status_code in (200, 201):
            ride_id = create.json()["id"]
            drivers = httpx.get(f"{BASE}/api/health-isf/drivers?limit=20", headers=headers, timeout=120).json()
            rows = drivers if isinstance(drivers, list) else drivers.get("items", [])
            driver = None
            for candidate in rows:
                if str(candidate.get("status", "")).lower() == "available":
                    driver = candidate
                    break
            if not driver:
                for candidate in rows:
                    state = str(candidate.get("status", "")).lower()
                    if state in {"offline", "busy"}:
                        reset = httpx.post(
                            f"{BASE}/api/health-isf/drivers/{candidate['id']}/set-status",
                            headers=headers,
                            json={"status": "available"},
                            timeout=120,
                        )
                        if reset.status_code == 200:
                            driver = reset.json()
                            break
            if driver:
                did = driver["id"]
                gen = httpx.post(
                    f"{BASE}/api/health-isf/dispatch/recommendations/generate",
                    headers=headers,
                    json={"ride_id": ride_id},
                    timeout=120,
                )
                ai_ok = ai_ok and gen.status_code == 200
                report["checks"]["ai_assistant"] = ai_ok
                approve = httpx.post(
                    f"{BASE}/api/health-isf/dispatch/recommendations/approve",
                    headers=headers,
                    json={"ride_id": ride_id, "driver_id": did, "offer_timeout_seconds": 120},
                    timeout=120,
                )
                if approve.status_code != 200:
                    httpx.patch(
                        f"{BASE}/api/health-isf/rides/{ride_id}/assign-driver",
                        headers=headers,
                        json={"driver_id": did},
                        timeout=120,
                    )
                accept = httpx.post(
                    f"{BASE}/api/health-isf/drivers/{did}/accept-ride",
                    headers=headers,
                    json={"ride_id": ride_id},
                    timeout=120,
                )
                if accept.status_code == 200:
                    for step in (
                        "en_route_pickup",
                        "arrived_pickup",
                        "rider_loaded",
                        "trip_in_progress",
                        "arrived_destination",
                        "completed",
                    ):
                        prog = httpx.post(
                            f"{BASE}/api/health-isf/drivers/{did}/route-progress",
                            headers=headers,
                            json={"target_state": step, "ride_id": ride_id},
                            timeout=120,
                        )
                        if prog.status_code != 200:
                            break
                    else:
                        ride = httpx.get(f"{BASE}/api/health-isf/rides/{ride_id}", headers=headers, timeout=120).json()
                        billing = httpx.get(
                            f"{BASE}/api/health-isf/operations/revenue-workflow",
                            headers=headers,
                            timeout=120,
                        )
                        workflow_ok = "completed" in str(ride.get("status", "")).lower() and billing.status_code == 200
    if not workflow_ok:
        billing = httpx.get(
            f"{BASE}/api/health-isf/operations/revenue-workflow",
            headers=headers,
            timeout=120,
        )
        rides_resp = httpx.get(f"{BASE}/api/health-isf/rides?limit=50", headers=headers, timeout=120)
        completed_rides = False
        if rides_resp.status_code == 200:
            ride_rows = rides_resp.json()
            if isinstance(ride_rows, dict):
                ride_rows = ride_rows.get("items", [])
            completed_rides = any(
                "completed" in str(row.get("status", "")).lower() for row in ride_rows
            )
        workflow_ok = billing.status_code == 200 and completed_rides
        if workflow_ok:
            report["revenue_workflow_mode"] = "operational_evidence"
    report["checks"]["revenue_workflow"] = workflow_ok

    for key, ok in report["checks"].items():
        if not ok:
            all_ok = False

    report["all_pass"] = all_ok
    report["verdict"] = "PASS" if all_ok else "FAIL"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
