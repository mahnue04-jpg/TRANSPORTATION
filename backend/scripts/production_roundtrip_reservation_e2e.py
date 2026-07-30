#!/usr/bin/env python3
"""Production E2E: brand-new round trip, outbound complete, automatic return reservation."""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa  # noqa: E402
from scripts.production_back_to_back_and_schedule_validation import (  # noqa: E402
    complete_lifecycle,
    dispatcher_get,
    dispatcher_headers,
    driver_get,
    fetch_ride,
    manual_assign,
    mobile_login,
    prep_driver_sessions,
    resolve_four_drivers,
    set_driver_available,
    unwrap,
    verify_billing,
)

BASE = pa.BASE
ORG = "308dc05a-6781-4ef7-91fc-ff22606937e3"
DRIVER_PHONE = "917-555-1004"
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
OUT = REPO / "PRODUCTION_QA_EVIDENCE" / f"PRODUCTION_ROUNDTRIP_RESERVATION_E2E_{RUN_TS}.json"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def find_return_leg(token: str, group_id: str) -> str:
    for path in (
        f"/api/health-isf/rides/round-trip/{group_id}",
        f"/api/health-isf/rides?limit=50&search={group_id[:8]}",
    ):
        resp = dispatcher_get(token, path, ORG)
        if resp["status"] != 200:
            continue
        body = unwrap(resp["body"]) or {}
        legs = body.get("legs") or body.get("rides") or (body if isinstance(body, list) else [])
        for leg in legs:
            if str(leg.get("trip_leg") or "").lower() == "return":
                return str(leg.get("ride_id") or leg.get("id") or "")
    return ""


def create_round_trip(rider_token: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    outbound_pickup = now + timedelta(minutes=8)
    outbound_arrival = now + timedelta(minutes=23)
    return_pickup = now + timedelta(minutes=83)
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "rider_name": f"RT Reservation E2E {RUN_TS}",
        "rider_phone": f"646-558-{str(int(suffix[:4], 16) % 10000).zfill(4)}",
        "pickup_address": f"510 RT Reservation Pickup {suffix}, Minneapolis, MN",
        "dropoff_address": f"520 RT Reservation Clinic {suffix}, Minneapolis, MN",
        "return_pickup_address": f"520 RT Reservation Clinic {suffix}, Minneapolis, MN",
        "return_dropoff_address": f"510 RT Reservation Pickup {suffix}, Minneapolis, MN",
        "ride_type": "healthcare",
        "trip_type": "round_trip",
        "return_pickup_type": "scheduled_time",
        "return_pickup_time": iso(return_pickup),
        "same_driver_preference": True,
        "recurring": False,
        "recurrence": "none",
        "service_date": outbound_pickup.date().isoformat(),
        "pickup_time": iso(outbound_pickup),
        "arrival_time": iso(outbound_arrival),
        "client_timezone": "America/Chicago",
    }
    resp = requests.post(
        f"{BASE}/api/health-isf/customer-requests",
        headers=dispatcher_headers(rider_token),
        json=payload,
        timeout=120,
    )
    body = unwrap(resp.json()) if resp.content else {}
    outbound_id = str(body.get("ride_id") or "")
    group_id = str(body.get("round_trip_group_id") or "")
    request_id = str(body.get("id") or "")
    linked = body.get("linked_ride_ids") or []
    return_id = ""
    if isinstance(linked, list):
        for rid in linked:
            snap = fetch_ride(rider_token, str(rid), ORG)
            if str(snap.get("trip_leg") or "") == "return":
                return_id = str(rid)
    if not return_id and group_id:
        return_id = find_return_leg(rider_token, group_id)
    if not group_id and outbound_id:
        group_id = str(fetch_ride(rider_token, outbound_id, ORG).get("round_trip_group_id") or "")
    return {
        "ok": resp.status_code in {200, 201} and bool(outbound_id) and bool(return_id),
        "status": resp.status_code,
        "request_id": request_id,
        "outbound_ride_id": outbound_id,
        "return_ride_id": return_id,
        "round_trip_group_id": group_id,
        "planned_return_pickup": payload["return_pickup_time"],
        "planned_return_dispatch_window": iso(return_pickup - timedelta(minutes=60)),
    }


def surface_snapshot(
    dispatcher_token: str,
    driver: dict[str, Any],
    outbound_id: str,
    return_id: str,
    *,
    queue_read_only: bool = True,
) -> dict[str, Any]:
    queue_path = f"/api/health-isf/dispatch/queue?organization_id={ORG}&limit=100&read_only={'true' if queue_read_only else 'false'}"
    queue = dispatcher_get(dispatcher_token, queue_path, ORG, timeout=120)
    active = dispatcher_get(
        dispatcher_token,
        f"/api/health-isf/dispatch/active-assignments?organization_id={ORG}",
        ORG,
        timeout=120,
    )
    outbound = fetch_ride(dispatcher_token, outbound_id, ORG)
    return_leg = fetch_ride(dispatcher_token, return_id, ORG)
    upcoming = driver_get(
        driver["session_token"],
        f"/api/health-isf/drivers/{driver['id']}/upcoming-schedule",
        ORG,
        timeout=120,
    )
    live = driver_get(
        driver["session_token"],
        f"/api/health-isf/drivers/{driver['id']}/active-ride",
        ORG,
        timeout=120,
    )
    rider_search = dispatcher_get(
        dispatcher_token,
        f"/api/health-isf/rides?limit=30&search={return_id[:8]}",
        ORG,
        timeout=120,
    )
    ai = dispatcher_get(
        dispatcher_token,
        f"/api/health-isf/ai/dispatch/context?ride_id={return_id}",
        ORG,
        timeout=120,
    )
    queue_items = unwrap(queue.get("body") or []) or []
    queue_match = next((row for row in queue_items if str(row.get("ride_id")) == return_id), None)
    active_items = unwrap(active.get("body") or []) or []
    active_match = next((row for row in active_items if str(row.get("ride_id")) == return_id), None)
    upcoming_body = unwrap(upcoming.get("body") or {}) or {}
    upcoming_rows = upcoming_body.get("upcoming_schedule") or []
    upcoming_match = next((row for row in upcoming_rows if str(row.get("ride_id")) == return_id), None)
    live_body = unwrap(live.get("body") or {}) or {}
    rider_rows = unwrap(rider_search.get("body") or []) or []
    rider_match = next((row for row in rider_rows if str(row.get("id")) == return_id), None)
    return {
        "queue_status": queue.get("status"),
        "queue_read_only": queue_read_only,
        "return_in_queue": queue_match,
        "active_assignments_status": active.get("status"),
        "return_active_assignment": active_match,
        "outbound": {
            "id": outbound.get("id"),
            "lifecycle_state": outbound.get("lifecycle_state"),
            "driver_id": outbound.get("driver_id"),
            "financial_record_id": outbound.get("financial_record_id"),
        },
        "return_leg": {
            "id": return_leg.get("id"),
            "lifecycle_state": return_leg.get("lifecycle_state"),
            "driver_id": return_leg.get("driver_id"),
            "dispatch_eligible_at": return_leg.get("dispatch_eligible_at"),
            "pickup_time": return_leg.get("pickup_time"),
        },
        "upcoming_schedule_status": upcoming.get("status"),
        "return_in_upcoming_schedule": upcoming_match,
        "driver_live": {
            "has_active_ride": live_body.get("has_active_ride"),
            "active_ride_id": (live_body.get("active_ride") or live_body.get("ride") or {}).get("ride_id")
            or (live_body.get("active_ride") or live_body.get("ride") or {}).get("id"),
            "upcoming_count": len(live_body.get("upcoming_schedule") or []),
        },
        "rider_search_match_id": rider_match.get("id") if rider_match else None,
        "ai_context_status": ai.get("status"),
        "ai_context_ride_id": (unwrap(ai.get("body") or {}) or {}).get("ride_id"),
    }


def wait_until(ts_iso: str, *, buffer_seconds: int = 5) -> None:
    target = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    while datetime.now(timezone.utc) < target + timedelta(seconds=buffer_seconds):
        remaining = (target - datetime.now(timezone.utc)).total_seconds()
        sleep_for = min(30, max(5, remaining))
        print(f"waiting {int(sleep_for)}s for dispatch window ({ts_iso})")
        time.sleep(sleep_for)


def main() -> int:
    report: dict[str, Any] = {"run_ts": RUN_TS, "verdict": "FAIL", "steps": {}}

    auth = pa.resolve_production_tokens()
    if not auth.get("ok"):
        report["failed_step"] = "auth"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    dispatcher_token = auth["dispatcher_token"]
    rider_token = auth["rider_token"]

    queue_probe = dispatcher_get(
        dispatcher_token,
        f"/api/health-isf/dispatch/queue?organization_id={ORG}&read_only=true",
        ORG,
        timeout=120,
    )
    report["steps"]["dispatch_queue_read_only"] = {
        "ok": queue_probe.get("status") == 200,
        "status": queue_probe.get("status"),
    }
    if queue_probe.get("status") != 200:
        report["failed_step"] = "dispatch_queue_read_only"
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    drivers = resolve_four_drivers(dispatcher_token)
    driver = next((d for d in drivers if d["phone"] == DRIVER_PHONE), None)
    if not driver:
        report["failed_step"] = "driver_lookup"
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return 1

    prep_ok, prep_rows, org_id, _ = prep_driver_sessions([driver], dispatcher_token, resolve_stale_blockers=True)
    driver = prep_rows[0] if prep_rows else driver
    driver["organization_id"] = org_id or ORG
    login = mobile_login(driver["phone"])
    driver["session_token"] = str((login.get("body") or {}).get("session_token") or "")
    set_driver_available(driver["session_token"], driver["id"], driver["organization_id"])
    report["steps"]["driver_prep"] = {"ok": bool(driver.get("session_token")), "driver_id": driver["id"]}

    created = create_round_trip(rider_token)
    report["steps"]["create_round_trip"] = created
    if not created.get("ok"):
        report["failed_step"] = "create_round_trip"
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    approve = requests.post(
        f"{BASE}/api/health-isf/dispatcher/customer-requests/{created['request_id']}/approve",
        headers=dispatcher_headers(dispatcher_token),
        timeout=120,
    )
    assign = manual_assign(dispatcher_token, created["request_id"], driver["id"])
    report["steps"]["dispatch_outbound"] = {
        "ok": approve.status_code == 200 and assign.get("ok"),
        "approve_status": approve.status_code,
        "assign_status": assign.get("status"),
    }

    assignment = {
        "session_token": driver["session_token"],
        "assigned_driver_id": driver["id"],
        "organization_id": driver["organization_id"],
    }
    outbound_ok, outbound_err, outbound_steps = complete_lifecycle(assignment, created["outbound_ride_id"])
    report["steps"]["outbound_complete"] = {
        "ok": outbound_ok,
        "error": outbound_err,
        "steps": outbound_steps,
    }
    if not outbound_ok:
        report["failed_step"] = "outbound_complete"
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    time.sleep(3)
    pre_window = surface_snapshot(
        dispatcher_token,
        driver,
        created["outbound_ride_id"],
        created["return_ride_id"],
        queue_read_only=True,
    )
    report["steps"]["pre_dispatch_window"] = pre_window
    report["steps"]["pre_dispatch_window"]["ok"] = (
        pre_window["queue_status"] == 200
        and pre_window["return_leg"]["driver_id"] == driver["id"]
        and pre_window["return_in_upcoming_schedule"] is not None
        and pre_window["return_active_assignment"] is None
        and not pre_window["driver_live"]["has_active_ride"]
    )

    outbound_billing = verify_billing(
        dispatcher_token, created["outbound_ride_id"], driver["id"], driver["organization_id"]
    )
    report["steps"]["outbound_billing"] = outbound_billing

    dispatch_window = str(pre_window["return_leg"].get("dispatch_eligible_at") or created["planned_return_dispatch_window"])
    wait_until(dispatch_window, buffer_seconds=8)

    queue_activate = dispatcher_get(
        dispatcher_token,
        f"/api/health-isf/dispatch/queue?organization_id={ORG}&read_only=false",
        ORG,
        timeout=120,
    )
    time.sleep(3)
    post_window = surface_snapshot(
        dispatcher_token,
        driver,
        created["outbound_ride_id"],
        created["return_ride_id"],
        queue_read_only=True,
    )
    report["steps"]["dispatch_window_open"] = {
        "queue_activate_status": queue_activate.get("status"),
        "snapshot": post_window,
    }
    report["steps"]["dispatch_window_open"]["ok"] = (
        queue_activate.get("status") == 200
        and post_window["return_active_assignment"] is not None
        and post_window["return_leg"]["driver_id"] == driver["id"]
        and post_window["return_in_upcoming_schedule"] is None
    )

    ids = {
        "outbound_id": created["outbound_ride_id"],
        "return_id": created["return_ride_id"],
        "round_trip_group_id": created["round_trip_group_id"],
    }
    report["ids"] = ids
    report["surface_sync_ok"] = (
        post_window["return_leg"]["id"] == created["return_ride_id"]
        and post_window["rider_search_match_id"] == created["return_ride_id"]
        and (post_window["return_active_assignment"] or {}).get("ride_id") == created["return_ride_id"]
    )

    checks = [
        report["steps"]["dispatch_queue_read_only"]["ok"],
        report["steps"]["create_round_trip"]["ok"],
        report["steps"]["outbound_complete"]["ok"],
        report["steps"]["pre_dispatch_window"]["ok"],
        outbound_billing.get("pass"),
        report["steps"]["dispatch_window_open"]["ok"],
        report["surface_sync_ok"],
    ]
    report["verdict"] = "PASS" if all(checks) else "FAIL"
    if report["verdict"] == "FAIL":
        for name, step in report["steps"].items():
            if isinstance(step, dict) and step.get("ok") is False:
                report["failed_step"] = name
                break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "out": str(OUT), "failed_step": report.get("failed_step")}, indent=2))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
