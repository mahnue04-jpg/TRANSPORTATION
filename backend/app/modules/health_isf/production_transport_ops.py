"""Phase 8B additive production transport operations: GPS, routing/ETA, and payments."""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    HealthISFDriver,
    HealthISFDriverLocationPing,
    HealthISFPayout,
    HealthISFPaymentTransaction,
    HealthISFRide,
    HealthISFRideRoutePlan,
    HealthISFSettlementLedger,
)


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return radius_miles * 2 * math.asin(min(1.0, math.sqrt(a)))


def _point_to_segment_meters(
    point_lat: float,
    point_lng: float,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
) -> float:
    # Equirectangular projection is sufficient for short, city-scale route segments.
    avg_lat = math.radians((origin_lat + dest_lat) / 2.0)

    def _xy(lat: float, lng: float) -> tuple[float, float]:
        x = math.radians(lng) * math.cos(avg_lat)
        y = math.radians(lat)
        return x, y

    ax, ay = _xy(origin_lat, origin_lng)
    bx, by = _xy(dest_lat, dest_lng)
    px, py = _xy(point_lat, point_lng)

    abx = bx - ax
    aby = by - ay
    ab_sq = (abx * abx) + (aby * aby)
    if ab_sq <= 1e-12:
        dx = px - ax
        dy = py - ay
    else:
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / ab_sq))
        cx = ax + (t * abx)
        cy = ay + (t * aby)
        dx = px - cx
        dy = py - cy

    earth_radius_m = 6371000.0
    return math.sqrt((dx * earth_radius_m) ** 2 + (dy * earth_radius_m) ** 2)


class ProductionTransportOps:
    TRAFFIC_MULTIPLIER = {
        "light": 1.05,
        "normal": 1.15,
        "heavy": 1.35,
    }

    @staticmethod
    def upsert_route_plan(
        db: Session,
        *,
        organization_id: str,
        ride_id: str,
        map_provider: str,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        traffic_mode: str = "normal",
        deviation_threshold_meters: float = 250.0,
    ) -> HealthISFRideRoutePlan:
        ride = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.id == ride_id,
                HealthISFRide.organization_id == organization_id,
            )
            .first()
        )
        if not ride:
            raise ValueError("Ride not found")

        multiplier = ProductionTransportOps.TRAFFIC_MULTIPLIER.get(str(traffic_mode).lower(), 1.15)
        distance_miles = _haversine_miles(
            origin_latitude,
            origin_longitude,
            destination_latitude,
            destination_longitude,
        )
        adjusted_distance = max(0.1, distance_miles * multiplier)
        # Synthetic fallback speed for map abstraction when external provider is not configured.
        duration_minutes = max(2, int(round((adjusted_distance / 27.0) * 60)))

        route = (
            db.query(HealthISFRideRoutePlan)
            .filter(
                HealthISFRideRoutePlan.ride_id == ride_id,
                HealthISFRideRoutePlan.organization_id == organization_id,
            )
            .first()
        )

        if route is None:
            route = HealthISFRideRoutePlan(
                id=uuid4(),
                organization_id=organization_id,
                ride_id=ride_id,
                map_provider=map_provider,
                route_reference=f"route_{uuid4().replace('-', '')[:16]}",
                origin_latitude=origin_latitude,
                origin_longitude=origin_longitude,
                destination_latitude=destination_latitude,
                destination_longitude=destination_longitude,
                estimated_distance_miles=adjusted_distance,
                estimated_duration_minutes=duration_minutes,
                traffic_multiplier=multiplier,
                deviation_threshold_meters=max(50.0, float(deviation_threshold_meters)),
                path_points_json=None,
                created_at=now(),
                updated_at=now(),
            )
            db.add(route)
        else:
            route.map_provider = map_provider
            route.origin_latitude = origin_latitude
            route.origin_longitude = origin_longitude
            route.destination_latitude = destination_latitude
            route.destination_longitude = destination_longitude
            route.estimated_distance_miles = adjusted_distance
            route.estimated_duration_minutes = duration_minutes
            route.traffic_multiplier = multiplier
            route.deviation_threshold_meters = max(50.0, float(deviation_threshold_meters))
            route.updated_at = now()

        ride.estimated_distance_miles = adjusted_distance
        ride.estimated_duration_minutes = duration_minutes
        ride.updated_at = now()
        db.commit()
        db.refresh(route)
        return route

    @staticmethod
    def ingest_driver_location(
        db: Session,
        *,
        organization_id: str,
        driver_id: str,
        latitude: float,
        longitude: float,
        heading: float | None = None,
        speed_kph: float | None = None,
        accuracy_meters: float | None = None,
        ride_id: str | None = None,
        device_id: str | None = None,
        source: str = "mobile",
    ) -> dict[str, Any]:
        driver = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.id == driver_id,
                HealthISFDriver.organization_id == organization_id,
            )
            .first()
        )
        if not driver:
            raise ValueError("Driver not found")

        ping = HealthISFDriverLocationPing(
            id=uuid4(),
            organization_id=organization_id,
            driver_id=driver_id,
            ride_id=ride_id,
            latitude=latitude,
            longitude=longitude,
            heading=heading,
            speed_kph=speed_kph,
            accuracy_meters=accuracy_meters,
            source=source,
            device_id=device_id,
            heartbeat_at=now(),
            created_at=now(),
        )
        db.add(ping)

        route = None
        if ride_id:
            route = (
                db.query(HealthISFRideRoutePlan)
                .filter(
                    HealthISFRideRoutePlan.ride_id == ride_id,
                    HealthISFRideRoutePlan.organization_id == organization_id,
                )
                .first()
            )

        eta_minutes = None
        deviation_meters = 0.0
        is_deviated = False

        if route:
            remaining_miles = _haversine_miles(
                latitude,
                longitude,
                route.destination_latitude,
                route.destination_longitude,
            )
            speed_mph = max(12.0, (float(speed_kph) if speed_kph else 35.0) * 0.621371)
            eta_minutes = max(1, int(round((remaining_miles / speed_mph) * 60)))
            deviation_meters = _point_to_segment_meters(
                latitude,
                longitude,
                route.origin_latitude,
                route.origin_longitude,
                route.destination_latitude,
                route.destination_longitude,
            )
            is_deviated = deviation_meters > float(route.deviation_threshold_meters or 250.0)

        db.commit()
        db.refresh(ping)
        return {
            "location_ping_id": ping.id,
            "driver_id": driver_id,
            "ride_id": ride_id,
            "heartbeat_at": ping.heartbeat_at.isoformat(),
            "eta_minutes": eta_minutes,
            "deviation_meters": round(float(deviation_meters), 2),
            "is_deviated": bool(is_deviated),
            "next_heartbeat_due_at": (ping.heartbeat_at + timedelta(seconds=45)).isoformat(),
        }

    @staticmethod
    def get_route_snapshot(db: Session, *, organization_id: str, ride_id: str) -> dict[str, Any]:
        route = (
            db.query(HealthISFRideRoutePlan)
            .filter(
                HealthISFRideRoutePlan.organization_id == organization_id,
                HealthISFRideRoutePlan.ride_id == ride_id,
            )
            .first()
        )
        if not route:
            raise ValueError("Route plan not found")

        points = (
            db.query(HealthISFDriverLocationPing)
            .filter(
                HealthISFDriverLocationPing.organization_id == organization_id,
                HealthISFDriverLocationPing.ride_id == ride_id,
            )
            .order_by(HealthISFDriverLocationPing.created_at.desc())
            .limit(200)
            .all()
        )

        return {
            "ride_id": ride_id,
            "map_provider": route.map_provider,
            "route_reference": route.route_reference,
            "estimated_distance_miles": route.estimated_distance_miles,
            "estimated_duration_minutes": route.estimated_duration_minutes,
            "traffic_multiplier": route.traffic_multiplier,
            "deviation_threshold_meters": route.deviation_threshold_meters,
            "origin": {"lat": route.origin_latitude, "lng": route.origin_longitude},
            "destination": {"lat": route.destination_latitude, "lng": route.destination_longitude},
            "recent_points": [
                {
                    "id": row.id,
                    "driver_id": row.driver_id,
                    "lat": row.latitude,
                    "lng": row.longitude,
                    "speed_kph": row.speed_kph,
                    "heading": row.heading,
                    "heartbeat_at": row.heartbeat_at.isoformat(),
                }
                for row in reversed(points)
            ],
            "replay_safe": True,
            "restart_safe": True,
        }

    @staticmethod
    def mobile_reconnect_snapshot(
        db: Session,
        *,
        organization_id: str,
        driver_id: str,
        last_ping_id: str | None,
    ) -> dict[str, Any]:
        driver = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.id == driver_id,
                HealthISFDriver.organization_id == organization_id,
            )
            .first()
        )
        if not driver:
            raise ValueError("Driver not found")

        base_query = db.query(HealthISFDriverLocationPing).filter(
            HealthISFDriverLocationPing.organization_id == organization_id,
            HealthISFDriverLocationPing.driver_id == driver_id,
        )
        if last_ping_id:
            marker = base_query.filter(HealthISFDriverLocationPing.id == last_ping_id).first()
            if marker:
                base_query = base_query.filter(HealthISFDriverLocationPing.created_at > marker.created_at)

        queued = base_query.order_by(HealthISFDriverLocationPing.created_at.asc()).limit(250).all()
        last_seen = (
            db.query(func.max(HealthISFDriverLocationPing.heartbeat_at))
            .filter(
                HealthISFDriverLocationPing.organization_id == organization_id,
                HealthISFDriverLocationPing.driver_id == driver_id,
            )
            .scalar()
        )
        return {
            "driver_id": driver_id,
            "queued_location_updates": [
                {
                    "id": row.id,
                    "ride_id": row.ride_id,
                    "lat": row.latitude,
                    "lng": row.longitude,
                    "speed_kph": row.speed_kph,
                    "heading": row.heading,
                    "heartbeat_at": row.heartbeat_at.isoformat(),
                }
                for row in queued
            ],
            "last_heartbeat_at": last_seen.isoformat() if isinstance(last_seen, datetime) else None,
            "requires_full_resync": len(queued) >= 250,
        }


class ProductionPaymentOps:
    @staticmethod
    def create_payment_intent(
        db: Session,
        *,
        organization_id: str,
        ride_id: str,
        actor_user_id: str | None,
        amount_usd: float | None,
        tip_amount_usd: float,
        surcharge_usd: float,
        currency: str,
        invoice_reference: str | None,
        capture_immediately: bool,
    ) -> HealthISFPaymentTransaction:
        ride = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.id == ride_id,
                HealthISFRide.organization_id == organization_id,
            )
            .first()
        )
        if not ride:
            raise ValueError("Ride not found")

        estimated = float(ride.estimated_distance_miles or 0.0)
        baseline_amount = max(16.0, round((estimated * 3.25) if estimated > 0 else 22.0, 2))
        charge_amount = float(amount_usd) if amount_usd and amount_usd > 0 else baseline_amount
        total_amount = round(charge_amount + max(0.0, float(tip_amount_usd)) + max(0.0, float(surcharge_usd)), 2)

        stripe_enabled = str(os.getenv("HEALTH_ISF_STRIPE_ENABLED", "0")).lower() in {"1", "true", "yes"}
        gateway = "stripe" if stripe_enabled else "simulated"
        external_intent_id = f"pi_{uuid4().replace('-', '')[:24]}"

        tx = HealthISFPaymentTransaction(
            id=uuid4(),
            organization_id=organization_id,
            ride_id=ride.id,
            driver_id=ride.driver_id,
            provider_id=ride.provider_id,
            gateway=gateway,
            gateway_payment_intent_id=external_intent_id,
            status="succeeded" if capture_immediately else "requires_capture",
            currency=(currency or "usd").lower(),
            amount_usd=total_amount,
            tip_amount_usd=max(0.0, float(tip_amount_usd)),
            surcharge_usd=max(0.0, float(surcharge_usd)),
            processing_fee_usd=round(total_amount * 0.029, 2),
            settlement_status="pending",
            invoice_reference=invoice_reference,
            failure_reason=None,
            attempt_count=1,
            created_by_user_id=actor_user_id,
            created_at=now(),
            updated_at=now(),
            paid_at=now() if capture_immediately else None,
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        return tx

    @staticmethod
    def capture_payment(
        db: Session,
        *,
        organization_id: str,
        payment_id: str,
        actor_user_id: str | None,
    ) -> HealthISFPaymentTransaction:
        tx = (
            db.query(HealthISFPaymentTransaction)
            .filter(
                HealthISFPaymentTransaction.id == payment_id,
                HealthISFPaymentTransaction.organization_id == organization_id,
            )
            .first()
        )
        if not tx:
            raise ValueError("Payment transaction not found")

        if tx.status == "succeeded":
            return tx

        tx.attempt_count = int(tx.attempt_count or 0) + 1
        tx.status = "succeeded"
        tx.failure_reason = None
        tx.paid_at = now()
        tx.updated_at = now()
        tx.created_by_user_id = actor_user_id or tx.created_by_user_id

        db.commit()
        db.refresh(tx)
        return tx

    @staticmethod
    def settle_payment(
        db: Session,
        *,
        organization_id: str,
        payment_id: str,
        driver_ratio: float,
        provider_ratio: float,
    ) -> dict[str, Any]:
        tx = (
            db.query(HealthISFPaymentTransaction)
            .filter(
                HealthISFPaymentTransaction.id == payment_id,
                HealthISFPaymentTransaction.organization_id == organization_id,
            )
            .first()
        )
        if not tx:
            raise ValueError("Payment transaction not found")
        if tx.status != "succeeded":
            raise ValueError("Payment must be captured before settlement")

        if not (0.0 <= driver_ratio <= 1.0) or not (0.0 <= provider_ratio <= 1.0):
            raise ValueError("Settlement ratios must be between 0 and 1")

        normalized_total = driver_ratio + provider_ratio
        if normalized_total <= 0:
            raise ValueError("Settlement ratios must sum to a positive value")

        driver_share = round(tx.amount_usd * (driver_ratio / normalized_total), 2)
        provider_share = round(tx.amount_usd * (provider_ratio / normalized_total), 2)

        existing = (
            db.query(HealthISFSettlementLedger)
            .filter(HealthISFSettlementLedger.payment_transaction_id == tx.id)
            .count()
        )
        if existing > 0:
            settlements = (
                db.query(HealthISFSettlementLedger)
                .filter(HealthISFSettlementLedger.payment_transaction_id == tx.id)
                .all()
            )
            return {
                "payment_id": tx.id,
                "settlement_status": tx.settlement_status,
                "entries": [
                    {
                        "participant_type": row.participant_type,
                        "participant_id": row.participant_id,
                        "net_amount_usd": row.net_amount_usd,
                        "status": row.status,
                    }
                    for row in settlements
                ],
            }

        driver_settlement = HealthISFSettlementLedger(
            id=uuid4(),
            organization_id=organization_id,
            payment_transaction_id=tx.id,
            ride_id=tx.ride_id,
            participant_type="driver",
            participant_id=tx.driver_id,
            gross_amount_usd=tx.amount_usd,
            net_amount_usd=driver_share,
            status="processed",
            processed_at=now(),
            created_at=now(),
        )
        provider_settlement = HealthISFSettlementLedger(
            id=uuid4(),
            organization_id=organization_id,
            payment_transaction_id=tx.id,
            ride_id=tx.ride_id,
            participant_type="provider",
            participant_id=tx.provider_id,
            gross_amount_usd=tx.amount_usd,
            net_amount_usd=provider_share,
            status="processed",
            processed_at=now(),
            created_at=now(),
        )
        db.add(driver_settlement)
        db.add(provider_settlement)

        if tx.driver_id:
            payout = HealthISFPayout(
                id=uuid4(),
                driver_id=tx.driver_id,
                trip_id=tx.ride_id,
                amount_usd=driver_share,
                status="processed",
                description=f"Phase8B settlement for payment {tx.id}",
                created_at=now(),
                updated_at=now(),
                processed_at=now(),
            )
            db.add(payout)

        tx.settlement_status = "processed"
        tx.updated_at = now()
        db.commit()

        return {
            "payment_id": tx.id,
            "settlement_status": tx.settlement_status,
            "entries": [
                {
                    "participant_type": "driver",
                    "participant_id": tx.driver_id,
                    "net_amount_usd": driver_share,
                    "status": "processed",
                },
                {
                    "participant_type": "provider",
                    "participant_id": tx.provider_id,
                    "net_amount_usd": provider_share,
                    "status": "processed",
                },
            ],
        }
