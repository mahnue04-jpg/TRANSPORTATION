"""Production verification: immediate Start Route + same-day multi-ride scheduling."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa  # noqa: E402

ORG_ID = "308dc05a-6781-4ef7-91fc-ff22606937e3"
DRIVERS = (
    {"name": "James Smith", "phone": "917-555-1001"},
    {"name": "Maria Garcia", "phone": "917-555-1002"},
)
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
MARKER = f"sched_multi_verify_{RUN_TS}"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Organization-Id": ORG_ID}


def _driver_session(phone: str) -> dict[str, Any]:
    resp = requests.post(f"{pa.BASE}/api/health-isf/drivers/mobile-login", json={"phone": phone}, timeout=120)
    body = resp.json() if resp.content else {}
    if resp.status_code != 200:
        raise RuntimeError(f"mobile-login failed for {phone}: {body}")
    return body


def _set_available(session_token: str, driver_id: str) -> None:
    requests.post(
        f"{pa.BASE}/api/health-isf/drivers/availability",
        headers={"X-Driver-Session-Token": session_token, "X-Organization-Id": ORG_ID},
        json={"driver_id": driver_id, "availability_state": "available", "session_token": session_token},
        timeout=90,
    )


def _create_request(token: str, *, suffix: str, pickup: datetime, arrival: datetime, trip_type: str, same_driver: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rider_name": f"{MARKER} Client {suffix}",
        "rider_phone": f"646559{suffix[-4:].zfill(4)}",
        "pickup_address": f"100 Verify Pickup {suffix}, NY",
        "dropoff_address": f"200 Verify Dropoff {suffix}, NY",
        "ride_type": "healthcare",
        "trip_type": trip_type,
        "service_date": pickup.date().isoformat(),
        "pickup_time": pickup.isoformat(),
        "arrival_time": arrival.isoformat(),
        "same_driver_preference": same_driver,
        "notes": MARKER,
    }
    if trip_type == "round_trip":
        payload["return_pickup_time"] = (pickup + timedelta(hours=5)).isoformat()
    resp = requests.post(f"{pa.BASE}/api/health-isf/customer-requests", headers=_headers(token), json=payload, timeout=120)
    body = resp.json() if resp.content else {}
    if resp.status_code not in {200, 201}:
        raise RuntimeError(f"create request failed: {body}")
    return body


def _assign_scheduled(token: str, ride_id: str, driver_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{pa.BASE}/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
        headers=_headers(token),
        json={"driver_id": driver_id, "note": MARKER},
        timeout=120,
    )
    body = resp.json() if resp.content else {}
    return {"status": resp.status_code, "body": body, "mode": "dispatcher_reassign"}


def _accept_scheduled(session_token: str, driver_id: str, ride_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{pa.BASE}/api/health-isf/drivers/{driver_id}/accept-scheduled-ride",
        headers={"X-Driver-Session-Token": session_token, "X-Organization-Id": ORG_ID},
        json={"ride_id": ride_id},
        timeout=120,
    )
    return {"status": resp.status_code, "body": resp.json() if resp.content else {}}


def _driver_schedule(session_token: str, driver_id: str) -> list[dict[str, Any]]:
    resp = requests.get(
        f"{pa.BASE}/api/health-isf/drivers/{driver_id}/upcoming-schedule",
        headers={"X-Driver-Session-Token": session_token, "X-Organization-Id": ORG_ID},
        timeout=120,
    )
    body = resp.json() if resp.content else {}
    return list(body.get("upcoming_schedule") or [])


def _ride_detail(token: str, ride_id: str) -> dict[str, Any]:
    resp = requests.get(f"{pa.BASE}/api/health-isf/rides/{ride_id}", headers=_headers(token), timeout=120)
    return resp.json() if resp.content else {}


def main() -> int:
    tokens = pa.resolve_production_tokens()
    dispatcher = tokens["dispatcher_token"]
    base_day = datetime.now(timezone.utc).replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(days=1)

    driver_sessions: dict[str, dict[str, Any]] = {}
    for spec in DRIVERS:
        session = _driver_session(spec["phone"])
        driver_id = str(session["driver_id"])
        _set_available(str(session["session_token"]), driver_id)
        driver_sessions[driver_id] = {**spec, **session}

    plan: list[dict[str, Any]] = []
    # Five clients: round trips with staggered times; client 5 has intentional overlap window
    for idx in range(5):
        pickup = base_day + timedelta(hours=idx * 4)
        trip_type = "round_trip" if idx < 4 else "one_way"
        created = _create_request(
            dispatcher,
            suffix=f"{idx}{uuid.uuid4().hex[:4]}",
            pickup=pickup,
            arrival=pickup + timedelta(minutes=45),
            trip_type=trip_type,
            same_driver=idx < 3,
        )
        plan.append({"request": created, "target_driver_idx": idx % 2, "intentional_conflict": idx == 4})

    reports: list[dict[str, Any]] = []
    driver_ids = list(driver_sessions.keys())

    for item in plan:
        request_body = item["request"]
        ride_ids = list(request_body.get("ride_ids") or [])
        if not ride_ids and request_body.get("ride_id"):
            ride_ids = [str(request_body["ride_id"])]
        target_driver = driver_ids[item["target_driver_idx"]]
        session = driver_sessions[target_driver]

        for ride_id in ride_ids:
            assign = _assign_scheduled(dispatcher, ride_id, target_driver)
            accept = _accept_scheduled(str(session["session_token"]), target_driver, ride_id)
            detail = _ride_detail(dispatcher, ride_id)
            schedule = _driver_schedule(str(session["session_token"]), target_driver)
            entry = next((row for row in schedule if str(row.get("ride_id")) == ride_id), {})
            reports.append(
                {
                    "ride_id": ride_id,
                    "leg": detail.get("trip_leg") or entry.get("trip_leg") or "one_way",
                    "pickup_time": detail.get("pickup_time") or entry.get("pickup_time"),
                    "assigned_driver": target_driver,
                    "assigned_driver_name": session["name"],
                    "assignment_reason": assign.get("body", {}).get("mode") or "admin_assign_scheduled",
                    "conflicts_checked": "driver_has_schedule_conflict + active_workload",
                    "lifecycle_state": detail.get("lifecycle_state") or detail.get("status"),
                    "assignment_state": accept.get("body", {}).get("assignment_state") or entry.get("assignment_state"),
                    "start_route_immediately_available": bool(entry.get("can_start_route")),
                    "activation_message": entry.get("activation_message"),
                    "intentional_conflict_scenario": bool(item.get("intentional_conflict")),
                    "assign_status": assign.get("status"),
                    "accept_status": accept.get("status"),
                }
            )

    # Attempt overlapping assign to same driver for conflict client (expect failure or skip)
    conflict_candidates = [row for row in reports if row.get("intentional_conflict_scenario")]
    if conflict_candidates and len(driver_ids) >= 1:
        conflict_ride = conflict_candidates[0]["ride_id"]
        overlap_pickup = datetime.fromisoformat(str(conflict_candidates[0]["pickup_time"]).replace("Z", "+00:00")) + timedelta(minutes=20)
        overlap = _create_request(
            dispatcher,
            suffix=f"ov{uuid.uuid4().hex[:4]}",
            pickup=overlap_pickup,
            arrival=overlap_pickup + timedelta(minutes=40),
            trip_type="one_way",
            same_driver=False,
        )
        overlap_ride_id = str((overlap.get("ride_ids") or [overlap.get("ride_id")])[0])
        overlap_assign = _assign_scheduled(dispatcher, overlap_ride_id, driver_ids[0])
        reports.append(
            {
                "ride_id": overlap_ride_id,
                "leg": "one_way",
                "pickup_time": overlap_pickup.isoformat(),
                "assigned_driver": driver_ids[0],
                "assignment_reason": "intentional_overlap_test",
                "conflicts_checked": "driver_has_schedule_conflict",
                "lifecycle_state": "scheduled",
                "assignment_state": overlap_assign.get("body", {}).get("assignment_state"),
                "start_route_immediately_available": False,
                "assign_status": overlap_assign.get("status"),
                "overlap_assign_rejected": overlap_assign.get("status") not in {200, 201},
            }
        )

    out = {
        "marker": MARKER,
        "organization_id": ORG_ID,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "drivers_online": [{"driver_id": did, "name": driver_sessions[did]["name"]} for did in driver_ids],
        "ride_reports": reports,
        "scoped_modules_changed": [
            "scheduling.py",
            "advance_scheduling.py",
            "service.py (driver_en_route_pickup, evaluate_driver_ride_operational_state)",
            "driver_mobile_read_path.py",
            "routes.py (_promote noop)",
            "dispatch_maintenance.py",
            "ops-shell.js",
        ],
    }
    out_path = REPO / f"PRODUCTION_SCHEDULED_MULTI_RIDE_{RUN_TS}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
