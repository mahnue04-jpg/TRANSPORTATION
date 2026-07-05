"""Verify dispatch dashboard visibility pipeline end-to-end."""
from __future__ import annotations

import re
import sys

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFRide

VALID_QUEUE_STATES = {
    "awaiting_approval",
    "pending_assignment",
    "offered",
    "assigned",
    "queued",
    "requested",
    "pending",
    "searching",
    "reassignment_pending",
    "dispatchable",
}


def sanitize_dispatch_state(raw: str) -> str:
    state = str(raw or "requested").strip().lower()
    if state.startswith("ridestatus."):
        state = state.split(".", 1)[1]
    return state


def simulate_ops_shell_ui_visible(queue_rows: list[dict], ride_id: str) -> tuple[bool, str, str]:
    """Mirror ops-shell.js renderLiveDispatchBoard queue filter + normalizeTrip."""
    normalized = []
    for item in queue_rows:
        trip_id = str(item.get("ride_id") or item.get("id") or "")
        state = sanitize_dispatch_state(
            item.get("assignment_state") or item.get("ride_status") or "requested"
        )
        normalized.append({"id": trip_id, "state": state})

    visible = [
        trip
        for trip in normalized
        if trip["state"] in VALID_QUEUE_STATES and trip["id"]
    ]
    match = next((trip for trip in visible if trip["id"] == ride_id), None)
    if match:
        return True, match["state"], "ops-shell queue table"
    return False, "", "ride filtered out or missing from normalized queue"


def simulate_health_isf_ui_visible(queue_rows: list[dict], ride_id: str) -> tuple[bool, str]:
    sorted_rows = sorted(
        queue_rows,
        key=lambda row: str(row.get("requested_at") or ""),
        reverse=True,
    )
    top_rows = sorted_rows[:25]
    match = next((row for row in top_rows if str(row.get("ride_id")) == ride_id), None)
    if match:
        return True, str(match.get("assignment_state") or "")
    return False, ""


def main() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    rider_auth.raise_for_status()
    rider_headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}

    dispatcher_auth = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    dispatcher_auth.raise_for_status()
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth.json()['access_token']}"}

    suffix = uuid4()[:8]
    digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Dispatch Vis {suffix}",
            "rider_phone": f"+1 646-555-{digits}",
            "pickup_address": f"100 Pickup {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Dropoff {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    if create.status_code != 201:
        print(f"RIDER_CREATED_RIDE_ID=NONE")
        print(f"RESULT=FAIL")
        print(f"reason=create_customer_request returned {create.status_code}: {create.text[:300]}")
        sys.exit(1)

    ride_id = str(create.json()["ride_id"])
    print(f"RIDER_CREATED_RIDE_ID={ride_id}")

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        if not ride:
            print("DISPATCH_QUEUE_CONTAINS=false")
            print("DISPATCH_UI_VISIBLE=false")
            print("STATUS=missing")
            print("RESULT=FAIL")
            print("reason=service.py DB persistence — ride row not found after create")
            sys.exit(1)
        if not ride.organization_id or not ride.passenger_name or not ride.pickup_address:
            print("RESULT=FAIL")
            print("reason=service.py create_ride — required dispatch fields missing on ride row")
            sys.exit(1)

    queue_resp = client.get("/api/health-isf/dispatch/queue?limit=200", headers=dispatcher_headers)
    if queue_resp.status_code != 200:
        print("DISPATCH_QUEUE_CONTAINS=false")
        print("DISPATCH_UI_VISIBLE=false")
        print(f"STATUS=unknown")
        print("RESULT=FAIL")
        print(f"reason=routes.py dispatch_queue — HTTP {queue_resp.status_code}: {queue_resp.text[:300]}")
        sys.exit(1)

    queue_rows = queue_resp.json()
    queue_match = next((row for row in queue_rows if str(row.get("ride_id")) == ride_id), None)
    print(f"DISPATCH_QUEUE_CONTAINS={str(queue_match is not None).lower()}")
    if not queue_match:
        print("DISPATCH_UI_VISIBLE=false")
        print("STATUS=missing")
        print("RESULT=FAIL")
        print(
            "reason=service.py get_dispatch_queue — new ride absent from /api/health-isf/dispatch/queue "
            f"(returned {len(queue_rows)} rows)"
        )
        sys.exit(1)

    status = str(queue_match.get("assignment_state") or "")
    print(f"STATUS={status}")

    ops_visible, ops_state, _ = simulate_ops_shell_ui_visible(queue_rows, ride_id)
    health_visible, health_state = simulate_health_isf_ui_visible(queue_rows, ride_id)
    ui_visible = ops_visible and health_visible
    print(f"DISPATCH_UI_VISIBLE={str(ui_visible).lower()}")

    if not ui_visible:
        print("RESULT=FAIL")
        if not ops_visible:
            print(
                "reason=ops-shell.js renderLiveDispatchBoard — ride filtered or hidden "
                f"(normalized_state={ops_state or 'none'})"
            )
        else:
            print(
                "reason=health-isf.js dispatchIntelQueue — ride not in top 25 sorted queue rows "
                f"(state={health_state or 'none'})"
            )
        sys.exit(1)

    if status not in VALID_QUEUE_STATES and status not in {"accepted"}:
        print("RESULT=FAIL")
        print(f"reason=service.py _resolve_dispatch_queue_assignment_state — unexpected status '{status}'")
        sys.exit(1)

    print("RESULT=PASS")


if __name__ == "__main__":
    main()
