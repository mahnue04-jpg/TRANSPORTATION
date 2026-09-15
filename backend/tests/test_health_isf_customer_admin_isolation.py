"""Customer ROLE_ADMIN cannot read another organization's Health ISF records."""
from __future__ import annotations

import os
import secrets

from fastapi.testclient import TestClient

from app.auth import (
    ROLE_SUPER_ADMIN_SUPPORT,
    SEED_PASSWORD,
    _serialize_authorized_roles,
    ensure_auth_schema,
    hash_password,
    seed_default_users,
)
from app.core.nova.autonomy.ledger import ensure_autonomy_schema
from app.core.nova.autonomy.v2_worker import WORKER_ENABLED_ENV, env_flag_enabled
from app.core.nova.tenants.provision import DEMO_ORGANIZATION_NAME, DEMO_OWNER_DISPLAY_NAME
from app.core.nova.today.schema_ensure import ensure_nova_today_schema
from app.db.models import User as UserModel
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import (
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFVehicle,
    RideStatus,
    ensure_health_isf_schema,
)

PLATFORM_SUPPORT_EMAIL = "nova.platform.support@amicor.local"
DEFAULT_ORG_CODES = ("AMICOR-DEFAULT", "AMICOR-ISF")


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_health_isf_schema()
    ensure_nova_today_schema(engine)
    ensure_autonomy_schema(engine)
    return TestClient(app)


def _password() -> str:
    return "Nd-" + secrets.token_urlsafe(16)


def _login(client: TestClient, email: str, password: str) -> tuple[dict[str, str], dict]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, response.json()


def _enable_phase1(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_AUTONOMY_PHASE1", "1")
    monkeypatch.delenv(WORKER_ENABLED_ENV, raising=False)
    monkeypatch.delenv("NOVA_AUTONOMY_PHASE2", raising=False)


def _ensure_platform_support() -> None:
    with SessionLocal() as db:
        admin = db.query(UserModel).filter(UserModel.email == "admin@amicor.local").first()
        org_id = admin.organization_id if admin is not None else None
        org_name = admin.organization_name if admin is not None else "Amicor Health"
        existing = db.query(UserModel).filter(UserModel.email == PLATFORM_SUPPORT_EMAIL).first()
        if existing is None:
            db.add(
                UserModel(
                    email=PLATFORM_SUPPORT_EMAIL,
                    hashed_password=hash_password(SEED_PASSWORD),
                    display_name="Nova Platform Support",
                    role=ROLE_SUPER_ADMIN_SUPPORT,
                    authorized_roles=_serialize_authorized_roles((ROLE_SUPER_ADMIN_SUPPORT,)),
                    session_role=ROLE_SUPER_ADMIN_SUPPORT,
                    organization_name=org_name,
                    organization_id=org_id,
                    is_active=True,
                    is_verified=True,
                )
            )
        else:
            existing.role = ROLE_SUPER_ADMIN_SUPPORT
            existing.session_role = ROLE_SUPER_ADMIN_SUPPORT
            existing.authorized_roles = _serialize_authorized_roles((ROLE_SUPER_ADMIN_SUPPORT,))
            existing.hashed_password = hash_password(SEED_PASSWORD)
            existing.is_active = True
        db.commit()


def _operator(client: TestClient) -> dict[str, str]:
    _ensure_platform_support()
    headers, session = _login(client, PLATFORM_SUPPORT_EMAIL, SEED_PASSWORD)
    assert session["role"] == ROLE_SUPER_ADMIN_SUPPORT
    return headers


def _default_org() -> HealthISFOrganization:
    with SessionLocal() as db:
        org = (
            db.query(HealthISFOrganization)
            .filter(HealthISFOrganization.code.in_(DEFAULT_ORG_CODES))
            .first()
        )
        assert org is not None
        db.expunge(org)
        return org


def _seed_health_records(org_id: str) -> dict[str, str]:
    suffix = uuid4()[:8]
    with SessionLocal() as db:
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Health Isolation Clinic {suffix}",
            address="1 Health Way",
            phone=f"212-555-{suffix[:4]}",
            service_type="clinic",
            is_active=True,
        )
        vehicle = HealthISFVehicle(
            id=uuid4(),
            organization_id=org_id,
            vehicle_type="sedan",
            vehicle_plate=f"HI-{suffix[:6]}",
            capacity=4,
            is_active=True,
        )
        db.add(provider)
        db.add(vehicle)
        db.flush()
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            vehicle_id=vehicle.id,
            name=f"Health Isolation Driver {suffix}",
            phone=f"917-555-{suffix[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"HD-{suffix[:6]}",
            is_active=True,
        )
        db.add(driver)
        db.flush()
        ride = HealthISFRide(
            id=uuid4(),
            organization_id=org_id,
            provider_id=provider.id,
            passenger_name=f"Health Isolation Patient {suffix}",
            passenger_phone="555-0199",
            service_type="medical_transport",
            pickup_address="1 Health Pickup",
            dropoff_address="2 Health Drop",
            status=RideStatus.PENDING,
        )
        db.add(ride)
        db.commit()
        return {
            "ride_id": str(ride.id),
            "driver_id": str(driver.id),
            "vehicle_id": str(vehicle.id),
            "provider_id": str(provider.id),
        }


def _org_ids(rows: list[dict]) -> set[str]:
    return {str(row.get("organization_id") or "") for row in rows}


def test_customer_admin_cannot_read_other_org_health_records(monkeypatch) -> None:
    _enable_phase1(monkeypatch)
    client = _client()
    operator = _operator(client)
    password = _password()
    suffix = uuid4()[:8]
    owner_email = f"nova.demo.owner.{suffix}@amicor.local"
    created = client.post(
        "/api/nova/tenants/provision",
        headers=operator,
        json={
            "organization_name": f"{DEMO_ORGANIZATION_NAME} {suffix}",
            "owner_display_name": DEMO_OWNER_DISPLAY_NAME,
            "owner_email": owner_email,
            "owner_password": password,
        },
    )
    assert created.status_code == 200, created.text
    tenant = created.json()
    assert tenant["created"] is True
    demo_org = tenant["organization_id"]
    default_org = _default_org()
    assert demo_org != str(default_org.id)
    seeded = _seed_health_records(str(default_org.id))

    owner_headers, session = _login(client, owner_email, password)
    assert session["role"] == "admin"
    assert session["organization_id"] == demo_org

    own_rides = client.get("/api/health-isf/rides", headers=owner_headers)
    assert own_rides.status_code == 200, own_rides.text
    assert seeded["ride_id"] not in {row["id"] for row in own_rides.json()}
    assert _org_ids(own_rides.json()) <= {"", demo_org}

    own_drivers = client.get("/api/health-isf/drivers", headers=owner_headers)
    assert own_drivers.status_code == 200, own_drivers.text
    assert seeded["driver_id"] not in {row["id"] for row in own_drivers.json()}
    assert _org_ids(own_drivers.json()) <= {"", demo_org}

    own_vehicles = client.get("/api/health-isf/vehicles/active", headers=owner_headers)
    assert own_vehicles.status_code == 200, own_vehicles.text
    assert seeded["vehicle_id"] not in {row["id"] for row in own_vehicles.json()}
    assert _org_ids(own_vehicles.json()) <= {"", demo_org}

    own_providers = client.get("/api/health-isf/providers", headers=owner_headers)
    assert own_providers.status_code == 200, own_providers.text
    assert seeded["provider_id"] not in {row["id"] for row in own_providers.json()}
    assert _org_ids(own_providers.json()) <= {"", demo_org}

    foreign = {"organization_id": str(default_org.id)}
    assert client.get("/api/health-isf/rides", headers=owner_headers, params=foreign).status_code == 403
    assert client.get("/api/health-isf/drivers", headers=owner_headers, params=foreign).status_code == 403
    assert client.get("/api/health-isf/vehicles/active", headers=owner_headers, params=foreign).status_code == 403
    assert client.get("/api/health-isf/providers", headers=owner_headers, params=foreign).status_code == 403
    assert client.get(f"/api/health-isf/rides/{seeded['ride_id']}", headers=owner_headers).status_code == 403
    assert client.get(f"/api/health-isf/drivers/{seeded['driver_id']}", headers=owner_headers).status_code == 403
    assert client.get(f"/api/health-isf/providers/{seeded['provider_id']}", headers=owner_headers).status_code == 403

    health_admin, health_session = _login(client, "admin@amicor.local", SEED_PASSWORD)
    assert health_session["organization_id"] == str(default_org.id)
    assert client.get(f"/api/health-isf/rides/{seeded['ride_id']}", headers=health_admin).status_code == 200
    assert client.get(f"/api/health-isf/drivers/{seeded['driver_id']}", headers=health_admin).status_code == 200
    assert client.get(f"/api/health-isf/providers/{seeded['provider_id']}", headers=health_admin).status_code == 200
    health_vehicles = client.get("/api/health-isf/vehicles/active", headers=health_admin)
    assert health_vehicles.status_code == 200, health_vehicles.text
    assert seeded["vehicle_id"] in {row["id"] for row in health_vehicles.json()}

    support_rides = client.get("/api/health-isf/rides", headers=operator, params=foreign)
    assert support_rides.status_code == 200, support_rides.text
    assert seeded["ride_id"] in {row["id"] for row in support_rides.json()}

    denied = client.post(
        "/api/nova/tenants/provision",
        headers=owner_headers,
        json={
            "organization_name": f"{DEMO_ORGANIZATION_NAME} hijack {suffix}",
            "owner_display_name": DEMO_OWNER_DISPLAY_NAME,
            "owner_email": f"nova.demo.hijack.{suffix}@amicor.local",
            "owner_password": _password(),
        },
    )
    assert denied.status_code == 403
    assert client.post("/api/nova/tenants/provision", json={"owner_password": _password()}).status_code == 401
    staff, _ = _login(client, "dispatcher@amicor.local", SEED_PASSWORD)
    assert client.post(
        "/api/nova/tenants/provision",
        headers=staff,
        json={
            "organization_name": f"{DEMO_ORGANIZATION_NAME} dispatcher {suffix}",
            "owner_display_name": DEMO_OWNER_DISPLAY_NAME,
            "owner_email": f"nova.demo.dispatcher.{suffix}@amicor.local",
            "owner_password": _password(),
        },
    ).status_code == 403

    assert env_flag_enabled(WORKER_ENABLED_ENV) is False
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    send = client.post("/api/nova/today/send", headers=owner_headers)
    assert send.status_code == 403
