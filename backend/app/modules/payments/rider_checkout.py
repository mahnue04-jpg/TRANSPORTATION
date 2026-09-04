"""Rider fare quote and sandbox PaymentIntent checkout.

Uses TripFinancialEngine.calculate_breakdown() and ProductionTransportOps
route-plan math. Creates sandbox PaymentIntents only. Never exposes secret keys.
Does not start driver payouts or alter completed-trip settlement math.
"""
from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.financial_engine import (
    PRICING_VERSION,
    TripFinancialEngine,
)
from app.modules.health_isf.models import (
    CustomerRequestStatus,
    HealthISFCustomerRideRequest,
    HealthISFPaymentTransaction,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.production_transport_ops import (
    ProductionTransportOps,
    _haversine_miles,
)
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager
from app.modules.payments.models import (
    PAYMENT_FAILED,
    PAYMENT_PENDING,
    PAYMENT_SUCCEEDED,
    PAYOUT_NOT_STARTED,
    SERVICE_RIDE,
    AmicorCustomerPayment,
)
from app.modules.payments.stripe_payments import amount_major_from_minor

logger = logging.getLogger("amicor.payments.rider_checkout")

SANDBOX_NOTICE = "This is the amount to be charged in the current sandbox test."
DEFAULT_TRAFFIC_MODE = "normal"

_CLIENT_OVERRIDE: "StripePaymentIntentClient | None" = None


class StripePaymentIntentClient(Protocol):
    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        ...


def stripe_secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def stripe_publishable_key() -> str:
    return os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()


def is_live_stripe_key(secret: str) -> bool:
    raw = str(secret or "").strip()
    return raw.startswith("sk_live_") or raw.startswith("rk_live_")


def set_stripe_payment_client_override(client: StripePaymentIntentClient | None) -> None:
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def get_stripe_payment_client() -> StripePaymentIntentClient | None:
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    secret = stripe_secret_key()
    if not secret:
        return None
    if is_live_stripe_key(secret):
        raise ValueError("Live Stripe keys are not allowed for rider checkout. Use a sandbox key.")
    return LiveStripePaymentIntentClient(api_key=secret)


class LiveStripePaymentIntentClient:
    def __init__(self, *, api_key: str):
        self.api_key = api_key

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        from stripe import StripeClient

        client = StripeClient(self.api_key)
        created = client.v1.payment_intents.create(
            {
                "amount": int(amount_minor),
                "currency": currency,
                "automatic_payment_methods": {"enabled": True},
                "metadata": metadata,
            }
        )
        payload = created if isinstance(created, dict) else getattr(created, "to_dict", lambda: {})()
        if not isinstance(payload, dict):
            payload = {
                "id": getattr(created, "id", None),
                "client_secret": getattr(created, "client_secret", None),
                "status": getattr(created, "status", None),
            }
        return payload


class FakeStripePaymentIntentClient:
    def __init__(self) -> None:
        self.created_count = 0
        self.last_metadata: dict[str, str] = {}

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        self.created_count += 1
        self.last_metadata = dict(metadata)
        intent_id = f"pi_test_{self.created_count}_{uuid4()[:12]}"
        return {
            "id": intent_id,
            "client_secret": f"{intent_id}_secret_test",
            "status": "requires_payment_method",
            "amount": int(amount_minor),
            "currency": currency,
            "metadata": dict(metadata),
        }


def _require_distinct_addresses(pickup_address: str, dropoff_address: str) -> tuple[str, str]:
    pickup = str(pickup_address or "").strip()
    dropoff = str(dropoff_address or "").strip()
    if not pickup or not dropoff:
        raise ValueError("Pickup and drop-off addresses are required to estimate a fare.")
    if pickup.lower() == dropoff.lower():
        raise ValueError("Pickup and drop-off must be different addresses.")
    return pickup, dropoff


def estimate_route_plan(
    db: Session,
    *,
    pickup_address: str,
    dropoff_address: str,
    pickup_latitude: float | None = None,
    pickup_longitude: float | None = None,
    dropoff_latitude: float | None = None,
    dropoff_longitude: float | None = None,
    traffic_mode: str = DEFAULT_TRAFFIC_MODE,
) -> dict[str, Any]:
    pickup, dropoff = _require_distinct_addresses(pickup_address, dropoff_address)
    origin_lat = pickup_latitude
    origin_lng = pickup_longitude
    dest_lat = dropoff_latitude
    dest_lng = dropoff_longitude
    source = "provided_coordinates"

    if origin_lat is None or origin_lng is None or dest_lat is None or dest_lng is None:
        from app.modules.health_isf.driver_mobile_routing import geocode_address

        pickup_geo = geocode_address(db, pickup) if origin_lat is None or origin_lng is None else None
        dropoff_geo = geocode_address(db, dropoff) if dest_lat is None or dest_lng is None else None
        if pickup_geo and pickup_geo.get("error"):
            raise ValueError("Pickup address could not be mapped. Enter a more complete street address.")
        if dropoff_geo and dropoff_geo.get("error"):
            raise ValueError("Drop-off address could not be mapped. Enter a more complete street address.")
        if not pickup_geo or pickup_geo.get("latitude") is None:
            raise ValueError("Pickup address could not be mapped. Enter a more complete street address.")
        if not dropoff_geo or dropoff_geo.get("latitude") is None:
            raise ValueError("Drop-off address could not be mapped. Enter a more complete street address.")
        origin_lat = float(pickup_geo["latitude"])
        origin_lng = float(pickup_geo["longitude"])
        dest_lat = float(dropoff_geo["latitude"])
        dest_lng = float(dropoff_geo["longitude"])
        source = str(pickup_geo.get("provider") or dropoff_geo.get("provider") or "nominatim")

    multiplier = ProductionTransportOps.TRAFFIC_MULTIPLIER.get(str(traffic_mode).lower(), 1.15)
    distance_miles = _haversine_miles(
        float(origin_lat),
        float(origin_lng),
        float(dest_lat),
        float(dest_lng),
    )
    estimated_distance_miles = max(0.1, distance_miles * multiplier)
    estimated_duration_minutes = max(2, int(round((estimated_distance_miles / 27.0) * 60)))
    return {
        "pickup_address": pickup,
        "dropoff_address": dropoff,
        "pickup_latitude": float(origin_lat),
        "pickup_longitude": float(origin_lng),
        "dropoff_latitude": float(dest_lat),
        "dropoff_longitude": float(dest_lng),
        "estimated_distance_miles": round(float(estimated_distance_miles), 2),
        "estimated_duration_minutes": int(estimated_duration_minutes),
        "traffic_multiplier": multiplier,
        "route_source": source,
        "map_provider": "haversine",
    }


def quote_rider_fare(
    db: Session,
    *,
    pickup_address: str,
    dropoff_address: str,
    ride_type: str = "healthcare",
    pickup_latitude: float | None = None,
    pickup_longitude: float | None = None,
    dropoff_latitude: float | None = None,
    dropoff_longitude: float | None = None,
) -> dict[str, Any]:
    route = estimate_route_plan(
        db,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        pickup_latitude=pickup_latitude,
        pickup_longitude=pickup_longitude,
        dropoff_latitude=dropoff_latitude,
        dropoff_longitude=dropoff_longitude,
    )
    ride_proxy = SimpleNamespace(
        estimated_distance_miles=route["estimated_distance_miles"],
        estimated_duration_minutes=route["estimated_duration_minutes"],
        service_type=str(ride_type or "healthcare"),
    )
    request_proxy = SimpleNamespace(ride_type=str(ride_type or "healthcare"))
    breakdown = TripFinancialEngine.calculate_breakdown(ride_proxy, request_row=request_proxy)
    amount_minor = max(0, int(round(float(breakdown.ride_price_usd) * 100)))
    return {
        "pickup_address": route["pickup_address"],
        "dropoff_address": route["dropoff_address"],
        "estimated_distance_miles": route["estimated_distance_miles"],
        "estimated_duration_minutes": route["estimated_duration_minutes"],
        "estimated_ride_fare_usd": breakdown.ride_price_usd,
        "amount_minor": amount_minor,
        "currency": "usd",
        "pricing_version": PRICING_VERSION,
        "sandbox": True,
        "sandbox_notice": SANDBOX_NOTICE,
        "route_source": route["route_source"],
        "map_provider": route["map_provider"],
        "pickup_latitude": route["pickup_latitude"],
        "pickup_longitude": route["pickup_longitude"],
        "dropoff_latitude": route["dropoff_latitude"],
        "dropoff_longitude": route["dropoff_longitude"],
        "is_healthcare": breakdown.is_healthcare,
    }


def ride_is_awaiting_payment(
    ride: HealthISFRide | None,
    request_row: HealthISFCustomerRideRequest | None = None,
) -> bool:
    if ride is not None:
        lifecycle = str(getattr(ride, "lifecycle_state", "") or "").strip().lower()
        if lifecycle == RideStatus.AWAITING_PAYMENT.value:
            return True
    if request_row is not None:
        status = str(getattr(request_row, "dispatch_status", "") or "").strip().lower()
        if status == CustomerRequestStatus.AWAITING_PAYMENT.value:
            return True
    return False


def _get_payment_for_ride(db: Session, ride_id: str) -> AmicorCustomerPayment | None:
    return (
        db.query(AmicorCustomerPayment)
        .filter(AmicorCustomerPayment.ride_id == ride_id)
        .order_by(AmicorCustomerPayment.created_at.desc())
        .first()
    )


def create_rider_checkout(
    db: Session,
    *,
    organization_id: str,
    user_id: str | None,
    rider_name: str,
    rider_phone: str,
    pickup_address: str,
    dropoff_address: str,
    ride_type: str = "healthcare",
    notes: str | None = None,
    scheduled_time=None,
    trip_type: str = "one_way",
    pickup_latitude: float | None = None,
    pickup_longitude: float | None = None,
    dropoff_latitude: float | None = None,
    dropoff_longitude: float | None = None,
    extra_request_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = get_stripe_payment_client()
    if client is None:
        raise ValueError("Stripe sandbox payment is not configured yet.")

    quote = quote_rider_fare(
        db,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        ride_type=ride_type,
        pickup_latitude=pickup_latitude,
        pickup_longitude=pickup_longitude,
        dropoff_latitude=dropoff_latitude,
        dropoff_longitude=dropoff_longitude,
    )

    from app.modules.health_isf import service as onboarding_service

    request_kwargs = dict(extra_request_kwargs or {})
    request_row, ride = onboarding_service.create_customer_ride_request(
        db,
        organization_id=organization_id,
        rider_name=rider_name,
        rider_phone=rider_phone,
        pickup_address=quote["pickup_address"],
        dropoff_address=quote["dropoff_address"],
        scheduled_time=scheduled_time,
        ride_type=ride_type,
        recurring=bool(request_kwargs.pop("recurring", False)),
        recurring_pattern=request_kwargs.pop("recurring_pattern", None),
        notes=notes,
        submitted_by_user_id=user_id,
        trip_type=trip_type,
        hold_for_payment=True,
        estimated_distance_miles=quote["estimated_distance_miles"],
        estimated_duration_minutes=quote["estimated_duration_minutes"],
        **request_kwargs,
    )

    metadata = {
        "service_type": SERVICE_RIDE,
        "ride_id": str(ride.id),
        "request_id": str(request_row.id),
        "internal_service_id": str(ride.id),
        "organization_id": str(organization_id),
        "pricing_version": PRICING_VERSION,
        "sandbox": "true",
    }
    intent = client.create_payment_intent(
        amount_minor=int(quote["amount_minor"]),
        currency="usd",
        metadata=metadata,
    )
    intent_id = str(intent.get("id") or "").strip()
    client_secret = str(intent.get("client_secret") or "").strip()
    if not intent_id or not client_secret:
        raise ValueError("Stripe did not return a sandbox PaymentIntent.")

    payment = AmicorCustomerPayment(
        id=uuid4(),
        service_type=SERVICE_RIDE,
        internal_service_id=str(ride.id),
        ride_id=str(ride.id),
        organization_id=str(organization_id),
        customer_id=user_id,
        pricing_version=PRICING_VERSION,
        stripe_payment_intent_id=intent_id,
        currency="usd",
        amount_minor=int(quote["amount_minor"]),
        payment_status=PAYMENT_PENDING,
        payout_status=PAYOUT_NOT_STARTED,
        created_at=now(),
        updated_at=now(),
    )
    db.add(payment)

    tx = HealthISFPaymentTransaction(
        id=uuid4(),
        organization_id=organization_id,
        ride_id=ride.id,
        driver_id=ride.driver_id,
        provider_id=ride.provider_id,
        gateway="stripe",
        gateway_payment_intent_id=intent_id,
        status="requires_payment_method",
        currency="usd",
        amount_usd=quote["estimated_ride_fare_usd"],
        tip_amount_usd=0.0,
        surcharge_usd=0.0,
        processing_fee_usd=0.0,
        settlement_status="pending",
        invoice_reference=f"RIDE-{str(ride.id)[:8].upper()}",
        created_by_user_id=user_id,
        created_at=now(),
        updated_at=now(),
    )
    db.add(tx)
    payment.health_isf_payment_transaction_id = tx.id
    db.commit()
    db.refresh(request_row)
    db.refresh(ride)

    publishable = stripe_publishable_key()
    return {
        **quote,
        "request_id": str(request_row.id),
        "ride_id": str(ride.id),
        "dispatch_status": request_row.dispatch_status,
        "lifecycle_state": getattr(ride, "lifecycle_state", None),
        "payment_status": PAYMENT_PENDING,
        "stripe_payment_intent_id": intent_id,
        "client_secret": client_secret,
        "publishable_key": publishable,
        "held_for_payment": True,
    }


def rider_payment_status(db: Session, *, request_id: str, organization_id: str) -> dict[str, Any]:
    request_row = (
        db.query(HealthISFCustomerRideRequest)
        .filter(HealthISFCustomerRideRequest.id == request_id)
        .first()
    )
    if request_row is None or str(request_row.organization_id) != str(organization_id):
        raise ValueError("Ride request not found.")
    ride = db.query(HealthISFRide).filter(HealthISFRide.id == request_row.ride_id).first()
    payment = _get_payment_for_ride(db, str(request_row.ride_id))
    payment_status = payment.payment_status if payment is not None else PAYMENT_PENDING
    fare = None
    if payment is not None:
        fare = amount_major_from_minor(int(payment.amount_minor or 0), payment.currency or "usd")
    failed = payment_status == PAYMENT_FAILED
    return {
        "request_id": str(request_row.id),
        "ride_id": str(request_row.ride_id),
        "dispatch_status": request_row.dispatch_status,
        "lifecycle_state": getattr(ride, "lifecycle_state", None) if ride is not None else None,
        "payment_status": payment_status,
        "held_for_payment": ride_is_awaiting_payment(ride, request_row),
        "released_to_dispatch": (
            not ride_is_awaiting_payment(ride, request_row)
            and payment_status == PAYMENT_SUCCEEDED
        ),
        "estimated_ride_fare_usd": fare,
        "sandbox": True,
        "sandbox_notice": SANDBOX_NOTICE,
        "message": (
            "Payment failed. You can retry the sandbox card. This ride is not in the dispatcher queue."
            if failed
            else (
                "Payment received. Your ride is now in the dispatcher queue."
                if payment_status == PAYMENT_SUCCEEDED
                else "Complete sandbox payment before this ride can enter the dispatcher queue."
            )
        ),
    }


def release_ride_after_payment(db: Session, *, payment: AmicorCustomerPayment) -> None:
    ride_id = str(payment.ride_id or payment.internal_service_id or "").strip()
    if not ride_id or payment.service_type != SERVICE_RIDE:
        return
    ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
    request_row = (
        db.query(HealthISFCustomerRideRequest)
        .filter(HealthISFCustomerRideRequest.ride_id == ride_id)
        .order_by(HealthISFCustomerRideRequest.created_at.desc())
        .first()
    )
    if ride is None:
        return
    if payment.payment_status == PAYMENT_FAILED:
        if request_row is not None and str(request_row.dispatch_status or "") != CustomerRequestStatus.AWAITING_PAYMENT.value:
            if ride_is_awaiting_payment(ride, request_row):
                request_row.dispatch_status = CustomerRequestStatus.AWAITING_PAYMENT.value
                request_row.updated_at = now()
        db.commit()
        return
    if payment.payment_status != PAYMENT_SUCCEEDED:
        return
    if str(getattr(ride, "lifecycle_state", "") or "") == RideStatus.AWAITING_PAYMENT.value:
        RideLifecycleManager.transition_ride(
            db,
            ride,
            target_state=RideStatus.QUEUED.value,
            action_type="payment_succeeded",
            actor_user_id=None,
            note="Sandbox payment succeeded; ride released to dispatch",
            payload={"ride_id": ride.id, "payment_id": payment.id},
        )
    if request_row is not None and str(request_row.dispatch_status or "") == CustomerRequestStatus.AWAITING_PAYMENT.value:
        request_row.dispatch_status = CustomerRequestStatus.PENDING.value
        request_row.pending_at = request_row.pending_at or now()
        request_row.updated_at = now()
    db.commit()

    if request_row is None:
        return
    from app.modules.health_isf.routes import _schedule_customer_request_side_effects

    _schedule_customer_request_side_effects(
        organization_id=str(request_row.organization_id),
        request_id=str(request_row.id),
        ride_id=str(ride.id),
        rider_phone=request_row.rider_phone,
        actor_user_id=request_row.submitted_by_user_id,
        idempotency_key="",
        auth_decision_status="paid",
        auth_decision_reason="sandbox_payment_succeeded",
        auth_decision_source="stripe_webhook",
        ride_type=request_row.ride_type,
        scheduled_time_iso=request_row.scheduled_time.isoformat() if request_row.scheduled_time else None,
        dispatch_status=request_row.dispatch_status,
        passenger_name=ride.passenger_name,
        priority_score=float(ride.priority_score or 0.0),
        priority_tag=str(ride.priority_tag or "normal"),
        provider_id=str(ride.provider_id) if ride.provider_id else None,
    )
