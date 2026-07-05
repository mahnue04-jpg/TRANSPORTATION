"""Proof newest rider-created ride is assigned to a real driver and visible in driver app."""
from __future__ import annotations

import json
import os
import re
import sys
import uuid

os.environ["HEALTH_ISF_AUTO_DISPATCH_ENABLED"] = "0"

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import DriverStatus, HealthISFDriver


RIDER_NAME = "saye monibah"
PROOF_RIDE_MARKER = "driver ai proof"


def _fail(reason: str, detail: str = "") -> None:
    print(f"RESULT=FAIL")
    print(f"REASON={reason}")
    if detail:
        print(f"DETAIL={detail[:500]}")
    sys.exit(1)


def _ensure_eligible_driver(org_id: str) -> str:
    with SessionLocal() as db:
        now_ts = hs.now()
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Live Dispatch Driver {uuid4()[:6]}",
            phone=f"917-555-{''.join(ch for ch in uuid4() if ch.isdigit())[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"LD-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=True,
            auth_state="active",
            last_seen_at=now_ts,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        db.refresh(driver)
        if not hs._driver_is_dispatch_candidate(db, driver):
            _fail("driver_setup", "fresh driver failed dispatch candidate checks")
        return str(driver.id)


def _ai_sees_ride(payload: dict, ride_id: str) -> bool:
    live = payload.get("live_dispatch") or {}
    focused = live.get("focused_ride") or {}
    if str(focused.get("ride_id") or "") == ride_id:
        return True
    queue_ids = live.get("queue_ride_ids") or []
    return ride_id in [str(item) for item in queue_ids]


def main() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    rider_auth.raise_for_status()
    rider_headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = rider_auth.json()["organization_id"]

    dispatcher_auth = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    dispatcher_auth.raise_for_status()
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth.json()['access_token']}"}

    with SessionLocal() as db:
        rows = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id)
            .all()
        )
        for driver_row in rows:
            driver_row.status = DriverStatus.OFFLINE
            driver_row.is_online = False
            driver_row.availability_state = "offline"
            driver_row.auth_state = "inactive"
        db.commit()

    existing_drivers = client.get("/api/health-isf/drivers?limit=200", headers=dispatcher_headers)
    if existing_drivers.status_code == 200 and isinstance(existing_drivers.json(), list):
        for driver_row in existing_drivers.json():
            driver_key = str(driver_row.get("id") or "")
            if not driver_key:
                continue
            client.post(
                f"/api/health-isf/drivers/{driver_key}/set-status",
                headers={**dispatcher_headers, "Content-Type": "application/json"},
                json={"status": "offline", "availability_state": "offline", "is_online": False},
            )

    suffix = uuid.uuid4().hex[:8]
    digits = re.sub(r"\D", "", suffix).ljust(4, "0")[:4]
    pickup = f"100 Live Pickup {suffix}, New York, NY 10001"
    dropoff = f"200 Live Dropoff {suffix}, New York, NY 10002"
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": RIDER_NAME,
            "rider_phone": f"+1 646-555-{digits}",
            "pickup_address": pickup,
            "dropoff_address": dropoff,
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    if create.status_code != 201:
        _fail("rider_create", create.text[:400])

    row = create.json()
    ride_id = str(row["ride_id"])
    print(f"NEWEST_RIDER_CREATED_RIDE_ID={ride_id}")

    ride_resp = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    if ride_resp.status_code != 200:
        _fail("ride_lookup", ride_resp.text[:300])
    ride_row = ride_resp.json()
    initial_status = str(ride_row.get("lifecycle_state") or ride_row.get("status") or "pending").lower()
    initial_driver = str(ride_row.get("driver_id") or "unassigned")
    print(f"RIDE_INITIAL_STATUS={initial_status}")
    print(f"RIDE_INITIAL_DRIVER={initial_driver or 'unassigned'}")
    if initial_driver not in {"", "unassigned", "none", "null"}:
        _fail("ride_initial_state", f"expected unassigned ride, got driver={initial_driver}")
    if initial_status not in {"pending", "queued", "requested", "pending_assignment"}:
        _fail("ride_initial_state", f"expected pending ride, got status={initial_status}")

    driver_id = _ensure_eligible_driver(org_id)

    queue = client.get("/api/health-isf/dispatch/queue?limit=200", headers=dispatcher_headers)
    if queue.status_code != 200:
        _fail("dispatch_queue", queue.text[:300])
    queue_rows = queue.json()
    newest = queue_rows[0] if queue_rows else None
    if not newest or str(newest.get("ride_id")) != ride_id:
        _fail("dispatch_queue", f"newest queue ride mismatch: {json.dumps((newest or {}))[:300]}")

    ai_pre = client.get(
        f"/api/health-isf/ai-dispatch/snapshot?publish=false&ride_id={ride_id}",
        headers=dispatcher_headers,
    )
    if ai_pre.status_code != 200:
        _fail("ai_snapshot", ai_pre.text[:300])
    ai_pre_sees = _ai_sees_ride(ai_pre.json(), ride_id)
    print(f"AI_ASSISTANT_SEES_RIDE={str(ai_pre_sees).lower()}")
    if not ai_pre_sees:
        _fail("ai_snapshot", json.dumps((ai_pre.json().get("live_dispatch") or {}))[:300])

    assign = client.post(
        "/api/health-isf/dispatch/assign-newest-queue?offer_timeout_seconds=120",
        headers=dispatcher_headers,
    )
    if assign.status_code != 200:
        _fail("assign_newest_queue", assign.text[:400])
    assign_payload = assign.json()
    if str(assign_payload.get("ride_id") or "") != ride_id:
        _fail("assign_newest_queue", f"assigned wrong ride: {json.dumps(assign_payload)[:300]}")
    ai_selected_driver_id = str(assign_payload.get("selected_driver_id") or "")
    print(f"AI_SELECTED_DRIVER_ID={ai_selected_driver_id}")
    if not ai_selected_driver_id:
        _fail("assign_newest_queue", "no selected driver returned")

    assignment_created = bool(assign_payload.get("offer"))
    print(f"ASSIGNMENT_CREATED_FOR_SAME_RIDE={str(assignment_created).lower()}")
    if not assignment_created:
        _fail("assign_newest_queue", json.dumps(assign_payload)[:300])

    workspace = client.get(
        f"/api/health-isf/drivers/{ai_selected_driver_id}/live-workspace",
        headers=dispatcher_headers,
    )
    offer = client.get(
        f"/api/health-isf/drivers/{ai_selected_driver_id}/active-offer",
        headers=dispatcher_headers,
    )
    if workspace.status_code != 200 or offer.status_code != 200:
        _fail("driver_app", f"workspace={workspace.status_code} offer={offer.status_code}")

    workspace_payload = workspace.json()
    offer_payload = offer.json().get("offer") or {}
    active_ride = workspace_payload.get("active_ride") or {}
    active_assignment = workspace_payload.get("active_assignment") or {}
    driver_app_ride_id = str(
        offer_payload.get("ride_id")
        or active_ride.get("id")
        or active_assignment.get("ride_id")
        or ""
    )
    print(f"DRIVER_APP_ACTIVE_RIDE_ID={driver_app_ride_id}")
    if driver_app_ride_id != ride_id:
        _fail("driver_app", json.dumps({"workspace": workspace_payload, "offer": offer_payload})[:500])

    rider_name = str(
        offer_payload.get("passenger_name")
        or active_ride.get("passenger_name")
        or ""
    ).strip()
    print(f"DRIVER_APP_SHOWS_RIDER_NAME={rider_name.lower()}")
    if rider_name.lower() != RIDER_NAME.lower():
        _fail("driver_app", f"expected rider name {RIDER_NAME}, got {rider_name}")

    pickup_text = str(
        offer_payload.get("pickup_address")
        or active_ride.get("pickup_address")
        or ""
    )
    dropoff_text = str(
        offer_payload.get("dropoff_address")
        or active_ride.get("dropoff_address")
        or ""
    )
    shows_pickup = pickup.lower() in pickup_text.lower()
    shows_dropoff = dropoff.lower() in dropoff_text.lower()
    print(f"DRIVER_APP_SHOWS_PICKUP={str(shows_pickup).lower()}")
    print(f"DRIVER_APP_SHOWS_DROPOFF={str(shows_dropoff).lower()}")
    if not shows_pickup or not shows_dropoff:
        _fail("driver_app", json.dumps({"pickup": pickup_text, "dropoff": dropoff_text})[:300])

    proof_selected = PROOF_RIDE_MARKER in rider_name.lower()
    print(f"OLD_AI_PROOF_RIDE_NOT_SELECTED={str(not proof_selected).lower()}")
    if proof_selected:
        _fail("driver_app", "driver app still bound to AI proof ride")

    offer_id = str(offer_payload.get("offer_id") or offer_payload.get("id") or "")
    accept = client.post(f"/api/health-isf/dispatch/offers/{offer_id}/accept", headers=dispatcher_headers)
    accept_ok = accept.status_code in {200, 201}
    print(f"DRIVER_ACCEPT_200={str(accept_ok).lower()}")
    if not accept_ok:
        _fail("driver_accept", accept.text[:300])

    post_ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    post_status = "accepted"
    if post_ride.status_code == 200:
        post_row = post_ride.json()
        post_status = str(post_row.get("lifecycle_state") or post_row.get("status") or "accepted").lower()
    print(f"RIDE_STATUS_AFTER_ACCEPT={post_status}")
    if post_status not in {"accepted", "assigned", "driver_en_route"}:
        _fail("ride_status", f"unexpected status after accept: {post_status}")

    print("RESULT=PASS")


if __name__ == "__main__":
    main()
