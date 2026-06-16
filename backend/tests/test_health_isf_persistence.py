import tempfile
import unittest
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.auth as auth_module
from app.db.models import User
from app.db.session import Base, get_db
from app.helpers import now, uuid4
from app.modules.health_isf import routes as health_routes
from app.modules.health_isf import service as health_service
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDispatchLog,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFRideStatusHistory,
    HealthISFVehicle,
    RideStatus,
)


@dataclass
class _FakeUser:
    id: str
    email: str
    role: str
    organization_id: str
    organization_name: str
    is_active: bool = True


T = TypeVar("T")


class HealthISFPersistenceIntegrationTests(unittest.TestCase):
    def _require(self, value: T | None, message: str) -> T:
        if value is None:
            self.fail(message)
            raise AssertionError(message)
        return value

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls._tmp_dir.name) / "health_isf_test.db"
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(cls.engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

        cls._seed_foundation()
        cls._build_api_client()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.engine.dispose()
        cls._tmp_dir.cleanup()

    @classmethod
    def _build_api_client(cls) -> None:
        app = FastAPI()
        app.include_router(health_routes.router)

        def _override_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        def _override_current_user():
            return cls.fake_user

        def _override_user_context():
            return auth_module.UserContext(
                user_id=cls.fake_user.id,
                email=cls.fake_user.email,
                role=cls.fake_user.role,
                organization_name=cls.fake_user.organization_name,
                organization_id=cls.fake_user.organization_id,
            )

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[auth_module.get_current_user] = _override_current_user
        app.dependency_overrides[auth_module.get_current_user_context] = _override_user_context

        cls.client = TestClient(app)

    @classmethod
    def _seed_foundation(cls) -> None:
        db = cls.SessionLocal()
        try:
            cls.user_id = uuid4()
            cls.org_id = uuid4()
            cls.org2_id = uuid4()
            cls.provider_id = uuid4()
            cls.driver_id = uuid4()
            cls.vehicle_id = uuid4()

            user = User(
                id=cls.user_id,
                email="dispatcher@test.local",
                hashed_password="pbkdf2$260000$testsalt$testhash",
                display_name="Dispatcher",
                role="dispatcher",
                organization_name="Test Org",
                organization_id=cls.org_id,
                is_active=True,
                is_verified=True,
            )
            org = HealthISFOrganization(
                id=cls.org_id,
                name="Test Org",
                code="TEST-ORG",
                is_active=True,
            )
            org2 = HealthISFOrganization(
                id=cls.org2_id,
                name="Other Org",
                code="OTHER-ORG",
                is_active=True,
            )
            provider = HealthISFProvider(
                id=cls.provider_id,
                organization_id=cls.org_id,
                name="Provider One",
                address="1 Provider St",
                phone="111-111-1111",
                service_type="clinic",
                is_active=True,
            )
            vehicle = HealthISFVehicle(
                id=cls.vehicle_id,
                organization_id=cls.org_id,
                vehicle_type="van",
                vehicle_plate="TEST-PLATE-1",
                capacity=4,
                is_active=True,
            )
            driver = HealthISFDriver(
                id=cls.driver_id,
                organization_id=cls.org_id,
                vehicle_id=cls.vehicle_id,
                name="Driver One",
                phone="222-222-2222",
                vehicle_type="van",
                vehicle_plate="DRV-PLATE-1",
                status=DriverStatus.AVAILABLE,
                is_active=True,
                total_trips=0,
                rating=4.8,
            )

            db.add_all([org, org2])
            db.flush()
            db.add_all([user, provider, vehicle, driver])
            db.commit()
            # Reload to ensure relationships are hydrated
            db.expire_all()
            org = db.get(HealthISFOrganization, cls.org_id)
            assert org is not None, "Seeded organization not found after commit"
            provider = db.get(HealthISFProvider, cls.provider_id)
            assert provider is not None, "Seeded provider not found after commit"
            vehicle = db.get(HealthISFVehicle, cls.vehicle_id)
            assert vehicle is not None, "Seeded vehicle not found after commit"
            driver = db.get(HealthISFDriver, cls.driver_id)
            assert driver is not None, "Seeded driver not found after commit"

            cls.fake_user = _FakeUser(
                id=cls.user_id,
                email="dispatcher@test.local",
                role="dispatcher",
                organization_id=cls.org_id,
                organization_name="Test Org",
            )
        finally:
            db.close()

    def _with_db(self, fn: Callable[[Session], None]) -> None:
        db = self.SessionLocal()
        try:
            fn(db)
        finally:
            db.close()

    def setUp(self) -> None:
        def _run(db: Session) -> None:
            vehicle_id = uuid4()
            driver_id = uuid4()
            db.add(HealthISFVehicle(
                id=vehicle_id,
                organization_id=self.org_id,
                vehicle_type="van",
                vehicle_plate=f"TEST-{driver_id[:8]}",
                capacity=4,
                is_active=True,
            ))
            db.add(HealthISFDriver(
                id=driver_id,
                organization_id=self.org_id,
                vehicle_id=vehicle_id,
                name=f"Driver {driver_id[:6]}",
                phone=f"222-555-{driver_id.replace('-', '')[:4]}",
                vehicle_type="van",
                vehicle_plate=f"DRV-{driver_id[:6]}",
                status=DriverStatus.AVAILABLE,
                is_active=True,
                total_trips=0,
                rating=4.8,
            ))
            db.commit()
            self.driver_id = driver_id
            self.vehicle_id = vehicle_id

        self._with_db(_run)

    def _create_ride(self, db: Session, *, actor: str | None = None) -> HealthISFRide:
        return health_service.create_ride(
            db=db,
            passenger_name="Patient A",
            passenger_phone="333-333-3333",
            pickup_address="100 Pickup Ave",
            dropoff_address="200 Dropoff Ave",
            service_type="medical_transport",
            provider_id=self.provider_id,
            organization_id=self.org_id,
            notes="integration",
            actor_user_id=actor or self.user_id,
        )

    def _count(self, db: Session, model) -> int:
        return db.query(model).count()

    def test_relational_integrity_links(self) -> None:
        def _run(db: Session) -> None:
            ride = self._create_ride(db)
            health_service.assign_driver_to_ride(db, ride.id, self.driver_id, actor_user_id=self.user_id)

            org = self._require(db.get(HealthISFOrganization, self.org_id), "Organization not found in DB after setup")
            self.assertIsNotNone(org.providers, "Organization.providers is None")
            self.assertTrue(any(p.id == self.provider_id for p in org.providers), "Provider not found in org.providers")
            self.assertIsNotNone(org.drivers, "Organization.drivers is None")
            self.assertTrue(any(d.id == self.driver_id for d in org.drivers), "Driver not found in org.drivers")
            self.assertIsNotNone(org.vehicles, "Organization.vehicles is None")
            self.assertTrue(any(v.id == self.vehicle_id for v in org.vehicles), "Vehicle not found in org.vehicles")
            self.assertIsNotNone(org.rides, "Organization.rides is None")
            self.assertTrue(any(r.id == ride.id for r in org.rides), "Ride not found in org.rides")

            refreshed_ride = self._require(db.get(HealthISFRide, ride.id), "Ride not found in DB after assignment")
            self.assertIsNotNone(refreshed_ride.dispatch_logs, "Ride.dispatch_logs is None")
            self.assertGreaterEqual(len(refreshed_ride.dispatch_logs), 2, "Expected at least 2 dispatch logs")
            self.assertIsNotNone(refreshed_ride.status_history, "Ride.status_history is None")
            self.assertGreaterEqual(len(refreshed_ride.status_history), 2, "Expected at least 2 status history entries")

            driver = self._require(db.get(HealthISFDriver, self.driver_id), "Driver not found in DB after assignment")
            vehicle = self._require(db.get(HealthISFVehicle, self.vehicle_id), "Vehicle not found in DB after assignment")
            self.assertEqual(driver.vehicle_id, vehicle.id, "Driver.vehicle_id does not match Vehicle.id")
            vehicle_driver = self._require(vehicle.driver, "Vehicle.driver is None")
            self.assertEqual(vehicle_driver.id, driver.id, "Vehicle.driver.id does not match Driver.id")

        self._with_db(_run)

    def test_lifecycle_validation_create_assign_transition_complete_cancel(self) -> None:
        def _run(db: Session) -> None:
            ride = self._require(self._create_ride(db), "Failed to create ride")
            self.assertEqual(RideStatus(ride.status), RideStatus.PENDING)

            ride = self._require(
                health_service.assign_driver_to_ride(db, ride.id, self.driver_id, actor_user_id=self.user_id),
                "Failed to assign driver to ride",
            )
            self.assertEqual(RideStatus(ride.status), RideStatus.ACCEPTED)
            self.assertEqual(ride.driver_id, self.driver_id)

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.ACCEPTED.value, actor_user_id=self.user_id),
                "Failed to normalize to ASSIGNED",
            )

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.DRIVER_EN_ROUTE.value, actor_user_id=self.user_id),
                "Failed to update to DRIVER_EN_ROUTE",
            )
            self.assertIn(str(ride.lifecycle_state), {RideStatus.DRIVER_EN_ROUTE.value, RideStatus.ASSIGNED.value})

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.ARRIVED.value, actor_user_id=self.user_id),
                "Failed to update to ARRIVED",
            )
            self.assertEqual(str(ride.lifecycle_state), RideStatus.ARRIVED.value)

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.RIDER_ONBOARD.value, actor_user_id=self.user_id),
                "Failed to update to RIDER_ONBOARD",
            )
            self.assertEqual(str(ride.lifecycle_state), RideStatus.RIDER_ONBOARD.value)

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.IN_TRANSIT.value, actor_user_id=self.user_id),
                "Failed to update to IN_TRANSIT",
            )
            self.assertIn(RideStatus(ride.status), {RideStatus.IN_TRANSIT, RideStatus.IN_PROGRESS})

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.COMPLETED.value, actor_user_id=self.user_id),
                "Failed to update to COMPLETED",
            )
            self.assertEqual(RideStatus(ride.status), RideStatus.COMPLETED)
            self.assertIsNotNone(ride.completed_at)

            ride2 = self._create_ride(db)
            with self.assertRaises(ValueError):
                health_service.update_ride_status(db, ride2.id, RideStatus.CANCELLED.value, actor_user_id=self.user_id)

            ride3 = self._create_ride(db)
            with self.assertRaises(ValueError):
                health_service.update_ride_status(db, ride3.id, RideStatus.COMPLETED.value, actor_user_id=self.user_id)

        self._with_db(_run)

    def test_foreign_key_enforcement_and_orphan_history_rejection(self) -> None:
        def _run(db: Session) -> None:
            ride = HealthISFRide(
                id=uuid4(),
                organization_id=self.org_id,
                provider_id="missing-provider",
                driver_id=None,
                passenger_name="Bad Provider",
                passenger_phone="555-000-0001",
                pickup_address="A",
                dropoff_address="B",
                service_type="medical",
                status=RideStatus.PENDING,
                requested_at=now(),
                created_at=now(),
                updated_at=now(),
            )
            db.add(ride)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            ride = HealthISFRide(
                id=uuid4(),
                organization_id=self.org_id,
                provider_id=self.provider_id,
                driver_id="missing-driver",
                passenger_name="Bad Driver",
                passenger_phone="555-000-0002",
                pickup_address="A",
                dropoff_address="B",
                service_type="medical",
                status=RideStatus.PENDING,
                requested_at=now(),
                created_at=now(),
                updated_at=now(),
            )
            db.add(ride)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            provider = HealthISFProvider(
                id=uuid4(),
                organization_id="missing-org",
                name="Bad Org Provider",
                address="bad",
                phone="111-000-0000",
                service_type="clinic",
                is_active=True,
            )
            db.add(provider)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            orphan_history = HealthISFRideStatusHistory(
                id=uuid4(),
                ride_id="missing-ride",
                from_status="pending",
                to_status="completed",
                changed_by_user_id=self.user_id,
                created_at=now(),
            )
            db.add(orphan_history)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

        self._with_db(_run)

    def test_cascade_behavior_and_audit_reference_survival(self) -> None:
        def _run(db: Session) -> None:
            ride = self._create_ride(db, actor=self.user_id)
            ride = self._require(
                health_service.assign_driver_to_ride(db, ride.id, self.driver_id, actor_user_id=self.user_id),
                "Failed to assign ride in cascade test",
            )
            health_service.update_ride_status(db, ride.id, RideStatus.ACCEPTED.value, actor_user_id=self.user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride.id, RideStatus.DRIVER_EN_ROUTE.value, actor_user_id=self.user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride.id, RideStatus.ARRIVED.value, actor_user_id=self.user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride.id, RideStatus.RIDER_ONBOARD.value, actor_user_id=self.user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride.id, RideStatus.IN_TRANSIT.value, actor_user_id=self.user_id)

            log_count_before = self._count(db, HealthISFDispatchLog)
            history_count_before = self._count(db, HealthISFRideStatusHistory)
            self.assertGreater(log_count_before, 0)
            self.assertGreater(history_count_before, 0)

            ride_for_delete = self._require(db.get(HealthISFRide, ride.id), "Ride to delete not found")
            db.delete(ride_for_delete)
            db.commit()

            self.assertLess(self._count(db, HealthISFDispatchLog), log_count_before)
            self.assertLess(self._count(db, HealthISFRideStatusHistory), history_count_before)

            ride2_vehicle_id = uuid4()
            ride2_driver_id = uuid4()
            db.add(HealthISFVehicle(
                id=ride2_vehicle_id,
                organization_id=self.org_id,
                vehicle_type="van",
                vehicle_plate=f"R2-{ride2_driver_id[:8]}",
                capacity=4,
                is_active=True,
            ))
            db.add(HealthISFDriver(
                id=ride2_driver_id,
                organization_id=self.org_id,
                vehicle_id=ride2_vehicle_id,
                name=f"Ride2 Driver {ride2_driver_id[:6]}",
                phone=f"333-555-{ride2_driver_id.replace('-', '')[:4]}",
                vehicle_type="van",
                vehicle_plate=f"R2D-{ride2_driver_id[:6]}",
                status=DriverStatus.AVAILABLE,
                is_active=True,
                total_trips=0,
                rating=4.7,
            ))
            ride2_user_id = uuid4()
            db.add(User(
                id=ride2_user_id,
                email=f"ride2-{ride2_user_id[:8]}@test.local",
                hashed_password="pbkdf2$260000$testsalt$testhash",
                role="dispatcher",
                organization_name="Test Org",
                organization_id=self.org_id,
                is_active=True,
                is_verified=True,
            ))
            db.commit()

            ride2 = self._create_ride(db, actor=ride2_user_id)
            health_service.assign_driver_to_ride(db, ride2.id, ride2_driver_id, actor_user_id=ride2_user_id)
            health_service.update_ride_status(db, ride2.id, RideStatus.ACCEPTED.value, actor_user_id=ride2_user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride2.id, RideStatus.DRIVER_EN_ROUTE.value, actor_user_id=ride2_user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride2.id, RideStatus.ARRIVED.value, actor_user_id=ride2_user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride2.id, RideStatus.RIDER_ONBOARD.value, actor_user_id=ride2_user_id)
            time.sleep(0.01)
            health_service.update_ride_status(db, ride2.id, RideStatus.IN_TRANSIT.value, actor_user_id=ride2_user_id)
            ride2_id = ride2.id

            user = db.get(User, ride2_user_id)
            db.delete(user)
            db.commit()

            ride2_refreshed = self._require(db.get(HealthISFRide, ride2_id), "Ride2 not found after user delete")
            self.assertIsNone(ride2_refreshed.created_by_user_id)
            self.assertIsNone(ride2_refreshed.assigned_by_user_id)
            self.assertIsNone(ride2_refreshed.last_status_changed_by_user_id)

            logs = db.query(HealthISFDispatchLog).filter(HealthISFDispatchLog.ride_id == ride2_id).all()
            history = db.query(HealthISFRideStatusHistory).filter(HealthISFRideStatusHistory.ride_id == ride2_id).all()
            self.assertTrue(all(item.acted_by_user_id is None for item in logs))
            self.assertTrue(all(item.changed_by_user_id is None for item in history))

        self._with_db(_run)

    def test_delete_organization_cascades_owned_entities(self) -> None:
        def _run(db: Session) -> None:
            org_id = uuid4()
            provider_id = uuid4()
            vehicle_id = uuid4()
            driver_id = uuid4()

            db.add(HealthISFOrganization(id=org_id, name="Cascade Org", code=f"CASCADE-{org_id[:8]}", is_active=True))
            db.add(HealthISFProvider(
                id=provider_id,
                organization_id=org_id,
                name="Cascade Provider",
                address="Cascade Addr",
                phone="555-100-1000",
                service_type="clinic",
                is_active=True,
            ))
            db.add(HealthISFVehicle(
                id=vehicle_id,
                organization_id=org_id,
                vehicle_type="sedan",
                vehicle_plate=f"CAS-{org_id[:5]}",
                capacity=4,
                is_active=True,
            ))
            db.add(HealthISFDriver(
                id=driver_id,
                organization_id=org_id,
                vehicle_id=vehicle_id,
                name="Cascade Driver",
                phone=f"555-200-{org_id[:4]}",
                vehicle_type="sedan",
                vehicle_plate=f"DRV-{org_id[:5]}",
                status=DriverStatus.AVAILABLE,
                is_active=True,
                total_trips=0,
                rating=5.0,
            ))
            db.commit()

            ride = health_service.create_ride(
                db,
                passenger_name="Cascade Ride",
                passenger_phone="555-300-3000",
                pickup_address="X",
                dropoff_address="Y",
                service_type="transport",
                provider_id=provider_id,
                organization_id=org_id,
                actor_user_id=None,
            )
            health_service.assign_driver_to_ride(db, ride.id, driver_id, actor_user_id=None)

            db.delete(db.get(HealthISFOrganization, org_id))
            db.commit()

            self.assertIsNone(db.get(HealthISFOrganization, org_id))
            self.assertIsNone(db.get(HealthISFProvider, provider_id))
            self.assertIsNone(db.get(HealthISFVehicle, vehicle_id))
            self.assertIsNone(db.get(HealthISFDriver, driver_id))
            self.assertIsNone(db.get(HealthISFRide, ride.id))

        self._with_db(_run)

    def test_audit_population_and_timestamps(self) -> None:
        def _run(db: Session) -> None:
            user_id = uuid4()
            db.add(User(
                id=user_id,
                email="audit@test.local",
                hashed_password="pbkdf2$260000$testsalt$testhash",
                role="dispatcher",
                organization_name="Test Org",
                organization_id=self.org_id,
                is_active=True,
                is_verified=True,
            ))
            db.commit()

            ride = health_service.create_ride(
                db,
                passenger_name="Audit Patient",
                passenger_phone="444-444-4444",
                pickup_address="Audit A",
                dropoff_address="Audit B",
                service_type="medical",
                provider_id=self.provider_id,
                organization_id=self.org_id,
                actor_user_id=user_id,
            )
            self.assertEqual(ride.created_by_user_id, user_id)
            self.assertIsNotNone(ride.created_at)
            self.assertIsNotNone(ride.updated_at)

            ride = self._require(
                health_service.assign_driver_to_ride(db, ride.id, self.driver_id, actor_user_id=user_id),
                "Failed to assign ride for audit assertions",
            )
            self.assertEqual(ride.assigned_by_user_id, user_id)

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.ACCEPTED.value, actor_user_id=user_id),
                "Failed to normalize ride to ASSIGNED for audit assertions",
            )

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.DRIVER_EN_ROUTE.value, actor_user_id=user_id),
                "Failed to update ride to DRIVER_EN_ROUTE for audit assertions",
            )

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.ARRIVED.value, actor_user_id=user_id),
                "Failed to update ride to ARRIVED for audit assertions",
            )

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.RIDER_ONBOARD.value, actor_user_id=user_id),
                "Failed to update ride to RIDER_ONBOARD for audit assertions",
            )

            ride = self._require(
                health_service.update_ride_status(db, ride.id, RideStatus.IN_TRANSIT.value, actor_user_id=user_id),
                "Failed to update ride to IN_TRANSIT for audit assertions",
            )
            self.assertEqual(ride.last_status_changed_by_user_id, user_id)

            history = health_service.get_ride_status_history(db, ride.id)
            self.assertTrue(any(item.changed_by_user_id == user_id for item in history))
            self.assertTrue(all(item.created_at is not None for item in history))

        self._with_db(_run)

    def test_api_persistence_integration_routes(self) -> None:
        create_resp = self.client.post(
            "/api/health-isf/rides",
            json={
                "passenger_name": "API Rider",
                "passenger_phone": "777-777-7777",
                "pickup_address": "1 Start St",
                "dropoff_address": "2 End St",
                "service_type": "medical_appointment",
                "provider_id": self.provider_id,
                "notes": "api test",
            },
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.text)
        ride = create_resp.json()
        ride_id = ride["id"]

        assign_resp = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            json={"driver_id": self.driver_id},
        )
        self.assertEqual(assign_resp.status_code, 200, assign_resp.text)

        history_resp = self.client.get(f"/api/health-isf/rides/{ride_id}/history")
        self.assertEqual(history_resp.status_code, 200, history_resp.text)
        self.assertGreaterEqual(len(history_resp.json()), 2)

        provider_patch = self.client.patch(
            f"/api/health-isf/providers/{self.provider_id}",
            json={"phone": "999-888-7777"},
        )
        self.assertEqual(provider_patch.status_code, 200, provider_patch.text)
        self.assertEqual(provider_patch.json()["phone"], "999-888-7777")

        driver_patch = self.client.patch(
            f"/api/health-isf/drivers/{self.driver_id}",
            json={"status": "available", "rating": 4.9},
        )
        self.assertEqual(driver_patch.status_code, 200, driver_patch.text)
        self.assertEqual(driver_patch.json()["status"], "available")

    def test_transaction_rollbacks_for_partial_failures_and_invalid_assignments(self) -> None:
        def _run(db: Session) -> None:
            ride = self._create_ride(db)
            logs_before = self._count(db, HealthISFDispatchLog)
            history_before = self._count(db, HealthISFRideStatusHistory)

            with self.assertRaises(ValueError):
                health_service.assign_driver_to_ride(db, ride.id, "missing-driver", actor_user_id=self.user_id)

            db.refresh(ride)
            self.assertIsNone(ride.driver_id)
            self.assertEqual(RideStatus(ride.status), RideStatus.PENDING)
            self.assertEqual(self._count(db, HealthISFDispatchLog), logs_before)
            self.assertEqual(self._count(db, HealthISFRideStatusHistory), history_before)

            other_vehicle_id = uuid4()
            other_driver_id = uuid4()
            db.add(HealthISFVehicle(
                id=other_vehicle_id,
                organization_id=self.org2_id,
                vehicle_type="sedan",
                vehicle_plate=f"OTH-{other_vehicle_id[:6]}",
                capacity=4,
                is_active=True,
            ))
            db.add(HealthISFDriver(
                id=other_driver_id,
                organization_id=self.org2_id,
                vehicle_id=other_vehicle_id,
                name="Other Org Driver",
                phone=f"555-700-{other_driver_id[:4]}",
                vehicle_type="sedan",
                vehicle_plate=f"ODR-{other_driver_id[:6]}",
                status=DriverStatus.AVAILABLE,
                is_active=True,
                total_trips=0,
                rating=4.5,
            ))
            db.commit()

            with self.assertRaises(ValueError):
                health_service.assign_driver_to_ride(db, ride.id, other_driver_id, actor_user_id=self.user_id)

            db.refresh(ride)
            self.assertIsNone(ride.driver_id)
            self.assertEqual(RideStatus(ride.status), RideStatus.PENDING)

        self._with_db(_run)

    def test_dashboard_query_budget_avoids_n_plus_one(self) -> None:
        def _run(db: Session) -> None:
            for idx in range(15):
                ride = health_service.create_ride(
                    db,
                    passenger_name=f"Perf {idx}",
                    passenger_phone=f"600-000-{idx:04d}",
                    pickup_address=f"Pickup {idx}",
                    dropoff_address=f"Dropoff {idx}",
                    service_type="medical",
                    provider_id=self.provider_id,
                    organization_id=self.org_id,
                    actor_user_id=self.user_id,
                )
                if idx % 3 == 0:
                    temp_vehicle_id = uuid4()
                    temp_driver_id = uuid4()
                    db.add(HealthISFVehicle(
                        id=temp_vehicle_id,
                        organization_id=self.org_id,
                        vehicle_type="sedan",
                        vehicle_plate=f"QRY-{temp_vehicle_id[:6]}",
                        capacity=4,
                        is_active=True,
                    ))
                    db.add(HealthISFDriver(
                        id=temp_driver_id,
                        organization_id=self.org_id,
                        vehicle_id=temp_vehicle_id,
                        name=f"Perf Driver {idx}",
                        phone=f"700-000-{idx:04d}",
                        vehicle_type="sedan",
                        vehicle_plate=f"QDR-{temp_driver_id[:6]}",
                        status=DriverStatus.AVAILABLE,
                        is_active=True,
                        total_trips=0,
                        rating=4.5,
                    ))
                    db.flush()
                    health_service.assign_driver_to_ride(db, ride.id, temp_driver_id, actor_user_id=self.user_id)

            query_count = 0

            def before_cursor_execute(*_args, **_kwargs):
                nonlocal query_count
                query_count += 1

            event.listen(db.bind, "before_cursor_execute", before_cursor_execute)
            try:
                metrics = health_service.get_dashboard_metrics(db)
            finally:
                event.remove(db.bind, "before_cursor_execute", before_cursor_execute)

            self.assertGreaterEqual(metrics.total_rides, 15)
            self.assertLessEqual(query_count, 6)

        self._with_db(_run)


if __name__ == "__main__":
    unittest.main()
