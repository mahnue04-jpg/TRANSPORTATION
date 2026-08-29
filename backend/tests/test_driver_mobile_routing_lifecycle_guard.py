"""Prove Driver Mobile routing/ETA data cannot break the working ride lifecycle.

These tests lock the current ETA=0 root cause and walk accept → complete with an
isolated route-plan write. They must not change dispatch, scheduling, billing,
payout, or driver-reset behavior.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.driver_mobile_routing import (
    REASON_DRIVER_GPS_UNAVAILABLE,
    REASON_INVALID_ADDRESS,
    REASON_NOMINATIM_UNAVAILABLE,
    apply_lifecycle_routing,
    geocode_address,
    haversine_route,
    routing_snapshot_for_ride,
    safe_apply_lifecycle_routing,
)
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFBillingHandoff,
    HealthISFDriverLocationPing,
    HealthISFProvider,
    HealthISFRide,
    HealthISFRideRoutePlan,
    HealthISFTripFinancialRecord,
    RideStatus,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _disable_intake_auto_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST-ONLY: keep routing-guard assignment deterministic.

    Intake auto-dispatch can bind another seeded driver (Maria) before the
    explicit James assignment/accept path completes. Same isolation pattern as
    Day-2 / Day-4 dispatch contract tests.
    """
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "0")
    monkeypatch.setattr(
        "app.modules.health_isf.service._is_intake_auto_dispatch_enabled",
        lambda db, organization_id: False,
    )
    monkeypatch.setattr(
        "app.modules.health_isf.routes._schedule_customer_request_side_effects",
        lambda **kwargs: None,
    )


@pytest.fixture(autouse=True)
def _reset_driver_routing_test_state() -> None:
    from tests.health_isf_driver_test_helpers import (
        clear_routing_sidecar_test_artifacts,
        drain_org_dispatch_queue,
        reset_scheduling_test_organization,
    )

    org_id = _org_id_for("dispatcher@amicor.local")
    drain_org_dispatch_queue(org_id)
    reset_scheduling_test_organization(org_id)
    clear_routing_sidecar_test_artifacts(org_id)
    yield
    drain_org_dispatch_queue(org_id)
    reset_scheduling_test_organization(org_id)
    clear_routing_sidecar_test_artifacts(org_id)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _accept_assigned_ride(
    client: TestClient,
    *,
    driver_id: str,
    ride_id: str,
    headers: dict[str, str],
):
    from tests.health_isf_driver_test_helpers import close_competing_assignments_for_ride

    close_competing_assignments_for_ride(ride_id, driver_id)
    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text
    close_competing_assignments_for_ride(ride_id, driver_id)
    return accept


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            if not provider.is_active:
                provider.is_active = True
                db.commit()
            return str(provider.id)
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Routing Guard Provider {uuid4()[:6]}",
            address="500 Routing Guard Avenue",
            phone="212-555-0711",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _upsert_isolated_route_plan(
    *,
    organization_id: str,
    ride_id: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
    path_points: list[list[float]] | None,
    duration_minutes: int,
    distance_miles: float,
    map_provider: str,
) -> None:
    """Write HealthISFRideRoutePlan without mutating ride billing estimate fields."""
    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        billing_distance = ride.estimated_distance_miles
        billing_duration = ride.estimated_duration_minutes
        billing_status = str(ride.status)
        billing_lifecycle = str(ride.lifecycle_state)
        billing_driver = ride.driver_id

        route = (
            db.query(HealthISFRideRoutePlan)
            .filter(
                HealthISFRideRoutePlan.ride_id == ride_id,
                HealthISFRideRoutePlan.organization_id == organization_id,
            )
            .first()
        )
        payload = {
            "map_provider": map_provider,
            "origin_latitude": origin[0],
            "origin_longitude": origin[1],
            "destination_latitude": destination[0],
            "destination_longitude": destination[1],
            "estimated_distance_miles": distance_miles,
            "estimated_duration_minutes": duration_minutes,
            "path_points_json": None if path_points is None else str(path_points),
            "updated_at": hs.now(),
        }
        if route is None:
            route = HealthISFRideRoutePlan(
                id=uuid4(),
                organization_id=organization_id,
                ride_id=ride_id,
                route_reference=f"guard_{uuid4().replace('-', '')[:12]}",
                created_at=hs.now(),
                **payload,
            )
            db.add(route)
        else:
            for key, value in payload.items():
                setattr(route, key, value)
        db.commit()

        persisted = hs.get_ride_by_id(db, ride_id)
        assert persisted is not None
        assert persisted.estimated_distance_miles == billing_distance
        assert persisted.estimated_duration_minutes == billing_duration
        assert str(persisted.status) == billing_status
        assert str(persisted.lifecycle_state) == billing_lifecycle
        assert persisted.driver_id == billing_driver


def _clear_isolated_route_plan(*, organization_id: str, ride_id: str) -> None:
    with SessionLocal() as db:
        db.query(HealthISFRideRoutePlan).filter(
            HealthISFRideRoutePlan.organization_id == organization_id,
            HealthISFRideRoutePlan.ride_id == ride_id,
        ).delete(synchronize_session=False)
        db.commit()


def test_missing_duration_returns_null_eta_not_zero() -> None:
    ride = HealthISFRide(
        id=uuid4(),
        organization_id=uuid4(),
        passenger_name="Routing Guard Rider",
        passenger_phone="646-555-0100",
        pickup_address="100 Clinic Ave, New York, NY 10001",
        dropoff_address="200 Hospital Rd, New York, NY 10002",
        service_type="healthcare",
        status=RideStatus.ACCEPTED,
        lifecycle_state="assigned",
        estimated_distance_miles=None,
        estimated_duration_minutes=None,
    )
    assert hs._estimated_eta_minutes(ride) is None
    assert hs._estimated_eta_minutes(None) is None


def test_route_plan_writes_cannot_break_end_to_end_lifecycle(client: TestClient) -> None:
    from tests.health_isf_driver_test_helpers import ensure_ride_assigned_to_driver, prepare_driver

    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = prepare_driver(org_id)

    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = _headers(rider_auth["access_token"])
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = _headers(dispatcher_auth["access_token"])
    admin_auth = _login(client, "admin@amicor.local")
    admin_headers = _headers(admin_auth["access_token"])

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-555-{phone_digits}"

    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Routing Guard Rider {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"100 Clinic Ave {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Hospital Rd {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "routing isolation lifecycle guard",
        },
    )
    assert create.status_code == 201, create.text
    request_row = create.json()
    request_id = request_row["id"]
    ride_id = request_row["ride_id"]

    with SessionLocal() as db:
        persisted = hs.get_ride_by_id(db, ride_id)
        assert persisted is not None
        assert persisted.pickup_address
        assert persisted.dropoff_address
        assert persisted.estimated_duration_minutes in {None, 0}
        assert hs._estimated_eta_minutes(persisted) is None

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text

    ensure_ride_assigned_to_driver(
        client,
        dispatcher_headers=dispatcher_headers,
        admin_headers=admin_headers,
        request_id=request_id,
        ride_id=ride_id,
        driver_id=driver_id,
    )

    _accept_assigned_ride(
        client,
        driver_id=driver_id,
        ride_id=ride_id,
        headers=dispatcher_headers,
    )

    active_after_accept = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride",
        headers=dispatcher_headers,
    )
    assert active_after_accept.status_code == 200, active_after_accept.text
    assert active_after_accept.json().get("eta_minutes") is None

    _upsert_isolated_route_plan(
        organization_id=org_id,
        ride_id=ride_id,
        origin=(40.7580, -73.9855),
        destination=(40.7484, -73.9857),
        path_points=[[40.7580, -73.9855], [40.7530, -73.9856], [40.7484, -73.9857]],
        duration_minutes=9,
        distance_miles=1.4,
        map_provider="osrm_guard",
    )

    still_null = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride",
        headers=dispatcher_headers,
    )
    assert still_null.status_code == 200, still_null.text
    assert still_null.json().get("eta_minutes") is None

    for target_state in (
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
    ):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    _upsert_isolated_route_plan(
        organization_id=org_id,
        ride_id=ride_id,
        origin=(40.7484, -73.9857),
        destination=(40.7306, -73.9352),
        path_points=[[40.7484, -73.9857], [40.7400, -73.9600], [40.7306, -73.9352]],
        duration_minutes=18,
        distance_miles=4.2,
        map_provider="osrm_guard",
    )

    for target_state in (
        "trip_in_progress",
        "arrived_destination",
        "completed",
    ):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride.status_code == 200, ride.text
    assert str(ride.json().get("lifecycle_state") or ride.json().get("status")).lower() == "completed"

    _clear_isolated_route_plan(organization_id=org_id, ride_id=ride_id)

    with SessionLocal() as db:
        persisted = hs.get_ride_by_id(db, ride_id)
        assert persisted is not None
        assert str(persisted.lifecycle_state or persisted.status).lower() == "completed"
        assert db.query(HealthISFRideRoutePlan).filter(HealthISFRideRoutePlan.ride_id == ride_id).count() == 0
        assert db.query(HealthISFTripFinancialRecord).filter(HealthISFTripFinancialRecord.ride_id == ride_id).count() == 1
        assert db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count() == 1

        financial = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=dispatcher_headers)
        assert financial.status_code == 200, financial.text
        financial_body = financial.json()
        assert financial_body["driver_pay_usd"] > 0
        assert financial_body["billing_handoff_id"]
        assert financial_body["billing_handoff_status"] == "ready"

        driver_row = hs.get_driver_by_id(db, driver_id)
        assert driver_row is not None
        assert str(driver_row.status) in {DriverStatus.AVAILABLE.value, str(DriverStatus.AVAILABLE)}
        assert str(driver_row.availability_state or "").lower() == "available"
        assert int(driver_row.total_trips or 0) >= 1


def _fake_geocode(_db, address: str):
    text = str(address or "").lower()
    if "zzz-unknown" in text or "unrecognized" in text:
        return {"error": REASON_INVALID_ADDRESS}
    if "hospital" in text or "dropoff" in text or "destination" in text:
        return {"latitude": 40.7306, "longitude": -73.9352, "provider": "nominatim"}
    return {"latitude": 40.7484, "longitude": -73.9857, "provider": "nominatim"}


def _fake_osrm(origin, destination):
    return {
        "distance_miles": 3.1,
        "duration_minutes": 12,
        "points": [
            [float(origin["latitude"]), float(origin["longitude"])],
            [float(destination["latitude"]), float(destination["longitude"])],
        ],
        "provider": "osrm",
    }


def _insert_gps(*, organization_id: str, driver_id: str, ride_id: str, lat: float, lng: float) -> None:
    with SessionLocal() as db:
        db.add(
            HealthISFDriverLocationPing(
                id=uuid4(),
                organization_id=organization_id,
                driver_id=driver_id,
                ride_id=ride_id,
                latitude=lat,
                longitude=lng,
                source="mobile",
                heartbeat_at=now(),
                created_at=now(),
            )
        )
        db.commit()


def _bootstrap_assigned_ride(client: TestClient) -> dict[str, str]:
    from tests.health_isf_driver_test_helpers import ensure_ride_assigned_to_driver, prepare_driver

    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = prepare_driver(org_id)
    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = _headers(rider_auth["access_token"])
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = _headers(dispatcher_auth["access_token"])
    admin_auth = _login(client, "admin@amicor.local")
    admin_headers = _headers(admin_auth["access_token"])
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Routing Sidecar Rider {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": f"100 Clinic Ave {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Hospital Rd {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "routing sidecar",
        },
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["id"]
    ride_id = create.json()["ride_id"]
    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text
    ensure_ride_assigned_to_driver(
        client,
        dispatcher_headers=dispatcher_headers,
        admin_headers=admin_headers,
        request_id=request_id,
        ride_id=ride_id,
        driver_id=driver_id,
    )
    return {
        "org_id": org_id,
        "driver_id": driver_id,
        "ride_id": ride_id,
        "dispatcher_headers": dispatcher_headers,
    }


def test_haversine_fallback_produces_duration() -> None:
    routed = haversine_route(
        {"latitude": 40.7484, "longitude": -73.9857},
        {"latitude": 40.7306, "longitude": -73.9352},
    )
    assert routed["provider"] == "haversine"
    assert routed["duration_minutes"] >= 1
    assert len(routed["points"]) == 2


def test_geocode_uses_cache_after_first_nominatim_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ROUTING_HTTP", "1")
    calls = {"count": 0}

    def fake_fetch(url: str):
        calls["count"] += 1
        assert "nominatim.openstreetmap.org" in url
        return [{"lat": "40.7580", "lon": "-73.9855", "display_name": "Times Square"}]

    monkeypatch.setattr(
        "app.modules.health_isf.driver_mobile_routing._fetch_json",
        fake_fetch,
    )
    address = f"1 Routing Cache Ave {uuid4()[:8]}, New York, NY"
    with SessionLocal() as db:
        first = geocode_address(db, address)
        second = geocode_address(db, address)
    assert first is not None and first.get("latitude") == 40.7580
    assert second is not None and second.get("cached") is True
    assert calls["count"] == 1


def test_pickup_eta_requires_real_gps_and_does_not_change_billing_estimates(client: TestClient) -> None:
    ctx = _bootstrap_assigned_ride(client)
    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ctx["ride_id"])
        assert ride is not None
        ride.estimated_distance_miles = 9.5
        ride.estimated_duration_minutes = 22
        db.commit()

    with patch("app.modules.health_isf.driver_mobile_routing.geocode_address", side_effect=_fake_geocode), patch(
        "app.modules.health_isf.driver_mobile_routing.route_between", side_effect=_fake_osrm
    ):
        _accept_assigned_ride(
            client,
            driver_id=ctx["driver_id"],
            ride_id=ctx["ride_id"],
            headers=ctx["dispatcher_headers"],
        )
        no_gps = client.get(
            f"/api/health-isf/drivers/{ctx['driver_id']}/active-ride",
            headers=ctx["dispatcher_headers"],
        )
        assert no_gps.status_code == 200
        body = no_gps.json()
        assert body.get("pickup_eta_minutes") is None
        assert body.get("eta_minutes") is None
        assert body.get("eta_unavailable_reason") == REASON_DRIVER_GPS_UNAVAILABLE
        assert body.get("pickup_latitude") == 40.7484
        assert body.get("driver_gps_available") is False

        _insert_gps(
            organization_id=ctx["org_id"],
            driver_id=ctx["driver_id"],
            ride_id=ctx["ride_id"],
            lat=40.7580,
            lng=-73.9855,
        )
        step = client.post(
            f"/api/health-isf/drivers/{ctx['driver_id']}/route-progress",
            headers=ctx["dispatcher_headers"],
            json={"ride_id": ctx["ride_id"], "target_state": "en_route_pickup"},
        )
        assert step.status_code == 200, step.text
        live = step.json()
        assert live.get("route_leg") == "driver_to_pickup"
        assert live.get("pickup_eta_minutes") == 12
        assert live.get("eta_minutes") == 12
        assert live.get("driver_gps_available") is True
        assert live.get("route_polyline")

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ctx["ride_id"])
        assert ride is not None
        assert float(ride.estimated_distance_miles) == 9.5
        assert int(ride.estimated_duration_minutes) == 22


def test_destination_eta_after_rider_loaded(client: TestClient) -> None:
    ctx = _bootstrap_assigned_ride(client)
    with patch("app.modules.health_isf.driver_mobile_routing.geocode_address", side_effect=_fake_geocode), patch(
        "app.modules.health_isf.driver_mobile_routing.route_between", side_effect=_fake_osrm
    ):
        _accept_assigned_ride(
            client,
            driver_id=ctx["driver_id"],
            ride_id=ctx["ride_id"],
            headers=ctx["dispatcher_headers"],
        )
        for target_state in ("en_route_pickup", "arrived_pickup", "rider_loaded"):
            step = client.post(
                f"/api/health-isf/drivers/{ctx['driver_id']}/route-progress",
                headers=ctx["dispatcher_headers"],
                json={"ride_id": ctx["ride_id"], "target_state": target_state},
            )
            assert step.status_code == 200, f"{target_state}: {step.text}"
        loaded = client.get(
            f"/api/health-isf/drivers/{ctx['driver_id']}/active-ride",
            headers=ctx["dispatcher_headers"],
        )
        assert loaded.status_code == 200
        body = loaded.json()
        assert body.get("route_leg") == "pickup_to_destination"
        assert body.get("destination_eta_minutes") == 12
        assert body.get("eta_minutes") == 12
        assert body.get("pickup_latitude") == 40.7484
        assert body.get("dropoff_latitude") == 40.7306


def test_routing_failures_never_block_lifecycle(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _bootstrap_assigned_ride(client)

    def boom(*_args, **_kwargs):
        raise RuntimeError("nominatim down")

    monkeypatch.setattr(
        "app.modules.health_isf.driver_mobile_routing.geocode_address",
        lambda *_args, **_kwargs: {"error": REASON_NOMINATIM_UNAVAILABLE},
    )
    monkeypatch.setattr(
        "app.modules.health_isf.driver_mobile_routing.route_between",
        boom,
    )
    _accept_assigned_ride(
        client,
        driver_id=ctx["driver_id"],
        ride_id=ctx["ride_id"],
        headers=ctx["dispatcher_headers"],
    )
    active = client.get(
        f"/api/health-isf/drivers/{ctx['driver_id']}/active-ride",
        headers=ctx["dispatcher_headers"],
    )
    assert active.status_code == 200
    assert active.json().get("eta_minutes") is None
    assert active.json().get("eta_unavailable_reason") in {REASON_NOMINATIM_UNAVAILABLE, REASON_INVALID_ADDRESS, None}

    monkeypatch.setattr(
        "app.modules.health_isf.driver_mobile_routing.apply_lifecycle_routing",
        boom,
    )
    for target_state in (
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "arrived_destination",
        "completed",
    ):
        step = client.post(
            f"/api/health-isf/drivers/{ctx['driver_id']}/route-progress",
            headers=ctx["dispatcher_headers"],
            json={"ride_id": ctx["ride_id"], "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    ride = client.get(f"/api/health-isf/rides/{ctx['ride_id']}", headers=ctx["dispatcher_headers"])
    assert str(ride.json().get("lifecycle_state") or ride.json().get("status")).lower() == "completed"
    financial = client.get(
        f"/api/health-isf/rides/{ctx['ride_id']}/financial-summary",
        headers=ctx["dispatcher_headers"],
    )
    assert financial.status_code == 200
    assert financial.json()["driver_pay_usd"] > 0


def test_osrm_unavailable_uses_haversine(client: TestClient) -> None:
    ctx = _bootstrap_assigned_ride(client)
    _insert_gps(
        organization_id=ctx["org_id"],
        driver_id=ctx["driver_id"],
        ride_id=ctx["ride_id"],
        lat=40.7580,
        lng=-73.9855,
    )

    def osrm_down(origin, destination):
        fallback = haversine_route(origin, destination)
        fallback["osrm_error"] = "osrm_unavailable"
        return fallback

    with patch("app.modules.health_isf.driver_mobile_routing.geocode_address", side_effect=_fake_geocode), patch(
        "app.modules.health_isf.driver_mobile_routing.route_between", side_effect=osrm_down
    ):
        _accept_assigned_ride(
            client,
            driver_id=ctx["driver_id"],
            ride_id=ctx["ride_id"],
            headers=ctx["dispatcher_headers"],
        )
        live = client.get(
            f"/api/health-isf/drivers/{ctx['driver_id']}/active-ride",
            headers=ctx["dispatcher_headers"],
        ).json()
        assert live.get("pickup_eta_minutes") is not None and live["pickup_eta_minutes"] >= 1
        assert live.get("routing_provider") == "haversine"


def test_invalid_address_keeps_eta_unavailable(client: TestClient) -> None:
    ctx = _bootstrap_assigned_ride(client)
    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ctx["ride_id"])
        assert ride is not None
        ride.pickup_address = "zzz-unknown-place-not-a-real-address"
        db.commit()
    with patch("app.modules.health_isf.driver_mobile_routing.geocode_address", side_effect=_fake_geocode):
        _accept_assigned_ride(
            client,
            driver_id=ctx["driver_id"],
            ride_id=ctx["ride_id"],
            headers=ctx["dispatcher_headers"],
        )
        live = client.get(
            f"/api/health-isf/drivers/{ctx['driver_id']}/active-ride",
            headers=ctx["dispatcher_headers"],
        ).json()
        assert live.get("eta_minutes") is None
        assert live.get("pickup_latitude") is None
        assert live.get("pickup_eta_minutes") is None


def test_arrived_states_may_show_zero_only_after_lifecycle_arrival(client: TestClient) -> None:
    ctx = _bootstrap_assigned_ride(client)
    with SessionLocal() as db:
        db.query(HealthISFDriverLocationPing).filter(
            HealthISFDriverLocationPing.driver_id == ctx["driver_id"]
        ).delete()
        db.commit()
    with patch("app.modules.health_isf.driver_mobile_routing.geocode_address", side_effect=_fake_geocode), patch(
        "app.modules.health_isf.driver_mobile_routing.route_between", side_effect=_fake_osrm
    ):
        _accept_assigned_ride(
            client,
            driver_id=ctx["driver_id"],
            ride_id=ctx["ride_id"],
            headers=ctx["dispatcher_headers"],
        )
        before_arrival = client.get(
            f"/api/health-isf/drivers/{ctx['driver_id']}/active-ride",
            headers=ctx["dispatcher_headers"],
        ).json()
        assert before_arrival.get("pickup_eta_minutes") is None
        assert before_arrival.get("eta_minutes") is None

        en_route = client.post(
            f"/api/health-isf/drivers/{ctx['driver_id']}/route-progress",
            headers=ctx["dispatcher_headers"],
            json={"ride_id": ctx["ride_id"], "target_state": "en_route_pickup"},
        )
        assert en_route.status_code == 200, en_route.text
        assert en_route.json().get("pickup_eta_minutes") is None
        assert en_route.json().get("eta_minutes") is None

        arrived_pickup = client.post(
            f"/api/health-isf/drivers/{ctx['driver_id']}/route-progress",
            headers=ctx["dispatcher_headers"],
            json={"ride_id": ctx["ride_id"], "target_state": "arrived_pickup"},
        )
        assert arrived_pickup.status_code == 200, arrived_pickup.text
        pickup_body = arrived_pickup.json()
        assert pickup_body.get("pickup_eta_minutes") == 0
        assert pickup_body.get("eta_minutes") == 0

        for target_state in ("rider_loaded", "trip_in_progress"):
            step = client.post(
                f"/api/health-isf/drivers/{ctx['driver_id']}/route-progress",
                headers=ctx["dispatcher_headers"],
                json={"ride_id": ctx["ride_id"], "target_state": target_state},
            )
            assert step.status_code == 200, f"{target_state}: {step.text}"

        arrived_destination = client.post(
            f"/api/health-isf/drivers/{ctx['driver_id']}/route-progress",
            headers=ctx["dispatcher_headers"],
            json={"ride_id": ctx["ride_id"], "target_state": "arrived_destination"},
        )
        assert arrived_destination.status_code == 200, arrived_destination.text
        dest_body = arrived_destination.json()
        assert dest_body.get("destination_eta_minutes") == 0
        assert dest_body.get("eta_minutes") == 0


def test_outbound_complete_does_not_clear_return_leg_route(client: TestClient) -> None:
    ctx = _bootstrap_assigned_ride(client)
    return_ride_id = uuid4()
    with SessionLocal() as db:
        outbound = hs.get_ride_by_id(db, ctx["ride_id"])
        assert outbound is not None
        group_id = uuid4()
        outbound.round_trip_group_id = group_id
        outbound.trip_leg = "outbound"
        returning = HealthISFRide(
            id=return_ride_id,
            organization_id=outbound.organization_id,
            provider_id=outbound.provider_id,
            passenger_name=outbound.passenger_name,
            passenger_phone=outbound.passenger_phone,
            pickup_address=outbound.dropoff_address,
            dropoff_address=outbound.pickup_address,
            service_type=outbound.service_type,
            status=RideStatus.ASSIGNED,
            lifecycle_state="assigned",
            round_trip_group_id=group_id,
            trip_leg="return",
        )
        db.add(returning)
        db.commit()

    with patch("app.modules.health_isf.driver_mobile_routing.geocode_address", side_effect=_fake_geocode), patch(
        "app.modules.health_isf.driver_mobile_routing.route_between", side_effect=_fake_osrm
    ):
        with SessionLocal() as db:
            apply_lifecycle_routing(
                db,
                ride_id=ctx["ride_id"],
                driver_id=ctx["driver_id"],
                event="accepted",
            )
            apply_lifecycle_routing(
                db,
                ride_id=return_ride_id,
                driver_id=ctx["driver_id"],
                event="accepted",
            )
            apply_lifecycle_routing(
                db,
                ride_id=ctx["ride_id"],
                driver_id=ctx["driver_id"],
                event="completed",
            )
            outbound_snap = routing_snapshot_for_ride(
                db,
                ride=hs.get_ride_by_id(db, ctx["ride_id"]),
                driver_id=ctx["driver_id"],
            )
            return_snap = routing_snapshot_for_ride(
                db,
                ride=hs.get_ride_by_id(db, return_ride_id),
                driver_id=ctx["driver_id"],
            )
            return_plan = (
                db.query(HealthISFRideRoutePlan)
                .filter(HealthISFRideRoutePlan.ride_id == return_ride_id)
                .first()
            )
        assert outbound_snap.get("eta_minutes") is None
        assert outbound_snap.get("route_polyline") == []
        assert return_plan is not None
        assert return_plan.cleared_at is None
        assert return_snap.get("pickup_latitude") == 40.7306


def test_safe_apply_swallows_routing_exceptions() -> None:
    with patch(
        "app.modules.health_isf.driver_mobile_routing.apply_lifecycle_routing",
        side_effect=RuntimeError("forced"),
    ):
        with SessionLocal() as db:
            snapshot = safe_apply_lifecycle_routing(
                db,
                ride_id="missing",
                driver_id="missing",
                event="accepted",
            )
    assert snapshot.get("eta_minutes") is None
    assert snapshot.get("eta_unavailable_reason") == "routing_failed"

