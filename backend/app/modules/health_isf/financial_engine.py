"""Canonical financial engine for completed transportation trips.

Single source of truth for ride price, driver pay, platform revenue, billing,
claims, handoffs, and AI audit entries. Invoked automatically on trip completion.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.ai_audit_engine import AIAuditEngine
from app.modules.health_isf.models import (
    HealthISFBillingHandoff,
    HealthISFClaim,
    HealthISFCustomerRideRequest,
    HealthISFPaymentTransaction,
    HealthISFPayout,
    HealthISFRide,
    HealthISFSettlementLedger,
    HealthISFTrip,
    HealthISFTripDocument,
    HealthISFTripFinancialRecord,
    TripStatus,
)

logger = logging.getLogger("amicor.health_isf.financial_engine")

PRICING_VERSION = "trip_financial_engine_v1"
BASE_FARE_USD = 16.0
PER_MILE_USD = 3.25
PER_MINUTE_USD = 0.55
MIN_RIDE_PRICE_USD = 18.0
DRIVER_SHARE_RATIO = 0.72
PROVIDER_SHARE_RATIO = 0.18
PROCESSING_FEE_RATE = 0.029

HEALTHCARE_SERVICE_MARKERS = {
    "healthcare",
    "medical_transport",
    "medical",
    "dialysis",
    "clinic",
    "hospital",
    "nemt",
}


@dataclass(frozen=True)
class RideFinancialBreakdown:
    ride_price_usd: float
    driver_pay_usd: float
    platform_revenue_usd: float
    provider_share_usd: float
    processing_fee_usd: float
    is_healthcare: bool
    miles: float
    minutes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ride_price_usd": self.ride_price_usd,
            "driver_pay_usd": self.driver_pay_usd,
            "platform_revenue_usd": self.platform_revenue_usd,
            "provider_share_usd": self.provider_share_usd,
            "processing_fee_usd": self.processing_fee_usd,
            "is_healthcare": self.is_healthcare,
            "miles": self.miles,
            "minutes": self.minutes,
        }


class TripFinancialEngine:
    @staticmethod
    def _is_healthcare_trip(
        ride: HealthISFRide,
        request_row: HealthISFCustomerRideRequest | None,
    ) -> bool:
        ride_type = str(getattr(request_row, "ride_type", "") or "").strip().lower()
        if ride_type == "healthcare":
            return True
        service_type = str(ride.service_type or "").strip().lower()
        return any(marker in service_type for marker in HEALTHCARE_SERVICE_MARKERS)

    @classmethod
    def calculate_breakdown(
        cls,
        ride: HealthISFRide,
        *,
        request_row: HealthISFCustomerRideRequest | None = None,
    ) -> RideFinancialBreakdown:
        miles = max(0.0, float(ride.estimated_distance_miles or 0.0))
        minutes = max(0, int(ride.estimated_duration_minutes or 0))
        ride_price = round(
            max(
                MIN_RIDE_PRICE_USD,
                BASE_FARE_USD + (miles * PER_MILE_USD) + (minutes * PER_MINUTE_USD),
            ),
            2,
        )
        is_healthcare = cls._is_healthcare_trip(ride, request_row)
        driver_pay = round(ride_price * DRIVER_SHARE_RATIO, 2)
        provider_share = round(ride_price * PROVIDER_SHARE_RATIO, 2) if is_healthcare else 0.0
        processing_fee = round(ride_price * PROCESSING_FEE_RATE, 2)
        platform_revenue = round(
            max(0.0, ride_price - driver_pay - provider_share - processing_fee),
            2,
        )
        return RideFinancialBreakdown(
            ride_price_usd=ride_price,
            driver_pay_usd=driver_pay,
            platform_revenue_usd=platform_revenue,
            provider_share_usd=provider_share,
            processing_fee_usd=processing_fee,
            is_healthcare=is_healthcare,
            miles=miles,
            minutes=minutes,
        )

    @staticmethod
    def _ensure_trip(db: Session, ride: HealthISFRide) -> HealthISFTrip | None:
        if not ride.driver_id:
            return None

        trip = (
            db.query(HealthISFTrip)
            .filter(HealthISFTrip.ride_id == ride.id)
            .order_by(desc(HealthISFTrip.created_at))
            .first()
        )
        end_time = ride.completed_at or now()
        start_time = ride.accepted_at or ride.assigned_at or ride.requested_at or end_time
        duration_minutes: int | None = None
        if start_time and end_time:
            norm_start = (
                start_time.replace(tzinfo=timezone.utc)
                if start_time.tzinfo is None
                else start_time.astimezone(timezone.utc)
            )
            norm_end = (
                end_time.replace(tzinfo=timezone.utc)
                if end_time.tzinfo is None
                else end_time.astimezone(timezone.utc)
            )
            if norm_end >= norm_start:
                duration_minutes = int((norm_end - norm_start).total_seconds() // 60)

        if not trip:
            trip = HealthISFTrip(
                id=uuid4(),
                ride_id=ride.id,
                driver_id=ride.driver_id,
                status=TripStatus.COMPLETED,
                start_time=start_time,
                end_time=end_time,
                distance_miles=float(ride.estimated_distance_miles or 0.0) or None,
                duration_minutes=duration_minutes,
                created_at=now(),
                updated_at=now(),
            )
            db.add(trip)
            db.flush()
        else:
            trip.status = TripStatus.COMPLETED
            trip.end_time = trip.end_time or end_time
            if trip.start_time is None:
                trip.start_time = start_time
            if trip.distance_miles is None and ride.estimated_distance_miles is not None:
                trip.distance_miles = float(ride.estimated_distance_miles)
            if trip.duration_minutes is None and duration_minutes is not None:
                trip.duration_minutes = duration_minutes
            trip.updated_at = now()
        return trip

    @classmethod
    def _resolve_payment_actor_user_id(cls, db: Session, actor_user_id: str | None) -> str | None:
        if not actor_user_id:
            return None
        try:
            from app.db.models import User

            exists = db.query(User.id).filter(User.id == str(actor_user_id)).first()
            return str(actor_user_id) if exists else None
        except Exception:
            return None

    @classmethod
    def get_financial_record_for_ride(
        cls,
        db: Session,
        *,
        ride_id: str,
    ) -> HealthISFTripFinancialRecord | None:
        return (
            db.query(HealthISFTripFinancialRecord)
            .filter(HealthISFTripFinancialRecord.ride_id == ride_id)
            .order_by(desc(HealthISFTripFinancialRecord.created_at))
            .first()
        )

    @classmethod
    def process_trip_completion(
        cls,
        db: Session,
        ride: HealthISFRide,
        *,
        actor_user_id: str | None = None,
        materialize_payout_row: bool = True,
    ) -> dict[str, Any] | None:
        """Idempotent financial settlement for a completed ride.

        Guarantees at most one financial record, billing handoff, payment,
        and document set per ride_id.
        """
        existing = cls.get_financial_record_for_ride(db, ride_id=ride.id)
        if existing:
            summary = cls.build_summary_from_record(db, existing)
            payment = None
            payout = None
            if existing.payment_transaction_id:
                payment = (
                    db.query(HealthISFPaymentTransaction)
                    .filter(HealthISFPaymentTransaction.id == existing.payment_transaction_id)
                    .first()
                )
            if existing.payout_id:
                payout = (
                    db.query(HealthISFPayout)
                    .filter(HealthISFPayout.id == existing.payout_id)
                    .first()
                )
            if payment and payout:
                request_row = (
                    db.query(HealthISFCustomerRideRequest)
                    .filter(HealthISFCustomerRideRequest.ride_id == ride.id)
                    .first()
                )
                breakdown = cls.calculate_breakdown(ride, request_row=request_row)
                summary["documents"] = cls._ensure_trip_documents(
                    db,
                    ride=ride,
                    record=existing,
                    payment=payment,
                    payout=payout,
                    breakdown=breakdown,
                )
            elif payment:
                request_row = (
                    db.query(HealthISFCustomerRideRequest)
                    .filter(HealthISFCustomerRideRequest.ride_id == ride.id)
                    .first()
                )
                breakdown = cls.calculate_breakdown(ride, request_row=request_row)
                summary["documents"] = cls._ensure_trip_documents(
                    db,
                    ride=ride,
                    record=existing,
                    payment=payment,
                    payout=None,
                    breakdown=breakdown,
                )
            else:
                summary["documents"] = cls.list_trip_documents_for_ride(
                    db, ride_id=ride.id, organization_id=ride.organization_id
                )
            return summary

        trip = cls._ensure_trip(db, ride)
        if not trip or not ride.driver_id:
            return None

        request_row = (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.ride_id == ride.id)
            .first()
        )
        breakdown = cls.calculate_breakdown(ride, request_row=request_row)

        payment = (
            db.query(HealthISFPaymentTransaction)
            .filter(
                HealthISFPaymentTransaction.ride_id == ride.id,
                HealthISFPaymentTransaction.organization_id == ride.organization_id,
            )
            .order_by(desc(HealthISFPaymentTransaction.created_at))
            .first()
        )
        if not payment:
            stripe_paid = None
            try:
                from app.modules.payments.models import PAYMENT_SUCCEEDED, AmicorCustomerPayment

                stripe_paid = (
                    db.query(AmicorCustomerPayment)
                    .filter(
                        AmicorCustomerPayment.ride_id == ride.id,
                        AmicorCustomerPayment.payment_status == PAYMENT_SUCCEEDED,
                    )
                    .order_by(desc(AmicorCustomerPayment.created_at))
                    .first()
                )
            except Exception:
                stripe_paid = None
            payment = HealthISFPaymentTransaction(
                id=uuid4(),
                organization_id=ride.organization_id,
                ride_id=ride.id,
                driver_id=ride.driver_id,
                provider_id=ride.provider_id,
                gateway="stripe" if stripe_paid is not None else "simulated",
                gateway_payment_intent_id=(
                    stripe_paid.stripe_payment_intent_id
                    if stripe_paid is not None
                    else f"pi_{uuid4().replace('-', '')[:24]}"
                ),
                status="succeeded",
                currency="usd",
                amount_usd=breakdown.ride_price_usd,
                tip_amount_usd=0.0,
                surcharge_usd=0.0,
                processing_fee_usd=breakdown.processing_fee_usd,
                settlement_status="settled",
                invoice_reference=f"BILL-{ride.id[:8].upper()}",
                failure_reason=None,
                attempt_count=1,
                created_by_user_id=cls._resolve_payment_actor_user_id(db, actor_user_id),
                created_at=now(),
                updated_at=now(),
                paid_at=now(),
            )
            db.add(payment)
            db.flush()
        else:
            payment.amount_usd = breakdown.ride_price_usd
            payment.processing_fee_usd = breakdown.processing_fee_usd
            payment.status = "succeeded"
            payment.settlement_status = "settled"
            payment.paid_at = payment.paid_at or now()
            payment.updated_at = now()

        payout: HealthISFPayout | None = None
        if materialize_payout_row:
            payout = (
                db.query(HealthISFPayout)
                .filter(HealthISFPayout.trip_id == trip.id)
                .order_by(desc(HealthISFPayout.created_at))
                .first()
            )
            if not payout:
                payout = HealthISFPayout(
                    id=uuid4(),
                    driver_id=ride.driver_id,
                    trip_id=trip.id,
                    amount_usd=breakdown.driver_pay_usd,
                    status="pending",
                    description=f"Driver earnings for completed ride {ride.id[:8]}",
                    created_at=now(),
                    updated_at=now(),
                )
                db.add(payout)
                db.flush()
            else:
                payout.amount_usd = breakdown.driver_pay_usd
                payout.updated_at = now()

        existing_settlements = (
            db.query(HealthISFSettlementLedger)
            .filter(HealthISFSettlementLedger.payment_transaction_id == payment.id)
            .count()
        )
        if existing_settlements == 0:
            settlements = [
                HealthISFSettlementLedger(
                    id=uuid4(),
                    organization_id=ride.organization_id,
                    payment_transaction_id=payment.id,
                    ride_id=ride.id,
                    participant_type="driver",
                    participant_id=ride.driver_id,
                    gross_amount_usd=breakdown.ride_price_usd,
                    net_amount_usd=breakdown.driver_pay_usd,
                    status="processed",
                    processed_at=now(),
                    created_at=now(),
                ),
                HealthISFSettlementLedger(
                    id=uuid4(),
                    organization_id=ride.organization_id,
                    payment_transaction_id=payment.id,
                    ride_id=ride.id,
                    participant_type="platform",
                    participant_id=None,
                    gross_amount_usd=breakdown.ride_price_usd,
                    net_amount_usd=breakdown.platform_revenue_usd,
                    status="processed",
                    processed_at=now(),
                    created_at=now(),
                ),
            ]
            if breakdown.is_healthcare and breakdown.provider_share_usd > 0:
                settlements.append(
                    HealthISFSettlementLedger(
                        id=uuid4(),
                        organization_id=ride.organization_id,
                        payment_transaction_id=payment.id,
                        ride_id=ride.id,
                        participant_type="provider",
                        participant_id=ride.provider_id,
                        gross_amount_usd=breakdown.ride_price_usd,
                        net_amount_usd=breakdown.provider_share_usd,
                        status="processed",
                        processed_at=now(),
                        created_at=now(),
                    )
                )
            for row in settlements:
                db.add(row)

        claim: HealthISFClaim | None = None
        if breakdown.is_healthcare:
            claim = (
                db.query(HealthISFClaim)
                .filter(HealthISFClaim.ride_id == ride.id)
                .order_by(desc(HealthISFClaim.created_at))
                .first()
            )
            if not claim:
                claim = HealthISFClaim(
                    id=uuid4(),
                    organization_id=ride.organization_id,
                    ride_id=ride.id,
                    provider_id=ride.provider_id,
                    claim_reference=f"CLM-{ride.id[:8].upper()}",
                    status="submitted",
                    billed_amount_usd=breakdown.ride_price_usd,
                    service_type=str(ride.service_type or "healthcare"),
                    passenger_name=str(ride.passenger_name or ""),
                    created_at=now(),
                    updated_at=now(),
                )
                db.add(claim)
                db.flush()

        handoff = (
            db.query(HealthISFBillingHandoff)
            .filter(HealthISFBillingHandoff.ride_id == ride.id)
            .order_by(desc(HealthISFBillingHandoff.created_at))
            .first()
        )
        if not handoff:
            handoff = HealthISFBillingHandoff(
                id=uuid4(),
                organization_id=ride.organization_id,
                ride_id=ride.id,
                handoff_status="ready",
                payment_transaction_id=payment.id,
                payout_id=payout.id if payout else None,
                claim_id=getattr(claim, "id", None),
                ride_price_usd=breakdown.ride_price_usd,
                driver_pay_usd=breakdown.driver_pay_usd,
                platform_revenue_usd=breakdown.platform_revenue_usd,
                created_at=now(),
                updated_at=now(),
            )
            db.add(handoff)
            db.flush()
        else:
            handoff.handoff_status = "ready"
            handoff.payment_transaction_id = handoff.payment_transaction_id or payment.id
            handoff.payout_id = handoff.payout_id or (payout.id if payout else None)
            handoff.ride_price_usd = breakdown.ride_price_usd
            handoff.driver_pay_usd = breakdown.driver_pay_usd
            handoff.platform_revenue_usd = breakdown.platform_revenue_usd
            handoff.updated_at = now()

        # Re-check immediately before insert to collapse near-concurrent completions.
        raced = cls.get_financial_record_for_ride(db, ride_id=ride.id)
        if raced:
            return cls.process_trip_completion(
                db,
                ride,
                actor_user_id=actor_user_id,
                materialize_payout_row=materialize_payout_row,
            )

        record = HealthISFTripFinancialRecord(
            id=uuid4(),
            organization_id=ride.organization_id,
            ride_id=ride.id,
            trip_id=trip.id,
            ride_price_usd=breakdown.ride_price_usd,
            driver_pay_usd=breakdown.driver_pay_usd,
            platform_revenue_usd=breakdown.platform_revenue_usd,
            provider_share_usd=breakdown.provider_share_usd,
            processing_fee_usd=breakdown.processing_fee_usd,
            payment_transaction_id=payment.id,
            payout_id=payout.id if payout else None,
            claim_id=getattr(claim, "id", None),
            billing_handoff_id=handoff.id,
            is_healthcare=breakdown.is_healthcare,
            service_type=str(ride.service_type or ""),
            breakdown_json=json.dumps(breakdown.as_dict(), separators=(",", ":")),
            created_at=now(),
        )
        try:
            with db.begin_nested():
                db.add(record)
                db.flush()
        except IntegrityError:
            # Concurrent completion already persisted the unique ride financial row.
            existing_after_race = cls.get_financial_record_for_ride(db, ride_id=ride.id)
            if existing_after_race:
                summary = cls.build_summary_from_record(db, existing_after_race)
                summary["documents"] = cls.list_trip_documents_for_ride(
                    db, ride_id=ride.id, organization_id=ride.organization_id
                )
                return summary
            raise

        if claim and not claim.financial_record_id:
            claim.financial_record_id = record.id
            claim.updated_at = now()

        if not handoff.financial_record_id:
            handoff.financial_record_id = record.id
            handoff.updated_at = now()

        documents = cls._ensure_trip_documents(
            db,
            ride=ride,
            record=record,
            payment=payment,
            payout=payout,
            breakdown=breakdown,
        )

        summary = cls.build_summary_from_record(db, record)
        summary["documents"] = documents
        try:
            cls._record_ai_audit(
                db,
                ride=ride,
                record=record,
                breakdown=breakdown,
                actor_user_id=cls._resolve_payment_actor_user_id(db, actor_user_id),
            )
            db.flush()
        except Exception as exc:
            logger.warning(
                "Financial AI audit skipped",
                extra={"ride_id": ride.id, "error": str(exc)},
            )
        logger.info(
            "Trip financials processed",
            extra={
                "ride_id": ride.id,
                "ride_price_usd": breakdown.ride_price_usd,
                "driver_pay_usd": breakdown.driver_pay_usd,
                "platform_revenue_usd": breakdown.platform_revenue_usd,
                "document_count": len(documents),
            },
        )
        return summary

    @classmethod
    def _ensure_trip_documents(
        cls,
        db: Session,
        *,
        ride: HealthISFRide,
        record: HealthISFTripFinancialRecord,
        payment: HealthISFPaymentTransaction,
        payout: HealthISFPayout | None,
        breakdown: RideFinancialBreakdown,
    ) -> list[dict[str, Any]]:
        """Create receipt, payout statement, and billing record documents for a completed trip."""
        payout_reference = str(getattr(payout, "id", "") or record.id)
        existing = (
            db.query(HealthISFTripDocument)
            .filter(
                HealthISFTripDocument.ride_id == ride.id,
                HealthISFTripDocument.organization_id == ride.organization_id,
            )
            .all()
        )
        by_type = {str(row.document_type): row for row in existing}
        ride_ref = str(ride.id or "")[:8].upper()
        specs = [
            {
                "document_type": "trip_receipt",
                "title": f"Trip Receipt · {ride.passenger_name or 'Passenger'}",
                "reference": str(payment.invoice_reference or f"RCPT-{ride_ref}"),
                "amount_usd": breakdown.ride_price_usd,
                "content": {
                    "passenger_name": ride.passenger_name,
                    "pickup_address": ride.pickup_address,
                    "dropoff_address": ride.dropoff_address,
                    "fare_usd": breakdown.ride_price_usd,
                    "processing_fee_usd": breakdown.processing_fee_usd,
                    "payment_id": payment.id,
                    "invoice_reference": payment.invoice_reference,
                },
            },
            {
                "document_type": "driver_payout_statement",
                "title": f"Driver Payout · {ride_ref}",
                "reference": f"PAYOUT-{ride_ref}",
                "amount_usd": breakdown.driver_pay_usd,
                "content": {
                    "driver_id": ride.driver_id,
                    "driver_pay_usd": breakdown.driver_pay_usd,
                    "payout_id": payout_reference,
                    "ride_price_usd": breakdown.ride_price_usd,
                },
            },
            {
                "document_type": "billing_record",
                "title": f"Billing Record · {ride_ref}",
                "reference": f"BILLREC-{ride_ref}",
                "amount_usd": breakdown.ride_price_usd,
                "content": {
                    "fare_usd": breakdown.ride_price_usd,
                    "driver_pay_usd": breakdown.driver_pay_usd,
                    "platform_revenue_usd": breakdown.platform_revenue_usd,
                    "billing_handoff_id": record.billing_handoff_id,
                    "financial_record_id": record.id,
                },
            },
        ]
        created: list[HealthISFTripDocument] = []
        for spec in specs:
            row = by_type.get(str(spec["document_type"]))
            if row:
                row.title = str(spec["title"])
                row.reference = str(spec["reference"])
                row.amount_usd = float(spec["amount_usd"])
                row.status = "issued"
                row.financial_record_id = record.id
                row.payment_transaction_id = payment.id
                row.payout_id = payout.id if payout else None
                row.content_json = json.dumps(spec["content"], separators=(",", ":"))
                created.append(row)
                continue
            row = HealthISFTripDocument(
                id=uuid4(),
                organization_id=ride.organization_id,
                ride_id=ride.id,
                driver_id=ride.driver_id,
                financial_record_id=record.id,
                payment_transaction_id=payment.id,
                payout_id=payout.id if payout else None,
                document_type=str(spec["document_type"]),
                title=str(spec["title"]),
                reference=str(spec["reference"]),
                status="issued",
                amount_usd=float(spec["amount_usd"]),
                content_json=json.dumps(spec["content"], separators=(",", ":")),
                created_at=now(),
            )
            db.add(row)
            created.append(row)
        db.flush()
        return [cls._document_to_dict(row) for row in created]

    @staticmethod
    def _document_to_dict(row: HealthISFTripDocument) -> dict[str, Any]:
        return {
            "id": row.id,
            "ride_id": row.ride_id,
            "driver_id": row.driver_id,
            "document_type": row.document_type,
            "title": row.title,
            "name": row.title,
            "reference": row.reference,
            "status": row.status,
            "amount_usd": float(row.amount_usd or 0.0),
            "financial_record_id": row.financial_record_id,
            "payment_transaction_id": row.payment_transaction_id,
            "payout_id": row.payout_id,
            "expiresIn": "n/a",
            "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
        }

    @classmethod
    def list_trip_documents_for_driver(
        cls,
        db: Session,
        *,
        driver_id: str,
        organization_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = db.query(HealthISFTripDocument).filter(HealthISFTripDocument.driver_id == driver_id)
        if organization_id:
            query = query.filter(HealthISFTripDocument.organization_id == organization_id)
        rows = query.order_by(desc(HealthISFTripDocument.created_at)).limit(limit).all()
        return [cls._document_to_dict(row) for row in rows]

    @classmethod
    def list_trip_documents_for_ride(
        cls,
        db: Session,
        *,
        ride_id: str,
        organization_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = db.query(HealthISFTripDocument).filter(HealthISFTripDocument.ride_id == ride_id)
        if organization_id:
            query = query.filter(HealthISFTripDocument.organization_id == organization_id)
        rows = query.order_by(desc(HealthISFTripDocument.created_at)).all()
        return [cls._document_to_dict(row) for row in rows]

    @classmethod
    def list_trip_documents_for_organization(
        cls,
        db: Session,
        *,
        organization_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows = (
            db.query(HealthISFTripDocument)
            .filter(HealthISFTripDocument.organization_id == organization_id)
            .order_by(desc(HealthISFTripDocument.created_at))
            .limit(limit)
            .all()
        )
        return [cls._document_to_dict(row) for row in rows]

    @staticmethod
    def _record_ai_audit(
        db: Session,
        *,
        ride: HealthISFRide,
        record: HealthISFTripFinancialRecord,
        breakdown: RideFinancialBreakdown,
        actor_user_id: str | None,
    ) -> None:
        AIAuditEngine.record_action(
            db,
            organization_id=ride.organization_id,
            actor_user_id=actor_user_id,
            action_payload={
                "action_type": "trip_financial_settlement",
                "ride_id": ride.id,
                "financial_record_id": record.id,
                "ride_price_usd": breakdown.ride_price_usd,
                "driver_pay_usd": breakdown.driver_pay_usd,
                "platform_revenue_usd": breakdown.platform_revenue_usd,
                "provider_share_usd": breakdown.provider_share_usd,
                "claim_created": bool(record.claim_id),
                "billing_handoff_id": record.billing_handoff_id,
            },
            explainability={
                "why_this_action": "Automatic financial settlement triggered by trip completion.",
                "supporting_signals": [
                    {"signal": "lifecycle_state", "value": "completed"},
                    {"signal": "is_healthcare", "value": breakdown.is_healthcare},
                ],
                "risk_evaluation": "low",
            },
            rollback_reference=record.id,
        )

    @classmethod
    def build_summary_from_record(
        cls,
        db: Session,
        record: HealthISFTripFinancialRecord,
    ) -> dict[str, Any]:
        handoff = None
        if record.billing_handoff_id:
            handoff = (
                db.query(HealthISFBillingHandoff)
                .filter(HealthISFBillingHandoff.id == record.billing_handoff_id)
                .first()
            )
        claim = None
        if record.claim_id:
            claim = db.query(HealthISFClaim).filter(HealthISFClaim.id == record.claim_id).first()

        return {
            "ride_id": record.ride_id,
            "organization_id": record.organization_id,
            "trip_id": record.trip_id,
            "financial_record_id": record.id,
            "ride_price_usd": record.ride_price_usd,
            "driver_pay_usd": record.driver_pay_usd,
            "platform_revenue_usd": record.platform_revenue_usd,
            "provider_share_usd": record.provider_share_usd,
            "processing_fee_usd": record.processing_fee_usd,
            "is_healthcare": bool(record.is_healthcare),
            "service_type": record.service_type,
            "payment_transaction_id": record.payment_transaction_id,
            "payout_id": record.payout_id,
            "claim_id": record.claim_id,
            "claim_reference": getattr(claim, "claim_reference", None),
            "claim_status": getattr(claim, "status", None),
            "billing_handoff_id": record.billing_handoff_id,
            "billing_handoff_status": getattr(handoff, "handoff_status", None),
            "fare_amount": record.ride_price_usd,
            "total_amount": record.ride_price_usd,
            "payout_amount": record.driver_pay_usd,
            "documents": cls.list_trip_documents_for_ride(
                db, ride_id=record.ride_id, organization_id=record.organization_id
            ),
            "created_at": record.created_at.isoformat() if isinstance(record.created_at, datetime) else None,
        }

    @classmethod
    def get_ride_financial_summary(cls, db: Session, *, ride_id: str) -> dict[str, Any] | None:
        record = cls.get_financial_record_for_ride(db, ride_id=ride_id)
        if not record:
            return None
        return cls.build_summary_from_record(db, record)

    @classmethod
    def get_driver_earnings_summary(
        cls,
        db: Session,
        *,
        driver_id: str,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        query = (
            db.query(HealthISFTripFinancialRecord)
            .outerjoin(HealthISFTrip, HealthISFTrip.id == HealthISFTripFinancialRecord.trip_id)
            .join(HealthISFRide, HealthISFRide.id == HealthISFTripFinancialRecord.ride_id)
            .filter(
                or_(
                    HealthISFRide.driver_id == driver_id,
                    HealthISFTrip.driver_id == driver_id,
                )
            )
        )
        if organization_id:
            query = query.filter(HealthISFTripFinancialRecord.organization_id == organization_id)

        records = query.order_by(desc(HealthISFTripFinancialRecord.created_at)).limit(500).all()
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_total = 0.0
        lifetime_total = 0.0
        trip_count_today = 0
        trips: list[dict[str, Any]] = []
        for record in records:
            amount = float(record.driver_pay_usd or 0.0)
            lifetime_total += amount
            created = record.created_at
            if created:
                created_utc = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created.astimezone(timezone.utc)
                if created_utc >= today_start:
                    today_total += amount
                    trip_count_today += 1
            trips.append(
                {
                    "ride_id": record.ride_id,
                    "trip_id": record.trip_id,
                    "driver_pay_usd": amount,
                    "ride_price_usd": record.ride_price_usd,
                    "completed_at": created.isoformat() if created else None,
                }
            )

        return {
            "driver_id": driver_id,
            "organization_id": organization_id,
            "earnings_today_usd": round(today_total, 2),
            "earnings_lifetime_usd": round(lifetime_total, 2),
            "trip_count": len(records),
            "trip_count_today": trip_count_today,
            "recent_trips": trips[:25],
        }

    @classmethod
    def get_admin_revenue_summary(
        cls,
        db: Session,
        *,
        organization_id: str,
    ) -> dict[str, Any]:
        records = (
            db.query(HealthISFTripFinancialRecord)
            .filter(HealthISFTripFinancialRecord.organization_id == organization_id)
            .order_by(desc(HealthISFTripFinancialRecord.created_at))
            .limit(1000)
            .all()
        )
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        revenue_today = 0.0
        platform_today = 0.0
        ride_revenue_total = 0.0
        platform_revenue_total = 0.0
        driver_payout_total = 0.0
        claims_count = 0
        for record in records:
            ride_revenue_total += float(record.ride_price_usd or 0.0)
            platform_revenue_total += float(record.platform_revenue_usd or 0.0)
            driver_payout_total += float(record.driver_pay_usd or 0.0)
            if record.claim_id:
                claims_count += 1
            created = record.created_at
            if created:
                created_utc = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created.astimezone(timezone.utc)
                if created_utc >= today_start:
                    revenue_today += float(record.ride_price_usd or 0.0)
                    platform_today += float(record.platform_revenue_usd or 0.0)

        return {
            "organization_id": organization_id,
            "ride_revenue_total_usd": round(ride_revenue_total, 2),
            "platform_revenue_total_usd": round(platform_revenue_total, 2),
            "driver_payout_total_usd": round(driver_payout_total, 2),
            "revenue_today_usd": round(revenue_today, 2),
            "platform_revenue_today_usd": round(platform_today, 2),
            "completed_trip_count": len(records),
            "claims_count": claims_count,
        }
