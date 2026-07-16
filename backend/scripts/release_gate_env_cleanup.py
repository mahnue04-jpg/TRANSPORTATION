"""Terminal-close stale active rides/assignments before release-gate verification."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.auth import ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
    RideStatus,
)

ensure_auth_schema()
seed_default_users()

ORG = "ca8d0c7c-1fff-4465-99d7-75a1fc51543e"
TERMINAL = {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}
OPEN_ASSIGNMENT_STATES = set(hs.DRIVER_APP_ASSIGNMENT_STATES)


def main() -> None:
    counts: dict[str, int] = {
        "rides_closed": 0,
        "assignments_closed": 0,
        "drivers_released": 0,
    }
    with SessionLocal() as db:
        now_ts = hs.now()
        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == ORG)
            .all()
        )
        for ride in rides:
            lifecycle = str(ride.lifecycle_state or ride.status or "")
            if lifecycle in TERMINAL or hs._ride_is_terminal(ride):
                continue
            ride.status = RideStatus.CANCELLED.value
            ride.lifecycle_state = RideStatus.CANCELLED.value
            ride.updated_at = now_ts
            counts["rides_closed"] += 1
            closed = hs._close_active_assignments_for_ride(
                db,
                ride_id=str(ride.id),
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="release_gate_env_cleanup",
            )
            counts["assignments_closed"] += closed

        stale_assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.organization_id == ORG,
                HealthISFDispatchAssignment.assignment_state.in_(list(OPEN_ASSIGNMENT_STATES)),
            )
            .all()
        )
        for assignment in stale_assignments:
            hs._close_dispatch_assignment_record(
                db,
                assignment,
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="release_gate_env_cleanup",
            )
            counts["assignments_closed"] += 1

        drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == ORG).all()
        for driver in drivers:
            if hs._driver_active_workload_count(db, driver.id) > 0:
                continue
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_online = True
            driver.auth_state = "active"
            driver.last_seen_at = now_ts
            counts["drivers_released"] += 1
        db.commit()

        post = {
            "dispatch_queue_count": len(hs.get_dispatch_queue(db, organization_id=ORG, limit=500)),
            "active_assignments_count": len(
                hs.get_dispatch_active_assignments(db, organization_id=ORG, limit=500)
            ),
            "open_rides": [
                str(row.id)
                for row in db.query(HealthISFRide).filter(HealthISFRide.organization_id == ORG).all()
                if not hs._ride_is_terminal(row)
            ],
        }
    print(json.dumps({"counts": counts, "post_cleanup": post}, indent=2))


if __name__ == "__main__":
    main()
