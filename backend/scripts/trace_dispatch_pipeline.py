"""Trace dispatch pipeline immediately after customer-request ride creation."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFCustomerRideRequest,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
)


def main() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    rider_auth = client.post(
        "/api/auth/login",
        json={"email": "rider@amicor.local", "password": SEED_PASSWORD},
    )
    rider_auth.raise_for_status()
    rider_token = rider_auth.json()["access_token"]
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    org_id = rider_auth.json().get("organization_id")

    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        james = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == org_id,
                HealthISFDriver.name.ilike("James Smith"),
            )
            .first()
        )
        if james:
            now_ts = hs.now()
            james.status = DriverStatus.AVAILABLE
            james.availability_state = "available"
            james.is_active = True
            james.is_online = True
            james.auth_state = "active"
            james.last_seen_at = now_ts
            james.updated_at = now_ts
            db.commit()
            print(f"James ready: {james.id} status={james.status}")

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Trace {suffix}",
            "rider_phone": f"+1 646-555-{phone_digits}",
            "pickup_address": f"100 Pickup {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Dropoff {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    print(f"1. CREATE customer-request: {create.status_code}")
    if create.status_code != 201:
        print(f"   ERROR: {create.text}")
        return
    create.raise_for_status()
    row = create.json()
    ride_id = row["ride_id"]
    req_id = row["id"]
    print(f"   request_id={req_id} ride_id={ride_id} dispatch_status={row.get('dispatch_status')}")

    dispatcher_auth = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    dispatcher_auth.raise_for_status()
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth.json()['access_token']}"}

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assert ride is not None
        print(f"2. RIDE DB: status={ride.status} lifecycle={ride.lifecycle_state} driver_id={ride.driver_id}")
        assigns = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .all()
        )
        print(f"3. ASSIGNMENTS: {[(a.assignment_state, a.driver_id) for a in assigns]}")
        req = db.query(HealthISFCustomerRideRequest).filter(HealthISFCustomerRideRequest.id == req_id).first()
        print(f"4. CUSTOMER REQUEST: dispatch_status={req.dispatch_status if req else None}")

    if assigns and assigns[0][0] == "offered" and ride.driver_id:
        print("PIPELINE OK: driver offer issued at intake without manual dispatch steps")
        if james:
            offer = client.get(
                f"/api/health-isf/drivers/{james.id}/active-offer",
                headers=dispatcher_headers,
            )
            print(f"DRIVER OFFER: {offer.status_code} {offer.text[:300]}")
        return

    queue = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers)
    print(f"5. DISPATCH QUEUE: {queue.status_code} count={len(queue.json())}")
    match = next((item for item in queue.json() if item.get("ride_id") == ride_id), None)
    print(f"   ride in queue: {match is not None}")
    if match:
        print(f"   queue row: assignment_state={match.get('assignment_state')} ride_status={match.get('ride_status')}")

    metrics = client.get("/api/health-isf/customer-requests/metrics", headers=dispatcher_headers)
    print(f"6. METRICS: {metrics.json()}")

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{req_id}/approve",
        headers=dispatcher_headers,
    )
    print(f"7. APPROVE: {approve.status_code}")

    auto = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{req_id}/auto-dispatch",
        headers=dispatcher_headers,
        json={"offer_timeout_seconds": 120},
    )
    print(f"8. AUTO-DISPATCH: {auto.status_code} {auto.text[:300]}")

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assigns = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .all()
        )
        print(f"9. POST-DISPATCH RIDE: status={ride.status} lifecycle={ride.lifecycle_state} driver_id={ride.driver_id}")
        print(f"10. POST-DISPATCH ASSIGNMENTS: {[(a.assignment_state, a.driver_id) for a in assigns]}")

    if james:
        offer = client.get(
            f"/api/health-isf/drivers/{james.id}/active-offer",
            headers=dispatcher_headers,
        )
        print(f"11. DRIVER OFFER: {offer.status_code} {offer.text[:300]}")


if __name__ == "__main__":
    main()
