"""Diagnose production driver assignment sync for a specific driver ID."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND))

import production_auth as pa  # noqa: E402

BASE = pa.BASE.rstrip("/")
ORG = os.getenv("AMICOR_ORG_ID", "308dc05a-6781-4ef7-91fc-ff22606937e3")
DRIVER_ID = sys.argv[1] if len(sys.argv) > 1 else "93bb089a-d61f-4f53-8fe5-f2a110b0f9bd"
OUT = BACKEND.parent / "PRODUCTION_QA_EVIDENCE" / f"DRIVER_SYNC_DIAG_{DRIVER_ID[:8]}.json"


def probe_driver_endpoints(session_token: str, org_id: str) -> dict:
    headers = {"X-Driver-Session-Token": session_token, "Accept": "application/json"}
    params = {"organization_id": org_id}
    out: dict = {}
    for name in ("active-ride", "live-workspace", "active-offer", "assigned-rides", "completion-snapshot"):
        try:
            resp = requests.get(
                f"{BASE}/api/health-isf/drivers/{DRIVER_ID}/{name}",
                headers=headers,
                params={**params, "limit": 50} if name == "completion-snapshot" else params,
                timeout=90,
            )
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:400]
            row = {"status": resp.status_code}
            if resp.ok:
                if isinstance(body, list):
                    row["count"] = len(body)
                    row["ride_ids"] = [str(r.get("id") or r.get("ride_id") or "") for r in body[:10]]
                elif isinstance(body, dict):
                    ride = body.get("ride") or {}
                    row["has_active_ride"] = body.get("has_active_ride")
                    row["assignment_state"] = body.get("assignment_state")
                    row["ride_id"] = str(ride.get("id") or "")
                    row["lifecycle_state"] = str(ride.get("lifecycle_state") or ride.get("status") or "")
            else:
                row["error"] = body
            out[name] = row
        except Exception as exc:
            out[name] = {"status": "error", "error": str(exc)}
    return out


def main() -> int:
    report: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "driver_id": DRIVER_ID,
        "base": BASE,
        "organization_id": ORG,
    }
    live = requests.get(f"{BASE}/api/health/live", timeout=60).json()
    report["deploy_commit"] = live.get("deploy_commit")

    auth_pack = pa.resolve_production_tokens()
    report["operator_auth"] = {k: v for k, v in auth_pack.items() if k != "dispatcher_token" and k != "rider_token"}
    token = str(auth_pack.get("dispatcher_token") or "")
    if not auth_pack.get("ok") or not token:
        report["error"] = "operator_auth_failed"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        return 1

    auth = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    driver_resp = requests.get(
        f"{BASE}/api/health-isf/drivers/{DRIVER_ID}",
        headers=auth,
        params={"organization_id": ORG},
        timeout=90,
    )
    report["driver_record"] = {
        "status": driver_resp.status_code,
        "body": driver_resp.json() if driver_resp.ok else driver_resp.text[:400],
    }

    queue_resp = requests.get(
        f"{BASE}/api/health-isf/dispatch/queue",
        headers=auth,
        params={"organization_id": ORG, "limit": 100},
        timeout=90,
    )
    queue_rows = queue_resp.json() if queue_resp.ok else []
    report["dispatch_queue_count"] = len(queue_rows) if isinstance(queue_rows, list) else 0
    report["dispatch_queue_for_driver"] = [
        {
            "ride_id": str(r.get("ride_id") or r.get("id") or ""),
            "driver_id": str(r.get("driver_id") or ""),
            "assignment_state": r.get("assignment_state"),
            "lifecycle_state": r.get("lifecycle_state") or r.get("status"),
            "passenger_name": r.get("passenger_name"),
            "dispatch_eligible_at": r.get("dispatch_eligible_at"),
            "protected_reservation": r.get("protected_reservation"),
            "trip_leg": r.get("trip_leg"),
        }
        for r in (queue_rows if isinstance(queue_rows, list) else [])
        if str(r.get("driver_id") or "") == DRIVER_ID
    ]

    assign_resp = requests.get(
        f"{BASE}/api/health-isf/dispatch/active-assignments",
        headers=auth,
        params={"organization_id": ORG, "limit": 200},
        timeout=90,
    )
    assign_rows = assign_resp.json() if assign_resp.ok else []
    report["active_assignments_for_driver"] = [
        {
            "assignment_id": str(r.get("id") or ""),
            "ride_id": str(r.get("ride_id") or ""),
            "assignment_state": r.get("assignment_state") or r.get("state"),
            "updated_at": r.get("updated_at"),
        }
        for r in (assign_rows if isinstance(assign_rows, list) else [])
        if str(r.get("driver_id") or "") == DRIVER_ID
    ]

    req_resp = requests.get(
        f"{BASE}/api/health-isf/customer-requests",
        headers=auth,
        params={"organization_id": ORG, "limit": 20},
        timeout=90,
    )
    recent_requests = req_resp.json() if req_resp.ok else []
    report["recent_customer_requests"] = [
        {
            "request_id": str(r.get("id") or ""),
            "ride_id": str(r.get("ride_id") or ""),
            "driver_id": str(r.get("driver_id") or ""),
            "dispatch_status": r.get("dispatch_status"),
            "trip_type": r.get("trip_type"),
            "created_at": r.get("created_at"),
            "scheduling_summary": r.get("scheduling_summary"),
            "created_ride_count": r.get("created_ride_count"),
        }
        for r in (recent_requests if isinstance(recent_requests, list) else [])[:10]
    ]

    rides_resp = requests.get(
        f"{BASE}/api/health-isf/rides",
        headers=auth,
        params={"organization_id": ORG, "limit": 30},
        timeout=90,
    )
    rides = rides_resp.json() if rides_resp.ok else []
    report["recent_rides_for_driver"] = [
        {
            "ride_id": str(r.get("id") or ""),
            "driver_id": str(r.get("driver_id") or ""),
            "lifecycle_state": r.get("lifecycle_state") or r.get("status"),
            "passenger_name": r.get("passenger_name"),
            "dispatch_eligible_at": r.get("dispatch_eligible_at"),
            "protected_reservation": r.get("protected_reservation"),
            "trip_leg": r.get("trip_leg"),
            "round_trip_group_id": r.get("round_trip_group_id"),
            "requested_at": r.get("requested_at"),
        }
        for r in (rides if isinstance(rides, list) else [])
        if str(r.get("driver_id") or "") == DRIVER_ID
    ][:15]

    unassigned_recent = [
        {
            "ride_id": str(r.get("id") or ""),
            "lifecycle_state": r.get("lifecycle_state") or r.get("status"),
            "passenger_name": r.get("passenger_name"),
            "dispatch_eligible_at": r.get("dispatch_eligible_at"),
            "protected_reservation": r.get("protected_reservation"),
            "requested_at": r.get("requested_at"),
        }
        for r in (rides if isinstance(rides, list) else [])
        if not str(r.get("driver_id") or "")
    ][:10]
    report["recent_unassigned_rides"] = unassigned_recent

    driver_phone = ""
    if driver_resp.ok:
        body = driver_resp.json()
        driver_phone = str(body.get("phone") or body.get("phone_number") or "")

    mobile_login_attempts = []
    login_payloads = []
    if driver_phone:
        login_payloads.append({"phone": driver_phone})
    login_payloads.append({"phone": driver_phone or "000", "driver_id": DRIVER_ID})

    session_token = ""
    org_id = ORG
    for payload in login_payloads:
        if not payload.get("phone") and not payload.get("driver_id"):
            continue
        ml = requests.post(
            f"{BASE}/api/health-isf/drivers/mobile-login",
            json=payload,
            timeout=90,
        )
        row = {"payload_keys": list(payload.keys()), "status": ml.status_code}
        if ml.ok:
            body = ml.json()
            row["driver_id"] = body.get("driver_id")
            row["organization_id"] = body.get("organization_id")
            session_token = str(body.get("session_token") or "")
            org_id = str(body.get("organization_id") or ORG)
        else:
            row["error"] = ml.text[:300]
        mobile_login_attempts.append(row)
        if session_token:
            break

    report["mobile_login_attempts"] = mobile_login_attempts
    if session_token:
        report["driver_mobile_endpoints"] = probe_driver_endpoints(session_token, org_id)
        core = report["driver_mobile_endpoints"]
        report["driver_mobile_api_healthy"] = any(
            core.get(name, {}).get("status") == 200
            for name in ("active-ride", "live-workspace", "active-offer", "assigned-rides")
        )
    else:
        report["driver_mobile_endpoints"] = None
        report["driver_mobile_api_healthy"] = False

    report["diagnosis"] = {
        "driver_exists": driver_resp.ok,
        "has_active_assignment_records": bool(report["active_assignments_for_driver"]),
        "has_queue_rows_for_driver": bool(report["dispatch_queue_for_driver"]),
        "has_recent_rides_bound_to_driver": bool(report["recent_rides_for_driver"]),
        "unassigned_recent_rides_exist": bool(unassigned_recent),
        "mobile_login_ok": bool(session_token),
        "mobile_sync_apis_respond": report.get("driver_mobile_api_healthy"),
        "likely_causes": [],
    }
    causes = report["diagnosis"]["likely_causes"]
    if not session_token:
        causes.append("driver_mobile_login_failed_session_unusable")
    elif not report.get("driver_mobile_api_healthy"):
        causes.append("all_driver_mobile_sync_endpoints_failed_causing_ui_sync_warning")
    elif not report["active_assignments_for_driver"] and not report["recent_rides_for_driver"]:
        if unassigned_recent:
            causes.append("ride_created_but_not_assigned_to_this_driver_yet")
        else:
            causes.append("no_open_rides_in_system_for_any_driver")
    if any(str(r.get("protected_reservation")) in ("true", "True", "1") or r.get("dispatch_eligible_at") for r in unassigned_recent):
        causes.append("scheduled_rides_may_be_dispatch_protected_until_eligible_window")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print("REPORT_PATH", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
