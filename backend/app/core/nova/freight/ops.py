"""Nova Freight V1 operations summary and completed-history views."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.nova.freight.models import (
    NovaFreightCarrier,
    NovaFreightInvoice,
    NovaFreightPayout,
    NovaFreightSettlement,
    NovaFreightShipment,
    NovaFreightShipmentEvent,
)
from app.core.nova.freight.money import money
from app.core.nova.freight.service import get_shipment, list_shipment_events, list_shipments
from app.helpers import now


ACTIVE_WORK_STATUSES = (
    "accepted",
    "en_route_to_pickup",
    "arrived_pickup",
    "picked_up",
    "in_transit",
    "arrived_delivery",
    "delivered",
)
UNPAID_INVOICE_STATUSES = ("draft", "ready", "payment_pending", "failed")
APPROVED_PAYOUT_STATUSES = ("approved", "ready")


def _start_of_today(stamp: datetime) -> datetime:
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.replace(hour=0, minute=0, second=0, microsecond=0)


def _count_status(db: Session, organization_id: str, statuses: tuple[str, ...] | str) -> int:
    values = (statuses,) if isinstance(statuses, str) else statuses
    return (
        db.query(NovaFreightShipment)
        .filter(
            NovaFreightShipment.organization_id == organization_id,
            NovaFreightShipment.status.in_(values),
        )
        .count()
    )


def _sum_money(values) -> object:
    total = money(0)
    for value in values:
        total = money(total + money(value or 0))
    return total


def ops_summary(db: Session, *, organization_id: str) -> dict:
    today = _start_of_today(now())
    paid_invoices = (
        db.query(NovaFreightInvoice)
        .filter(
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.invoice_status == "paid",
        )
        .all()
    )
    unpaid_invoices = (
        db.query(NovaFreightInvoice)
        .filter(
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.invoice_status.in_(UNPAID_INVOICE_STATUSES),
        )
        .count()
    )
    payouts = (
        db.query(NovaFreightPayout)
        .filter(NovaFreightPayout.organization_id == organization_id)
        .all()
    )
    pending = [row for row in payouts if row.payout_status == "pending"]
    approved = [row for row in payouts if row.payout_status in APPROVED_PAYOUT_STATUSES]
    paid = [row for row in payouts if row.payout_status == "paid"]
    held = [row for row in payouts if row.payout_status == "held"]
    completed_today = (
        db.query(NovaFreightShipment)
        .filter(
            NovaFreightShipment.organization_id == organization_id,
            NovaFreightShipment.status == "completed",
            func.coalesce(NovaFreightShipment.last_status_at, NovaFreightShipment.updated_at) >= today,
        )
        .count()
    )
    customer_revenue = _sum_money(row.total_amount for row in paid_invoices)
    carrier_total = _sum_money(row.carrier_payout_amount for row in paid)
    margin_total = _sum_money(row.amicor_margin_amount for row in paid)
    return {
        "awaiting_dispatch": _count_status(db, organization_id, "ready_for_dispatch"),
        "offered": _count_status(db, organization_id, "offered"),
        "accepted_active": _count_status(db, organization_id, ACTIVE_WORK_STATUSES),
        "in_transit": _count_status(db, organization_id, "in_transit"),
        "completed_today": completed_today,
        "unpaid_invoices": unpaid_invoices,
        "paid_invoices": len(paid_invoices),
        "pending_payouts": len(pending),
        "approved_payouts": len(approved),
        "paid_payouts": len(paid),
        "held_payouts": len(held),
        "gross_customer_revenue": customer_revenue,
        "carrier_payout_total": carrier_total,
        "amicor_margin_estimate": margin_total,
        "currency": "USD",
    }


def _carrier_name(db: Session, carrier_id: str | None) -> str | None:
    if not carrier_id:
        return None
    row = db.query(NovaFreightCarrier).filter(NovaFreightCarrier.carrier_id == carrier_id).first()
    return row.name if row else None


def _event_at(db: Session, shipment_id: str, organization_id: str, status_after: str):
    row = (
        db.query(NovaFreightShipmentEvent)
        .filter(
            NovaFreightShipmentEvent.shipment_id == shipment_id,
            NovaFreightShipmentEvent.organization_id == organization_id,
            NovaFreightShipmentEvent.status_after == status_after,
        )
        .order_by(NovaFreightShipmentEvent.created_at.asc())
        .first()
    )
    return row.created_at if row else None


def history_row(db: Session, shipment: NovaFreightShipment, *, include_events: bool = False) -> dict:
    invoice = (
        db.query(NovaFreightInvoice)
        .filter(
            NovaFreightInvoice.shipment_id == shipment.shipment_id,
            NovaFreightInvoice.organization_id == shipment.organization_id,
            NovaFreightInvoice.invoice_status != "void",
        )
        .order_by(NovaFreightInvoice.created_at.desc())
        .first()
    )
    payout = (
        db.query(NovaFreightPayout)
        .filter(
            NovaFreightPayout.shipment_id == shipment.shipment_id,
            NovaFreightPayout.organization_id == shipment.organization_id,
            NovaFreightPayout.payout_status != "void",
        )
        .order_by(NovaFreightPayout.created_at.desc())
        .first()
    )
    settlement = None
    if payout is not None:
        settlement = (
            db.query(NovaFreightSettlement)
            .filter(NovaFreightSettlement.payout_id == payout.payout_id)
            .first()
        )
    row = {
        "shipment_id": shipment.shipment_id,
        "customer_name": shipment.customer_name,
        "pickup_city": shipment.pickup_city,
        "pickup_state": shipment.pickup_state,
        "delivery_city": shipment.delivery_city,
        "delivery_state": shipment.delivery_state,
        "assigned_carrier_id": shipment.assigned_carrier_id,
        "assigned_carrier_name": _carrier_name(db, shipment.assigned_carrier_id),
        "created_at": shipment.created_at,
        "accepted_at": _event_at(db, shipment.shipment_id, shipment.organization_id, "accepted"),
        "completed_at": shipment.last_status_at if shipment.status == "completed" else None,
        "final_quote": shipment.quoted_amount,
        "invoice_status": invoice.invoice_status if invoice else None,
        "customer_payment_status": invoice.invoice_status if invoice else None,
        "carrier_payout_status": payout.payout_status if payout else None,
        "settlement_status": settlement.settlement_status if settlement else None,
        "remittance_reference": settlement.remittance_reference if settlement else None,
        "has_pickup_proof": bool(shipment.proof_of_pickup_ref),
        "has_delivery_proof": bool(shipment.proof_of_delivery_ref),
        "status": shipment.status,
    }
    if include_events:
        row["events"] = [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "status_before": event.status_before,
                "status_after": event.status_after,
                "actor_role": event.actor_role,
                "created_at": event.created_at,
                "notes": event.notes,
            }
            for event in list_shipment_events(db, shipment.shipment_id, organization_id=shipment.organization_id)
        ]
    return row


def list_history(db: Session, *, organization_id: str) -> list[dict]:
    rows = list_shipments(db, organization_id=organization_id, scope="history")
    return [history_row(db, row) for row in rows]


def get_history_detail(db: Session, shipment_id: str, *, organization_id: str) -> dict:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    return history_row(db, shipment, include_events=True)
