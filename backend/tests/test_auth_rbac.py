import unittest
import time

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFProvider


class AuthRbacTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_auth_schema()
        seed_default_users()
        cls.client = TestClient(app)

    def _login(self, email: str) -> dict: # type: ignore
        response = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": SEED_PASSWORD},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _dispatcher_org_id(self) -> str:
        with SessionLocal() as db:
            user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
            if user is None or user.organization_id is None:
                raise AssertionError("dispatcher user organization context missing")
            return str(user.organization_id)

    def _ensure_provider(self, organization_id: str) -> str:
        with SessionLocal() as db:
            existing = (
                db.query(HealthISFProvider)
                .filter(HealthISFProvider.organization_id == organization_id)
                .order_by(HealthISFProvider.created_at.desc())
                .first()
            )
            if existing:
                return str(existing.id)

            provider = HealthISFProvider(
                id=uuid4(),
                organization_id=organization_id,
                name=f"RBAC Provider {uuid4()[:6]}",
                address="100 RBAC Way",
                phone="212-555-7711",
                service_type="clinic",
                is_active=True,
            )
            db.add(provider)
            db.commit()
            return str(provider.id)

    def _ensure_driver(self, organization_id: str) -> str:
        with SessionLocal() as db:
            existing = (
                db.query(HealthISFDriver)
                .filter(HealthISFDriver.organization_id == organization_id)
                .order_by(HealthISFDriver.created_at.desc())
                .first()
            )
            if existing:
                existing.status = DriverStatus.AVAILABLE
                existing.is_active = True
                db.commit()
                return str(existing.id)

            driver = HealthISFDriver(
                id=uuid4(),
                organization_id=organization_id,
                name=f"RBAC Driver {uuid4()[:6]}",
                phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
                vehicle_type="sedan",
                vehicle_plate=f"RBAC-{uuid4()[:5].upper()}",
                status=DriverStatus.AVAILABLE,
                is_active=True,
            )
            db.add(driver)
            db.commit()
            return str(driver.id)

    def test_seeded_admin_login_and_me(self) -> None:
        payload = self._login("admin@amicor.local") # type: ignore
        self.assertEqual(payload.get("role"), "admin") # type: ignore

        me_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer " + payload["access_token"]}, # type: ignore
        )
        self.assertEqual(me_response.status_code, 200, me_response.text)
        me_json = me_response.json()
        self.assertEqual(me_json.get("email"), "admin@amicor.local")
        self.assertEqual(me_json.get("role"), "admin")

    def test_driver_cannot_mutate_health_isf(self) -> None:
        login_payload = self._login("driver@amicor.local") # type: ignore
        headers = {"Authorization": "Bearer " + login_payload["access_token"]} # type: ignore

        rides_response = self.client.get("/api/health-isf/rides", headers=headers) # type: ignore
        self.assertEqual(rides_response.status_code, 200, rides_response.text)
        rides = rides_response.json()
        self.assertTrue(isinstance(rides, list) and len(rides) > 0) # type: ignore

        ride_id = rides[0]["id"] # type: ignore
        mutate_response = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers, # type: ignore
            json={"status": "accepted"},
        )
        self.assertEqual(mutate_response.status_code, 403, mutate_response.text)

    def test_dispatcher_persists_updates_and_history_timeline(self) -> None:
        login_payload = self._login("dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": "Bearer " + login_payload["access_token"]} # type: ignore
        org_id = self._dispatcher_org_id()
        self._ensure_provider(org_id)
        self._ensure_driver(org_id)

        providers_response = self.client.get("/api/health-isf/providers", headers=headers) # type: ignore
        self.assertEqual(providers_response.status_code, 200, providers_response.text)
        providers = providers_response.json()
        self.assertGreater(len(providers), 0)
        provider_id = providers[0]["id"]

        provider_patch = self.client.patch(
            f"/api/health-isf/providers/{provider_id}",
            headers=headers, # type: ignore
            json={"phone": "212-555-7777"},
        )
        self.assertEqual(provider_patch.status_code, 200, provider_patch.text)

        drivers_response = self.client.get("/api/health-isf/drivers", headers=headers) # type: ignore
        self.assertEqual(drivers_response.status_code, 200, drivers_response.text)
        drivers = drivers_response.json()
        self.assertGreater(len(drivers), 0)
        driver_id = drivers[0]["id"]

        driver_patch = self.client.patch(
            f"/api/health-isf/drivers/{driver_id}",
            headers=headers, # type: ignore
            json={"status": "available"},
        )
        self.assertEqual(driver_patch.status_code, 200, driver_patch.text)

        create_response = self.client.post(
            "/api/health-isf/rides",
            headers=headers, # type: ignore
            json={
                "passenger_name": "Timeline Patient",
                "passenger_phone": "212-555-8888",
                "pickup_address": "10 Main St, New York, NY 10001",
                "dropoff_address": "20 Park Ave, New York, NY 10002",
                "service_type": "medical_appointment",
                "provider_id": provider_id,
                "notes": "timeline test",
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        ride = create_response.json()
        ride_id = ride["id"]

        assign_response = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers, # type: ignore
            json={"driver_id": driver_id},
        )
        self.assertEqual(assign_response.status_code, 200, assign_response.text)
        time.sleep(0.01)

        assigned_response = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers, # type: ignore
            json={"status": "accepted"},
        )
        self.assertEqual(assigned_response.status_code, 200, assigned_response.text)
        time.sleep(0.01)

        accept_response = self.client.post(
            f"/api/health-isf/drivers/{driver_id}/accept-ride",
            headers=headers, # type: ignore
            json={"ride_id": ride_id},
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        time.sleep(0.01)

        en_route_response = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers, # type: ignore
            json={"status": "driver_en_route"},
        )
        self.assertEqual(en_route_response.status_code, 200, en_route_response.text)
        time.sleep(0.01)

        arrived_response = self.client.post(
            f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
            headers=headers, # type: ignore
            json={"ride_id": ride_id},
        )
        self.assertEqual(arrived_response.status_code, 200, arrived_response.text)
        time.sleep(0.01)

        onboard_response = self.client.post(
            f"/api/health-isf/drivers/{driver_id}/pickup-complete",
            headers=headers, # type: ignore
            json={"ride_id": ride_id},
        )
        self.assertEqual(onboard_response.status_code, 200, onboard_response.text)
        time.sleep(0.01)

        transit_response = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers, # type: ignore
            json={"status": "in_progress"},
        )
        self.assertEqual(transit_response.status_code, 200, transit_response.text)
        time.sleep(0.01)

        complete_response = self.client.post(
            f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
            headers=headers, # type: ignore
            json={"ride_id": ride_id},
        )
        self.assertEqual(complete_response.status_code, 200, complete_response.text)
        time.sleep(0.01)

        history_response = self.client.get(
            f"/api/health-isf/rides/{ride_id}/history",
            headers=headers, # type: ignore
        )
        self.assertEqual(history_response.status_code, 200, history_response.text)
        history = history_response.json()
        self.assertGreaterEqual(len(history), 3)
        self.assertEqual(history[-1]["to_status"], "completed")


    def test_staff_cannot_switch_to_dispatcher_or_assign(self) -> None:
        login_payload = self._login("staff@amicor.local")
        headers = {"Authorization": "Bearer " + login_payload["access_token"]}

        switch_response = self.client.post(
            "/api/auth/switch-role",
            headers=headers,
            json={"role": "dispatcher"},
        )
        self.assertEqual(switch_response.status_code, 403, switch_response.text)

        org_id = self._dispatcher_org_id()
        provider_id = self._ensure_provider(org_id)
        driver_id = self._ensure_driver(org_id)
        create_response = self.client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "passenger_name": "Staff RBAC Patient",
                "passenger_phone": "212-555-4411",
                "pickup_address": "10 Main St, New York, NY 10001",
                "dropoff_address": "20 Park Ave, New York, NY 10002",
                "service_type": "medical_appointment",
                "provider_id": provider_id,
                "notes": "staff rbac test",
            },
        )
        self.assertEqual(create_response.status_code, 403, create_response.text)

        dispatcher_login = self._login("dispatcher@amicor.local")
        dispatcher_headers = {"Authorization": "Bearer " + dispatcher_login["access_token"]}
        create_response = self.client.post(
            "/api/health-isf/rides",
            headers=dispatcher_headers,
            json={
                "passenger_name": "Staff RBAC Patient",
                "passenger_phone": "212-555-4412",
                "pickup_address": "10 Main St, New York, NY 10001",
                "dropoff_address": "20 Park Ave, New York, NY 10002",
                "service_type": "medical_appointment",
                "provider_id": provider_id,
                "notes": "staff rbac test",
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        ride_id = create_response.json()["id"]
        assign_response = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        )
        self.assertEqual(assign_response.status_code, 403, assign_response.text)

    def test_admin_can_switch_role_and_assign_driver(self) -> None:
        login_payload = self._login("admin@amicor.local")
        headers = {"Authorization": "Bearer " + login_payload["access_token"]}

        switch_response = self.client.post(
            "/api/auth/switch-role",
            headers=headers,
            json={"role": "dispatcher"},
        )
        self.assertEqual(switch_response.status_code, 200, switch_response.text)
        switch_json = switch_response.json()
        self.assertEqual(switch_json.get("role"), "dispatcher")
        self.assertEqual(switch_json.get("token_role"), "dispatcher")
        dispatcher_headers = {"Authorization": "Bearer " + switch_json["access_token"]}

        session_response = self.client.get("/api/auth/session", headers=dispatcher_headers)
        self.assertEqual(session_response.status_code, 200, session_response.text)
        session_json = session_response.json()
        self.assertEqual(session_json.get("token_role"), "dispatcher")

        org_id = self._dispatcher_org_id()
        provider_id = self._ensure_provider(org_id)
        driver_id = self._ensure_driver(org_id)
        create_response = self.client.post(
            "/api/health-isf/rides",
            headers=dispatcher_headers,
            json={
                "passenger_name": "Switch RBAC Patient",
                "passenger_phone": "212-555-4422",
                "pickup_address": "10 Main St, New York, NY 10001",
                "dropoff_address": "20 Park Ave, New York, NY 10002",
                "service_type": "medical_appointment",
                "provider_id": provider_id,
                "notes": "switch rbac test",
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        ride_id = create_response.json()["id"]
        ride_lookup = self.client.get(
            f"/api/health-isf/rides/{ride_id}",
            headers=dispatcher_headers,
        )
        self.assertEqual(ride_lookup.status_code, 200, ride_lookup.text)
        ride_row = ride_lookup.json()
        if not ride_row.get("driver_id"):
            assign_response = self.client.patch(
                f"/api/health-isf/rides/{ride_id}/assign-driver",
                headers=dispatcher_headers,
                json={"driver_id": driver_id},
            )
            self.assertEqual(assign_response.status_code, 200, assign_response.text)
            assigned = assign_response.json()
            self.assertEqual(str(assigned.get("driver_id")), str(driver_id))
        else:
            self.assertTrue(str(ride_row.get("driver_id")))


if __name__ == "__main__":
    unittest.main()
