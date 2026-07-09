"""Final pre-production seed/demo database cleanup.

Does NOT modify ride workflow, billing engine, or dispatch logic.
Only removes duplicate/demo/test seed records and restores a realistic seed set.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.session import SessionLocal
from app.db import models as _platform_models  # noqa: F401  — register platform_users metadata
from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    CustomerRequestStatus,
    DispatchAssignmentState,
    DriverStatus,
    HealthISFBillingHandoff,
    HealthISFClaim,
    HealthISFCustomerRideRequest,
    HealthISFDispatchAssignment,
    HealthISFDispatchLog,
    HealthISFDriver,
    HealthISFDriverApplication,
    HealthISFDriverLocationPing,
    HealthISFDriverSession,
    HealthISFOrganization,
    HealthISFPaymentTransaction,
    HealthISFPayout,
    HealthISFProvider,
    HealthISFRecurringRideSchedule,
    HealthISFRide,
    HealthISFRideExecutionAction,
    HealthISFRideRoutePlan,
    HealthISFRideStatusHistory,
    HealthISFSettlementLedger,
    HealthISFTrip,
    HealthISFTripDocument,
    HealthISFTripFinancialRecord,
    HealthISFVehicle,
    RideAssignmentLock,
    RealTimeEvent,
    RideStatus,
)
from app.modules.health_isf.service import (
    SAMPLE_DRIVERS,
    SAMPLE_PROVIDERS,
    _is_ai_proof_ride,
    _is_test_ride_row,
)

ORG_ID = os.getenv("AMICOR_SEED_ORG_ID", "ca8d0c7c-1fff-4465-99d7-75a1fc51543e")

KEEP_DRIVER_NAMES = {
    "James Smith",
    "Maria Garcia",
    "David Chen",
    "Aisha Patel",
    "Carlos Rivera",
    "Emily Nguyen",
    "Michael Brooks",
    "Sofia Alvarez",
}

EXTRA_DRIVERS = [
    {
        "name": "Aisha Patel",
        "phone": "917-555-1004",
        "vehicle_type": "sedan",
        "vehicle_plate": "DRV-1004",
        "status": DriverStatus.AVAILABLE,
        "rating": 4.9,
    },
    {
        "name": "Carlos Rivera",
        "phone": "917-555-1005",
        "vehicle_type": "van",
        "vehicle_plate": "DRV-1005",
        "status": DriverStatus.AVAILABLE,
        "rating": 4.8,
    },
    {
        "name": "Emily Nguyen",
        "phone": "917-555-1006",
        "vehicle_type": "sedan",
        "vehicle_plate": "DRV-1006",
        "status": DriverStatus.AVAILABLE,
        "rating": 4.7,
    },
    {
        "name": "Michael Brooks",
        "phone": "917-555-1007",
        "vehicle_type": "medical_van",
        "vehicle_plate": "DRV-1007",
        "status": DriverStatus.AVAILABLE,
        "rating": 4.8,
    },
    {
        "name": "Sofia Alvarez",
        "phone": "917-555-1008",
        "vehicle_type": "sedan",
        "vehicle_plate": "DRV-1008",
        "status": DriverStatus.AVAILABLE,
        "rating": 4.9,
    },
]

KEEP_PROVIDER_NAMES = {
    "Lincoln Medical Center",
    "Queens Dialysis Facility",
    "Manhattan Health Hub",
    "Brooklyn Care Clinic",
    "Bronx Wellness Center",
}

EXTRA_PROVIDERS = [
    {
        "name": "Brooklyn Care Clinic",
        "address": "220 Atlantic Ave, Brooklyn, NY 11201",
        "phone": "718-555-0400",
        "service_type": "clinic",
    },
    {
        "name": "Bronx Wellness Center",
        "address": "880 Grand Concourse, Bronx, NY 10451",
        "phone": "718-555-0500",
        "service_type": "facility",
    },
]

KEEP_VEHICLE_PLATES = {"NYC-1001", "NYC-1002", "NYC-1003"}

KEEP_RIDERS = [
    {
        "passenger_name": "Patricia Johnson",
        "passenger_phone": "646-555-2001",
        "pickup_address": "1000 Park Ave, New York, NY 10028",
        "dropoff_address": "456 Care Ave, Queens, NY 11375",
        "service_type": "dialysis",
        "provider_name": "Queens Dialysis Facility",
    },
    {
        "passenger_name": "Robert Williams",
        "passenger_phone": "646-555-2002",
        "pickup_address": "200 West 57th St, New York, NY 10019",
        "dropoff_address": "123 Health St, Brooklyn, NY 11201",
        "service_type": "medical_appointment",
        "provider_name": "Lincoln Medical Center",
    },
    {
        "passenger_name": "Angela Thompson",
        "passenger_phone": "646-555-2003",
        "pickup_address": "88 Lexington Ave, New York, NY 10016",
        "dropoff_address": "789 Medical Pkwy, New York, NY 10001",
        "service_type": "medical_transport",
        "provider_name": "Manhattan Health Hub",
    },
    {
        "passenger_name": "Daniel Kim",
        "passenger_phone": "646-555-2004",
        "pickup_address": "15 Court Square, Long Island City, NY 11101",
        "dropoff_address": "220 Atlantic Ave, Brooklyn, NY 11201",
        "service_type": "clinic_visit",
        "provider_name": "Brooklyn Care Clinic",
    },
    {
        "passenger_name": "Grace Okonkwo",
        "passenger_phone": "646-555-2005",
        "pickup_address": "310 East 14th St, New York, NY 10003",
        "dropoff_address": "880 Grand Concourse, Bronx, NY 10451",
        "service_type": "wellness_transport",
        "provider_name": "Bronx Wellness Center",
    },
]

DEMO_NAME_MARKERS = (
    "workflow",
    "orchestration",
    "browser e2e",
    "e2e ",
    "proof",
    "test patient",
    "test user",
    "test rider",
    "ceo live",
    "revenue driver",
    "accept driver",
    "appr driver",
    "audit driver",
    "a4 driver",
    "phase ",
    "lifecycle",
    "financial",
    "placeholder",
    "demo",
    "smoke",
    "ops_clean",
    "render_ready",
    "prod_sync",
    "bill_sync",
    "jordan ellis",
    "malik",
    "mlik",
    "wonokay",
    "jennifer brown",
    "temp passenger",
    "smoke-test",
    "smoke test",
)


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _is_demo_name(value: object) -> bool:
    text = _norm(value)
    return any(marker in text for marker in DEMO_NAME_MARKERS)


def _is_terminal(ride: HealthISFRide) -> bool:
    return _norm(ride.lifecycle_state or ride.status) in {"completed", "cancelled", "failed"}


def _delete_ride_artifacts(db, ride_ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not ride_ids:
        return counts
    trip_ids = [
        str(row[0])
        for row in db.query(HealthISFTrip.id).filter(HealthISFTrip.ride_id.in_(ride_ids)).all()
    ]
    if trip_ids:
        counts["payouts"] = int(
            db.query(HealthISFPayout)
            .filter(HealthISFPayout.trip_id.in_(trip_ids))
            .delete(synchronize_session=False)
            or 0
        )
    models = (
        HealthISFTripDocument,
        HealthISFSettlementLedger,
        HealthISFClaim,
        HealthISFBillingHandoff,
        HealthISFTripFinancialRecord,
        HealthISFPaymentTransaction,
        HealthISFRideExecutionAction,
        HealthISFRideRoutePlan,
        HealthISFRideStatusHistory,
        HealthISFDispatchLog,
        HealthISFDispatchAssignment,
        RideAssignmentLock,
        RealTimeEvent,
        HealthISFTrip,
        HealthISFCustomerRideRequest,
    )
    for model in models:
        counts[model.__tablename__] = int(
            db.query(model).filter(model.ride_id.in_(ride_ids)).delete(synchronize_session=False) or 0
        )
    db.query(HealthISFDriverLocationPing).filter(
        HealthISFDriverLocationPing.ride_id.in_(ride_ids)
    ).update({HealthISFDriverLocationPing.ride_id: None}, synchronize_session=False)
    counts["rides"] = int(
        db.query(HealthISFRide).filter(HealthISFRide.id.in_(ride_ids)).delete(synchronize_session=False)
        or 0
    )
    return counts


def _ensure_providers(db, org_id: str) -> dict[str, HealthISFProvider]:
    by_name: dict[str, HealthISFProvider] = {}
    for item in list(SAMPLE_PROVIDERS) + EXTRA_PROVIDERS:
        name = item["name"]
        row = (
            db.query(HealthISFProvider)
            .filter(
                HealthISFProvider.organization_id == org_id,
                HealthISFProvider.name == name,
            )
            .order_by(HealthISFProvider.created_at.asc())
            .first()
        )
        if not row:
            row = HealthISFProvider(
                id=uuid4(),
                organization_id=org_id,
                name=name,
                address=item["address"],
                phone=item["phone"],
                service_type=item["service_type"],
                is_active=True,
                created_at=now(),
                updated_at=now(),
            )
            db.add(row)
            db.flush()
        else:
            row.address = item["address"]
            row.phone = item["phone"]
            row.service_type = item["service_type"]
            row.is_active = True
            row.updated_at = now()
        by_name[name] = row
    return by_name


def _ensure_drivers_and_vehicles(
    db, org_id: str
) -> tuple[dict[str, HealthISFDriver], dict[str, HealthISFVehicle]]:
    drivers_by_name: dict[str, HealthISFDriver] = {}
    vehicles_by_plate: dict[str, HealthISFVehicle] = {}

    # Fleet vehicles: exactly the 3 production plates.
    for item in SAMPLE_DRIVERS:
        plate = item["vehicle_plate"]
        vehicle = (
            db.query(HealthISFVehicle)
            .filter(
                HealthISFVehicle.organization_id == org_id,
                HealthISFVehicle.vehicle_plate == plate,
            )
            .order_by(HealthISFVehicle.created_at.asc())
            .first()
        )
        if not vehicle:
            vehicle = HealthISFVehicle(
                id=uuid4(),
                organization_id=org_id,
                vehicle_type=item["vehicle_type"],
                vehicle_plate=plate,
                capacity=4,
                is_active=True,
                created_at=now(),
                updated_at=now(),
            )
            db.add(vehicle)
            db.flush()
        else:
            vehicle.vehicle_type = item["vehicle_type"]
            vehicle.is_active = True
            vehicle.updated_at = now()
        vehicles_by_plate[plate] = vehicle

    for item in list(SAMPLE_DRIVERS) + EXTRA_DRIVERS:
        plate = item["vehicle_plate"]
        vehicle = vehicles_by_plate.get(plate)
        driver = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == org_id,
                HealthISFDriver.name == item["name"],
            )
            .order_by(HealthISFDriver.created_at.asc())
            .first()
        )
        if not driver:
            # Phone uniqueness is global — reclaim orphan phone if needed.
            phone_owner = (
                db.query(HealthISFDriver)
                .filter(HealthISFDriver.phone == item["phone"])
                .order_by(HealthISFDriver.created_at.asc())
                .first()
            )
            plate_owner = (
                db.query(HealthISFDriver)
                .filter(HealthISFDriver.vehicle_plate == plate)
                .order_by(HealthISFDriver.created_at.asc())
                .first()
            )
            if phone_owner and str(phone_owner.organization_id) == org_id:
                driver = phone_owner
            elif plate_owner and str(plate_owner.organization_id) == org_id:
                driver = plate_owner

        if not driver:
            driver = HealthISFDriver(
                id=uuid4(),
                organization_id=org_id,
                vehicle_id=vehicle.id if vehicle else None,
                name=item["name"],
                phone=item["phone"],
                vehicle_type=item["vehicle_type"],
                vehicle_plate=plate,
                status=DriverStatus.AVAILABLE,
                availability_state="available",
                is_active=True,
                is_online=True,
                auth_state="active",
                total_trips=0,
                rating=item["rating"],
                created_at=now(),
                updated_at=now(),
            )
            db.add(driver)
            db.flush()
        else:
            # Free unique constraints on other rows before updating.
            conflicts = (
                db.query(HealthISFDriver)
                .filter(
                    HealthISFDriver.id != driver.id,
                    HealthISFDriver.phone == item["phone"],
                )
                .all()
            )
            for conflict in conflicts:
                conflict.phone = f"000-DEL-{str(conflict.id)[:8]}"
            plate_conflicts = (
                db.query(HealthISFDriver)
                .filter(
                    HealthISFDriver.id != driver.id,
                    HealthISFDriver.vehicle_plate == plate,
                )
                .all()
            )
            for conflict in plate_conflicts:
                conflict.vehicle_plate = f"DEL-{str(conflict.id)[:8]}"
            if vehicle:
                # vehicle_id is unique — clear other drivers linked to this vehicle.
                db.query(HealthISFDriver).filter(
                    HealthISFDriver.vehicle_id == vehicle.id,
                    HealthISFDriver.id != driver.id,
                ).update({HealthISFDriver.vehicle_id: None}, synchronize_session=False)

            driver.name = item["name"]
            driver.phone = item["phone"]
            driver.vehicle_id = vehicle.id if vehicle else None
            driver.vehicle_type = item["vehicle_type"]
            driver.vehicle_plate = plate
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_active = True
            driver.is_online = True
            driver.auth_state = "active"
            driver.rating = item["rating"]
            driver.organization_id = org_id
            driver.updated_at = now()
        drivers_by_name[item["name"]] = driver
    return drivers_by_name, vehicles_by_plate


def _ensure_seed_riders(
    db,
    org_id: str,
    providers: dict[str, HealthISFProvider],
    default_driver: HealthISFDriver,
) -> list[str]:
    """Ensure 5 realistic completed seed rides + customer requests (riders)."""
    kept_request_ids: list[str] = []
    for item in KEEP_RIDERS:
        provider = providers[item["provider_name"]]
        ride = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.organization_id == org_id,
                HealthISFRide.passenger_phone == item["passenger_phone"],
            )
            .order_by(HealthISFRide.created_at.asc())
            .first()
        )
        if not ride:
            ride = HealthISFRide(
                id=uuid4(),
                organization_id=org_id,
                provider_id=provider.id,
                driver_id=default_driver.id,
                vehicle_id=default_driver.vehicle_id,
                passenger_name=item["passenger_name"],
                passenger_phone=item["passenger_phone"],
                pickup_address=item["pickup_address"],
                dropoff_address=item["dropoff_address"],
                service_type=item["service_type"],
                status=RideStatus.COMPLETED,
                lifecycle_state=RideStatus.COMPLETED.value,
                estimated_distance_miles=6.0,
                estimated_duration_minutes=20,
                notes="production seed rider",
                completed_at=now(),
                created_at=now(),
                updated_at=now(),
            )
            db.add(ride)
            db.flush()
        else:
            ride.passenger_name = item["passenger_name"]
            ride.passenger_phone = item["passenger_phone"]
            ride.pickup_address = item["pickup_address"]
            ride.dropoff_address = item["dropoff_address"]
            ride.service_type = item["service_type"]
            ride.provider_id = provider.id
            if not ride.driver_id:
                ride.driver_id = default_driver.id
            ride.status = RideStatus.COMPLETED
            ride.lifecycle_state = RideStatus.COMPLETED.value
            ride.notes = "production seed rider"
            ride.completed_at = ride.completed_at or now()
            ride.updated_at = now()

        req = (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.ride_id == ride.id)
            .first()
        )
        if not req:
            req = HealthISFCustomerRideRequest(
                id=uuid4(),
                organization_id=org_id,
                ride_id=ride.id,
                rider_name=item["passenger_name"],
                rider_phone=item["passenger_phone"],
                pickup_address=item["pickup_address"],
                dropoff_address=item["dropoff_address"],
                ride_type="healthcare",
                dispatch_status=CustomerRequestStatus.COMPLETED.value,
                notes="production seed rider profile",
                completed_at=now(),
                created_at=now(),
                updated_at=now(),
            )
            db.add(req)
            db.flush()
        else:
            req.rider_name = item["passenger_name"]
            req.rider_phone = item["passenger_phone"]
            req.pickup_address = item["pickup_address"]
            req.dropoff_address = item["dropoff_address"]
            req.dispatch_status = CustomerRequestStatus.COMPLETED.value
            req.completed_at = req.completed_at or now()
            req.updated_at = now()
        kept_request_ids.append(str(req.id))
    return kept_request_ids


def _remap_refs_to_kept(
    db,
    org_id: str,
    keep_driver_ids: set[str],
    keep_provider_ids: set[str],
    default_driver_id: str,
    default_provider_id: str,
) -> dict[str, int]:
    stats = {"rides": 0, "trips": 0, "payouts": 0, "payments": 0, "assignments": 0}
    for ride in db.query(HealthISFRide).filter(HealthISFRide.organization_id == org_id).all():
        changed = False
        if ride.provider_id and str(ride.provider_id) not in keep_provider_ids:
            ride.provider_id = default_provider_id
            changed = True
        if ride.driver_id and str(ride.driver_id) not in keep_driver_ids:
            if _is_terminal(ride):
                ride.driver_id = default_driver_id
            else:
                ride.status = RideStatus.CANCELLED
                ride.lifecycle_state = RideStatus.CANCELLED.value
                ride.driver_id = None
            changed = True
        if changed:
            ride.updated_at = now()
            stats["rides"] += 1

    for trip in db.query(HealthISFTrip).all():
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == trip.ride_id).first()
        if not ride or str(ride.organization_id) != org_id:
            continue
        if str(trip.driver_id) not in keep_driver_ids:
            trip.driver_id = default_driver_id
            trip.updated_at = now()
            stats["trips"] += 1

    for payout in db.query(HealthISFPayout).all():
        if str(payout.driver_id) not in keep_driver_ids:
            # Only remap payouts tied to org rides via trip.
            trip = db.query(HealthISFTrip).filter(HealthISFTrip.id == payout.trip_id).first()
            if not trip:
                continue
            ride = db.query(HealthISFRide).filter(HealthISFRide.id == trip.ride_id).first()
            if ride and str(ride.organization_id) == org_id:
                payout.driver_id = default_driver_id
                payout.updated_at = now()
                stats["payouts"] += 1

    for pay in (
        db.query(HealthISFPaymentTransaction)
        .filter(HealthISFPaymentTransaction.organization_id == org_id)
        .all()
    ):
        changed = False
        if pay.driver_id and str(pay.driver_id) not in keep_driver_ids:
            pay.driver_id = default_driver_id
            changed = True
        if pay.provider_id and str(pay.provider_id) not in keep_provider_ids:
            pay.provider_id = default_provider_id
            changed = True
        if changed:
            stats["payments"] += 1

    for row in (
        db.query(HealthISFDispatchAssignment)
        .filter(HealthISFDispatchAssignment.organization_id == org_id)
        .all()
    ):
        if row.driver_id and str(row.driver_id) not in keep_driver_ids:
            row.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
            row.driver_id = None
            row.updated_at = now()
            stats["assignments"] += 1
    return stats


def main() -> int:
    db = SessionLocal()
    report: dict[str, object] = {"organization_id": ORG_ID}
    try:
        org = db.query(HealthISFOrganization).filter(HealthISFOrganization.id == ORG_ID).first()
        if not org:
            print("DATABASE_CLEAN=false", flush=True)
            print("SEED_DATA_READY=false", flush=True)
            print("REFERENTIAL_INTEGRITY=false", flush=True)
            print("READY_FOR_RENDER=false", flush=True)
            print(f"DETAIL=organization not found {ORG_ID}", flush=True)
            return 1

        providers = _ensure_providers(db, ORG_ID)
        drivers, vehicles = _ensure_drivers_and_vehicles(db, ORG_ID)
        keep_provider_ids = {str(p.id) for p in providers.values()}
        keep_driver_ids = {str(d.id) for d in drivers.values()}
        keep_vehicle_ids = {str(v.id) for v in vehicles.values()}

        default_provider_id = str(providers["Lincoln Medical Center"].id)
        default_driver = drivers["James Smith"]
        default_driver_id = str(default_driver.id)

        rider_ids = _ensure_seed_riders(db, ORG_ID, providers, default_driver)
        keep_rider_phones = {item["passenger_phone"] for item in KEEP_RIDERS}
        keep_rider_names = {_norm(item["passenger_name"]) for item in KEEP_RIDERS}
        report["kept_rider_request_ids"] = rider_ids

        # Remove demo/proof/test rides (except the 5 seed riders).
        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == ORG_ID).all()
        remove_ride_ids: list[str] = []
        for ride in rides:
            phone = str(ride.passenger_phone or "")
            if phone in keep_rider_phones and _norm(ride.passenger_name) in keep_rider_names:
                continue
            passenger = str(ride.passenger_name or "")
            if (
                _is_demo_name(passenger)
                or _is_test_ride_row(ride)
                or _is_ai_proof_ride(ride)
                or phone.startswith("000-")
            ):
                remove_ride_ids.append(str(ride.id))
        report["removed_demo_rides"] = _delete_ride_artifacts(db, remove_ride_ids)

        # Remap remaining refs away from doomed entities before deletes.
        report["remapped"] = _remap_refs_to_kept(
            db,
            ORG_ID,
            keep_driver_ids,
            keep_provider_ids,
            default_driver_id,
            default_provider_id,
        )

        # Keep only seed rider customer requests.
        keep_rider_id_set = set(rider_ids)
        removed_reqs = 0
        for req in (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.organization_id == ORG_ID)
            .all()
        ):
            if str(req.id) in keep_rider_id_set:
                continue
            db.delete(req)
            removed_reqs += 1
        report["removed_customer_requests"] = removed_reqs

        # Delete non-kept drivers (after remapping RESTRICT refs).
        all_drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == ORG_ID).all()
        delete_driver_ids = [str(d.id) for d in all_drivers if str(d.id) not in keep_driver_ids]
        if delete_driver_ids:
            # Force-clear every FK that can block RESTRICT deletes.
            db.query(HealthISFRide).filter(HealthISFRide.driver_id.in_(delete_driver_ids)).update(
                {HealthISFRide.driver_id: default_driver_id}, synchronize_session=False
            )
            db.query(HealthISFTrip).filter(HealthISFTrip.driver_id.in_(delete_driver_ids)).update(
                {HealthISFTrip.driver_id: default_driver_id}, synchronize_session=False
            )
            db.query(HealthISFPayout).filter(HealthISFPayout.driver_id.in_(delete_driver_ids)).update(
                {HealthISFPayout.driver_id: default_driver_id}, synchronize_session=False
            )
            db.query(HealthISFPaymentTransaction).filter(
                HealthISFPaymentTransaction.driver_id.in_(delete_driver_ids)
            ).update(
                {HealthISFPaymentTransaction.driver_id: default_driver_id},
                synchronize_session=False,
            )
            db.query(HealthISFDispatchLog).filter(
                HealthISFDispatchLog.driver_id.in_(delete_driver_ids)
            ).update({HealthISFDispatchLog.driver_id: None}, synchronize_session=False)
            db.query(HealthISFDispatchAssignment).filter(
                HealthISFDispatchAssignment.driver_id.in_(delete_driver_ids)
            ).update({HealthISFDispatchAssignment.driver_id: None}, synchronize_session=False)
            db.query(RealTimeEvent).filter(RealTimeEvent.driver_id.in_(delete_driver_ids)).update(
                {RealTimeEvent.driver_id: None}, synchronize_session=False
            )
            db.query(HealthISFTripDocument).filter(
                HealthISFTripDocument.driver_id.in_(delete_driver_ids)
            ).update({HealthISFTripDocument.driver_id: None}, synchronize_session=False)
            db.query(HealthISFDriverSession).filter(
                HealthISFDriverSession.driver_id.in_(delete_driver_ids)
            ).delete(synchronize_session=False)
            db.query(HealthISFDriverLocationPing).filter(
                HealthISFDriverLocationPing.driver_id.in_(delete_driver_ids)
            ).delete(synchronize_session=False)
            # Clear optional tables that may not be mapped in this script.
            for table in (
                "health_isf_dispatch_event_retries",
                "health_isf_dispatcher_activity",
                "health_isf_workflow_executions",
                "health_isf_workflow_incidents",
            ):
                for i in range(0, len(delete_driver_ids), 200):
                    chunk = delete_driver_ids[i : i + 200]
                    ph = ", ".join(f":d{j}" for j in range(len(chunk)))
                    params = {f"d{j}": chunk[j] for j in range(len(chunk))}
                    db.execute(
                        text(f"UPDATE {table} SET driver_id = NULL WHERE driver_id IN ({ph})"),
                        params,
                    )
            # Chunk deletes — SQLite parameter limits.
            deleted = 0
            for i in range(0, len(delete_driver_ids), 200):
                chunk = delete_driver_ids[i : i + 200]
                deleted += int(
                    db.query(HealthISFDriver)
                    .filter(HealthISFDriver.id.in_(chunk))
                    .delete(synchronize_session=False)
                    or 0
                )
            report["deleted_drivers"] = deleted
        else:
            report["deleted_drivers"] = 0

        # Delete workflow/demo/duplicate providers.
        all_providers = (
            db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == ORG_ID).all()
        )
        delete_provider_ids = [str(p.id) for p in all_providers if str(p.id) not in keep_provider_ids]
        if delete_provider_ids:
            db.query(HealthISFRide).filter(HealthISFRide.provider_id.in_(delete_provider_ids)).update(
                {HealthISFRide.provider_id: default_provider_id}, synchronize_session=False
            )
            db.query(HealthISFPaymentTransaction).filter(
                HealthISFPaymentTransaction.provider_id.in_(delete_provider_ids)
            ).update(
                {HealthISFPaymentTransaction.provider_id: default_provider_id},
                synchronize_session=False,
            )
            db.query(HealthISFRecurringRideSchedule).filter(
                HealthISFRecurringRideSchedule.provider_id.in_(delete_provider_ids)
            ).update(
                {HealthISFRecurringRideSchedule.provider_id: default_provider_id},
                synchronize_session=False,
            )
            report["deleted_providers"] = int(
                db.query(HealthISFProvider)
                .filter(HealthISFProvider.id.in_(delete_provider_ids))
                .delete(synchronize_session=False)
                or 0
            )
        else:
            report["deleted_providers"] = 0

        # Delete non-production vehicles (keep only NYC-1001/1002/1003).
        all_vehicles = (
            db.query(HealthISFVehicle).filter(HealthISFVehicle.organization_id == ORG_ID).all()
        )
        delete_vehicle_ids: list[str] = []
        for vehicle in all_vehicles:
            plate = str(vehicle.vehicle_plate or "")
            if plate in KEEP_VEHICLE_PLATES and str(vehicle.id) in keep_vehicle_ids:
                vehicle.is_active = True
                continue
            if plate in KEEP_VEHICLE_PLATES:
                # Duplicate plate rows — keep the ensured one only.
                if str(vehicle.id) in keep_vehicle_ids:
                    vehicle.is_active = True
                    continue
            db.query(HealthISFDriver).filter(HealthISFDriver.vehicle_id == vehicle.id).update(
                {HealthISFDriver.vehicle_id: None}, synchronize_session=False
            )
            db.query(HealthISFRide).filter(HealthISFRide.vehicle_id == vehicle.id).update(
                {HealthISFRide.vehicle_id: None}, synchronize_session=False
            )
            delete_vehicle_ids.append(str(vehicle.id))
        # Also delete duplicate keep-plate vehicles not in keep_vehicle_ids.
        for vehicle in all_vehicles:
            plate = str(vehicle.vehicle_plate or "")
            if plate in KEEP_VEHICLE_PLATES and str(vehicle.id) not in keep_vehicle_ids:
                if str(vehicle.id) not in delete_vehicle_ids:
                    db.query(HealthISFDriver).filter(HealthISFDriver.vehicle_id == vehicle.id).update(
                        {HealthISFDriver.vehicle_id: None}, synchronize_session=False
                    )
                    db.query(HealthISFRide).filter(HealthISFRide.vehicle_id == vehicle.id).update(
                        {HealthISFRide.vehicle_id: None}, synchronize_session=False
                    )
                    delete_vehicle_ids.append(str(vehicle.id))
        if delete_vehicle_ids:
            report["deleted_vehicles"] = int(
                db.query(HealthISFVehicle)
                .filter(HealthISFVehicle.id.in_(delete_vehicle_ids))
                .delete(synchronize_session=False)
                or 0
            )
        else:
            report["deleted_vehicles"] = 0

        # Re-link primary three drivers to fleet vehicles.
        for item in SAMPLE_DRIVERS:
            driver = drivers[item["name"]]
            vehicle = vehicles[item["vehicle_plate"]]
            driver.vehicle_id = vehicle.id
            driver.vehicle_plate = item["vehicle_plate"]
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_active = True
            driver.is_online = True
        for item in EXTRA_DRIVERS:
            driver = drivers[item["name"]]
            driver.vehicle_id = None
            driver.vehicle_plate = item["vehicle_plate"]
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_active = True
            driver.is_online = True

        # Clean demo driver applications.
        apps = (
            db.query(HealthISFDriverApplication)
            .filter(HealthISFDriverApplication.organization_id == ORG_ID)
            .all()
        )
        removed_apps = 0
        for app in apps:
            if _is_demo_name(app.applicant_name):
                db.delete(app)
                removed_apps += 1
        report["removed_driver_applications"] = removed_apps

        # Global cleanup: Workflow placeholders + ephemeral test tenants.
        workflow_providers = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.name.ilike("%workflow%"))
            .all()
        )
        workflow_provider_ids = [str(p.id) for p in workflow_providers]
        if workflow_provider_ids:
            db.query(HealthISFRide).filter(
                HealthISFRide.provider_id.in_(workflow_provider_ids)
            ).update({HealthISFRide.provider_id: None}, synchronize_session=False)
            db.query(HealthISFRecurringRideSchedule).filter(
                HealthISFRecurringRideSchedule.provider_id.in_(workflow_provider_ids)
            ).update(
                {HealthISFRecurringRideSchedule.provider_id: None},
                synchronize_session=False,
            )
            db.query(HealthISFPaymentTransaction).filter(
                HealthISFPaymentTransaction.provider_id.in_(workflow_provider_ids)
            ).update(
                {HealthISFPaymentTransaction.provider_id: None},
                synchronize_session=False,
            )
            report["deleted_workflow_providers"] = int(
                db.query(HealthISFProvider)
                .filter(HealthISFProvider.id.in_(workflow_provider_ids))
                .delete(synchronize_session=False)
                or 0
            )
        else:
            report["deleted_workflow_providers"] = 0

        workflow_drivers = (
            db.query(HealthISFDriver).filter(HealthISFDriver.name.ilike("%workflow%")).all()
        )
        workflow_driver_ids = [str(d.id) for d in workflow_drivers]
        if workflow_driver_ids:
            db.query(HealthISFRide).filter(
                HealthISFRide.driver_id.in_(workflow_driver_ids)
            ).update({HealthISFRide.driver_id: None}, synchronize_session=False)
            db.query(HealthISFTrip).filter(
                HealthISFTrip.driver_id.in_(workflow_driver_ids)
            ).update({HealthISFTrip.driver_id: default_driver_id}, synchronize_session=False)
            db.query(HealthISFPayout).filter(
                HealthISFPayout.driver_id.in_(workflow_driver_ids)
            ).update({HealthISFPayout.driver_id: default_driver_id}, synchronize_session=False)
            db.query(HealthISFDriverSession).filter(
                HealthISFDriverSession.driver_id.in_(workflow_driver_ids)
            ).delete(synchronize_session=False)
            db.query(HealthISFDriverLocationPing).filter(
                HealthISFDriverLocationPing.driver_id.in_(workflow_driver_ids)
            ).delete(synchronize_session=False)
            report["deleted_workflow_drivers"] = int(
                db.query(HealthISFDriver)
                .filter(HealthISFDriver.id.in_(workflow_driver_ids))
                .delete(synchronize_session=False)
                or 0
            )
        else:
            report["deleted_workflow_drivers"] = 0

        # Remove ephemeral Other Tenant / External * test orgs (not production).
        test_orgs = (
            db.query(HealthISFOrganization)
            .filter(HealthISFOrganization.id != ORG_ID)
            .all()
        )
        deleted_test_orgs = 0
        for org_row in test_orgs:
            name = _norm(org_row.name)
            code = _norm(org_row.code)
            is_test_org = (
                name.startswith("other tenant")
                or name.startswith("external ")
                or name.startswith("deferred publish")
                or name.startswith("debug org")
                or name.startswith("manual org")
                or code.startswith("ot-")
                or code.startswith("ext-")
                or code.startswith("dp-")
                or code.startswith("dbg-")
                or code.startswith("man-")
                or code == "amicor-isf"
                or str(org_row.id).startswith("org-phase16-")
                or str(org_row.id).startswith("org-debug-")
                or str(org_row.id).startswith("org-manual-")
                or str(org_row.id) == "00000000-0000-0000-0000-00000000a1c0"
            )
            if not is_test_org:
                continue
            oid = str(org_row.id)
            org_ride_ids = [
                str(r[0])
                for r in db.query(HealthISFRide.id)
                .filter(HealthISFRide.organization_id == oid)
                .all()
            ]
            if org_ride_ids:
                _delete_ride_artifacts(db, org_ride_ids)
            db.query(HealthISFDriverSession).filter(
                HealthISFDriverSession.organization_id == oid
            ).delete(synchronize_session=False)
            db.query(HealthISFDriverLocationPing).filter(
                HealthISFDriverLocationPing.organization_id == oid
            ).delete(synchronize_session=False)
            db.query(HealthISFCustomerRideRequest).filter(
                HealthISFCustomerRideRequest.organization_id == oid
            ).delete(synchronize_session=False)
            db.query(HealthISFDispatchAssignment).filter(
                HealthISFDispatchAssignment.organization_id == oid
            ).delete(synchronize_session=False)
            db.query(HealthISFDriverApplication).filter(
                HealthISFDriverApplication.organization_id == oid
            ).delete(synchronize_session=False)
            db.query(HealthISFRecurringRideSchedule).filter(
                HealthISFRecurringRideSchedule.organization_id == oid
            ).delete(synchronize_session=False)
            db.query(HealthISFPaymentTransaction).filter(
                HealthISFPaymentTransaction.organization_id == oid
            ).delete(synchronize_session=False)
            db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == oid).delete(
                synchronize_session=False
            )
            db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == oid).delete(
                synchronize_session=False
            )
            db.query(HealthISFVehicle).filter(HealthISFVehicle.organization_id == oid).delete(
                synchronize_session=False
            )
            db.delete(org_row)
            deleted_test_orgs += 1
        report["deleted_test_orgs"] = deleted_test_orgs

        db.commit()

        # Integrity verification.
        drivers_left = (
            db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == ORG_ID).all()
        )
        providers_left = (
            db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == ORG_ID).all()
        )
        vehicles_left = (
            db.query(HealthISFVehicle).filter(HealthISFVehicle.organization_id == ORG_ID).all()
        )
        riders_left = (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.organization_id == ORG_ID)
            .all()
        )
        rides_left = db.query(HealthISFRide).filter(HealthISFRide.organization_id == ORG_ID).all()

        driver_ids = {str(d.id) for d in drivers_left}
        provider_ids = {str(p.id) for p in providers_left}

        orphan_driver_refs = [
            str(r.id) for r in rides_left if r.driver_id and str(r.driver_id) not in driver_ids
        ]
        orphan_provider_refs = [
            str(r.id) for r in rides_left if r.provider_id and str(r.provider_id) not in provider_ids
        ]
        active_bad = [
            str(r.id)
            for r in rides_left
            if not _is_terminal(r)
            and (
                (r.driver_id and str(r.driver_id) not in driver_ids)
                or (r.provider_id and str(r.provider_id) not in provider_ids)
                or _is_demo_name(r.passenger_name)
            )
        ]
        demo_drivers = [d.name for d in drivers_left if _is_demo_name(d.name)]
        demo_providers = [
            p.name for p in providers_left if _is_demo_name(p.name) or "workflow" in _norm(p.name)
        ]
        dname_map: dict[str, int] = defaultdict(int)
        for d in drivers_left:
            dname_map[_norm(d.name)] += 1
        pname_map: dict[str, int] = defaultdict(int)
        for p in providers_left:
            pname_map[_norm(p.name)] += 1
        dup_driver_names = [n for n, c in dname_map.items() if c > 1]
        dup_provider_names = [n for n, c in pname_map.items() if c > 1]

        active_vehicles = [v for v in vehicles_left if v.is_active]
        seed_rider_names = sorted({r.rider_name for r in riders_left})
        seed_ready = (
            5 <= len(drivers_left) <= 10
            and len(providers_left) == 5
            and len(active_vehicles) == 3
            and len(vehicles_left) == 3
            and len(riders_left) == 5
            and not demo_drivers
            and not demo_providers
            and not dup_driver_names
            and not dup_provider_names
            and set(seed_rider_names)
            == {item["passenger_name"] for item in KEEP_RIDERS}
        )
        integrity = not orphan_driver_refs and not orphan_provider_refs and not active_bad
        clean = seed_ready and integrity

        report.update(
            {
                "drivers": len(drivers_left),
                "driver_names": sorted(d.name for d in drivers_left),
                "providers": len(providers_left),
                "provider_names": sorted(p.name for p in providers_left),
                "vehicles_total": len(vehicles_left),
                "vehicles_active": len(active_vehicles),
                "vehicle_plates": sorted(v.vehicle_plate for v in active_vehicles),
                "riders": len(riders_left),
                "rider_names": seed_rider_names,
                "rides_remaining": len(rides_left),
                "orphan_driver_refs": orphan_driver_refs,
                "orphan_provider_refs": orphan_provider_refs,
                "active_bad_refs": active_bad,
                "dup_driver_names": dup_driver_names,
                "dup_provider_names": dup_provider_names,
                "demo_drivers": demo_drivers,
                "demo_providers": demo_providers,
            }
        )

        print(f"DATABASE_CLEAN={'true' if clean else 'false'}", flush=True)
        print(f"SEED_DATA_READY={'true' if seed_ready else 'false'}", flush=True)
        print(f"REFERENTIAL_INTEGRITY={'true' if integrity else 'false'}", flush=True)
        print(f"READY_FOR_RENDER={'true' if clean else 'false'}", flush=True)
        print(json.dumps(report, indent=2, default=str), flush=True)
        return 0 if clean else 1
    except Exception as exc:
        db.rollback()
        print("DATABASE_CLEAN=false", flush=True)
        print("SEED_DATA_READY=false", flush=True)
        print("REFERENTIAL_INTEGRITY=false", flush=True)
        print("READY_FOR_RENDER=false", flush=True)
        print(f"DETAIL={exc}", flush=True)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
