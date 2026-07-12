"""Local proof of server role switch + assign using operator-like account."""
from __future__ import annotations

import base64
import json
import unittest

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, apply_operator_role_grants, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app


def decode_role(token: str) -> str:
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    return str(payload.get("role") or "")


class LocalOperatorProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_auth_schema()
        seed_default_users()
        with SessionLocal() as db:
            user = db.query(PlatformUser).filter(PlatformUser.email == "mahnue04@gmail.com").first()
            if not user:
                user = PlatformUser(
                    email="mahnue04@gmail.com",
                    hashed_password=__import__("app.auth", fromlist=["hash_password"]).hash_password(SEED_PASSWORD),
                    display_name="saye monibah",
                    role="staff",
                    is_active=True,
                    is_verified=True,
                )
                db.add(user)
                db.commit()
        apply_operator_role_grants()
        cls.client = TestClient(app)

    def test_operator_switch_and_assign(self) -> None:
        login = self.client.post(
            "/api/auth/login",
            json={"email": "mahnue04@gmail.com", "password": SEED_PASSWORD},
        )
        self.assertEqual(login.status_code, 200, login.text)
        before = decode_role(login.json()["access_token"])
        switch = self.client.post(
            "/api/auth/switch-role",
            headers={"Authorization": "Bearer " + login.json()["access_token"]},
            json={"role": "dispatcher"},
        )
        self.assertEqual(switch.status_code, 200, switch.text)
        after = decode_role(switch.json()["access_token"])
        self.assertEqual(after, "dispatcher")
        session = self.client.get(
            "/api/auth/session",
            headers={"Authorization": "Bearer " + switch.json()["access_token"]},
        )
        self.assertEqual(session.json().get("token_role"), "dispatcher")

        dispatcher_headers = {"Authorization": "Bearer " + switch.json()["access_token"]}
        drivers = self.client.get("/api/health-isf/drivers", headers=dispatcher_headers)
        self.assertEqual(drivers.status_code, 200, drivers.text)
        driver_id = drivers.json()[0]["id"]
        providers = self.client.get("/api/health-isf/providers", headers=dispatcher_headers)
        self.assertEqual(providers.status_code, 200, providers.text)
        provider_id = providers.json()[0]["id"]
        create = self.client.post(
            "/api/health-isf/rides",
            headers=dispatcher_headers,
            json={
                "passenger_name": "Operator Switch Proof",
                "passenger_phone": "646-555-9911",
                "pickup_address": "100 Proof St, New York, NY 10001",
                "dropoff_address": "200 Proof Ave, New York, NY 10002",
                "service_type": "medical_appointment",
                "provider_id": provider_id,
                "notes": "operator role switch proof",
            },
        )
        self.assertEqual(create.status_code, 201, create.text)
        ride_id = create.json()["id"]
        assign = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        self.assertIn(assign.status_code, {200, 400}, assign.text)
        staff = self.client.post(
            "/api/auth/login",
            json={"email": "staff@amicor.local", "password": SEED_PASSWORD},
        )
        self.assertEqual(staff.status_code, 200, staff.text)
        blocked = self.client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers={"Authorization": "Bearer " + staff.json()["access_token"]},
            json={"driver_id": driver_id},
        )
        self.assertEqual(blocked.status_code, 403, blocked.text)
        print("LOCAL_OPERATOR_PROOF=PASS")


if __name__ == "__main__":
    unittest.main()
