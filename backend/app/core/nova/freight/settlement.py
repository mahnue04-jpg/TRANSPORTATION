"""Nova freight carrier payout and simulated TEST remittance. Not Delivery/Health payouts."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.freight.commercial import get_invoice_or_404
from app.core.nova.freight.models import (
    NovaFreightCarrier,
    NovaFreightInvoice,
    NovaFreightPayout,
    NovaFreightProof,
    NovaFreightSettlement,
    NovaFreightShipment,
    NovaFreightShipmentEvent,
)
from app.core.nova.freight.money import money
from app.core.nova.freight.payout_config import (
    PAYOUT_METHOD_SIMULATED,
    PAYOUT_POLICY_VERSION,
    split_customer_amount,
)
from app.core.nova.freight.service import NovaFreightError, get_shipment
from app.core.nova.freight.stripe_checkout import is_live_stripe_key, stripe_secret_key
from app.helpers import now, uuid4

ACTIVE_PAYOUT_STATUSES = frozenset({"pending", "approved", "ready", "processing", "paid", "held", "failed"})
MONEY_ACTION_STATUSES = frozenset({"pending", "held", "approved", "ready"})


def _new_payout_id() -> str:
    return "NFPY-" + uuid4().replace("-", "")[:9].upper()


def _new_settlement_id() -> str:
    return "NFS-" + uuid4().replace("-", "")[:10].upper()


def _new_event_id() -> str:
    return "NFE-" + uuid4().replace("-", "")[:10].upper()


def _add_event(
    db: Session,
    shipment: NovaFreightShipment,
    *,
    event_type: str,
    actor_user_id: str | None,
    actor_role: str | None,
    notes: str | None,
    payout_id: str | None = None,
    settlement_id: str | None = None,
    carrier_id: str | None = None,
    invoice_id: str | None = None,
) -> None:
    db.add(
        NovaFreightShipmentEvent(
            event_id=_new_event_id(),
            shipment_id=shipment.shipment_id,
            organization_id=shipment.organization_id,
            status_before=shipment.status,
            status_after=shipment.status,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_carrier_id=carrier_id or shipment.assigned_carrier_id,
            actor_role=actor_role,
            notes=notes,
            source="nova_freight_settlement",
            invoice_id=invoice_id,
            payout_id=payout_id,
            settlement_id=settlement_id,
            created_at=now(),
        )
    )


def _active_payout(db: Session, shipment_id: str, organization_id: str) -> NovaFreightPayout | None:
    return (
        db.query(NovaFreightPayout)
        .filter(
            NovaFreightPayout.shipment_id == shipment_id,
            NovaFreightPayout.organization_id == organization_id,
            NovaFreightPayout.payout_status != "void",
        )
        .first()
    )


def _carrier_name(db: Session, carrier_id: str) -> str | None:
    row = db.query(NovaFreightCarrier).filter(NovaFreightCarrier.carrier_id == carrier_id).first()
    return row.name if row else None


def _proof_warning(db: Session, shipment_id: str, organization_id: str) -> str | None:
    rows = (
        db.query(NovaFreightProof)
        .filter(
            NovaFreightProof.shipment_id == shipment_id,
            NovaFreightProof.organization_id == organization_id,
            NovaFreightProof.is_active.is_(True),
        )
        .all()
    )
    has_pop = any(row.proof_type.startswith("pickup_") for row in rows)
    has_pod = any(row.proof_type.startswith("delivery_") for row in rows)
    missing = []
    if not has_pop:
        missing.append("pickup proof")
    if not has_pod:
        missing.append("delivery proof")
    if not missing:
        return None
    return "Missing " + " and ".join(missing) + ". Warning only; payout is not blocked."


def assert_test_payout_mode() -> None:
    secret = stripe_secret_key()
    if secret and is_live_stripe_key(secret):
        raise NovaFreightError("Live Stripe keys are not allowed for Nova freight payouts", status_code=503)


def payout_eligibility(db: Session, shipment_id: str, *, organization_id: str) -> dict:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    reasons: list[str] = []
    warnings: list[str] = []
    invoice = None
    try:
        invoice = get_invoice_or_404(db, shipment_id, organization_id=organization_id)
    except NovaFreightError:
        reasons.append("Customer invoice is required")
    if shipment.status == "cancelled":
        reasons.append("Cancelled shipments are not payout eligible")
    if shipment.status != "completed":
        reasons.append("Shipment must be completed")
    if not shipment.assigned_carrier_id:
        reasons.append("Assigned carrier is required")
    if shipment.assigned_carrier_id:
        carrier = (
            db.query(NovaFreightCarrier)
            .filter(
                NovaFreightCarrier.carrier_id == shipment.assigned_carrier_id,
                NovaFreightCarrier.organization_id == organization_id,
            )
            .first()
        )
        if carrier is None:
            reasons.append("Required carrier settlement record is missing")
    if invoice is None:
        pass
    elif invoice.invoice_status == "payment_pending":
        reasons.append("Customer payment is still pending")
    elif invoice.invoice_status != "paid":
        reasons.append("Customer invoice must be paid")
    invoice_count = (
        db.query(NovaFreightInvoice)
        .filter(
            NovaFreightInvoice.shipment_id == shipment_id,
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.invoice_status != "void",
        )
        .count()
        if invoice is not None
        else 0
    )
    if invoice_count > 1:
        reasons.append("Unresolved duplicate invoice/payment state")
    existing = _active_payout(db, shipment_id, organization_id)
    if existing is not None:
        reasons.append("An active payout already exists")
    warning = _proof_warning(db, shipment_id, organization_id)
    if warning:
        warnings.append(warning)
    customer = money(invoice.total_amount) if invoice is not None else money(shipment.quoted_amount or 0)
    customer, carrier, margin = split_customer_amount(customer)
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "warnings": warnings,
        "shipment_id": shipment.shipment_id,
        "shipment_status": shipment.status,
        "assigned_carrier_id": shipment.assigned_carrier_id,
        "invoice_status": invoice.invoice_status if invoice else None,
        "has_pickup_proof": shipment.proof_of_pickup_ref is not None,
        "has_delivery_proof": shipment.proof_of_delivery_ref is not None,
        "suggested_customer_amount": customer,
        "suggested_carrier_payout": carrier,
        "suggested_amicor_margin": margin,
        "payout_policy_version": PAYOUT_POLICY_VERSION,
        "existing_payout_id": existing.payout_id if existing else None,
    }


def create_payout(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightPayout:
    check = payout_eligibility(db, shipment_id, organization_id=organization_id)
    if not check["eligible"]:
        raise NovaFreightError("; ".join(check["reasons"]), status_code=409)
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    invoice = get_invoice_or_404(db, shipment_id, organization_id=organization_id)
    customer, carrier, margin = split_customer_amount(invoice.total_amount)
    stamp = now()
    voided_count = (
        db.query(NovaFreightPayout)
        .filter(
            NovaFreightPayout.shipment_id == shipment.shipment_id,
            NovaFreightPayout.organization_id == organization_id,
            NovaFreightPayout.payout_status == "void",
        )
        .count()
    )
    row = NovaFreightPayout(
        payout_id=_new_payout_id(),
        shipment_id=shipment.shipment_id,
        carrier_id=shipment.assigned_carrier_id or "",
        organization_id=organization_id,
        invoice_id=invoice.invoice_id,
        customer_amount=customer,
        carrier_payout_amount=carrier,
        amicor_margin_amount=margin,
        adjustment_amount=money(0),
        currency=invoice.currency,
        payout_status="pending",
        payout_method=PAYOUT_METHOD_SIMULATED,
        proof_warning=check["warnings"][0] if check["warnings"] else None,
        idempotency_key=f"nova-freight-payout:{organization_id}:{shipment.shipment_id}:{voided_count}",
        created_at=stamp,
        updated_at=stamp,
    )
    try:
        db.add(row)
        db.flush()
        shipment.carrier_payout_amount = carrier
        shipment.amicor_margin = margin
        shipment.updated_at = stamp
        _add_event(
            db,
            shipment,
            event_type="carrier_payout_created",
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            notes=f"payout={row.payout_id} carrier={row.carrier_payout_amount} margin={row.amicor_margin_amount}",
            payout_id=row.payout_id,
            carrier_id=row.carrier_id,
            invoice_id=row.invoice_id,
        )
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        existing = _active_payout(db, shipment_id, organization_id)
        if existing is not None:
            return existing
        raise NovaFreightError("Payout already exists", status_code=409)


def get_payout_or_404(db: Session, payout_id: str, *, organization_id: str) -> NovaFreightPayout:
    row = (
        db.query(NovaFreightPayout)
        .filter(NovaFreightPayout.payout_id == payout_id, NovaFreightPayout.organization_id == organization_id)
        .first()
    )
    if row is None:
        raise NovaFreightError("Payout not found", status_code=404)
    return row


def get_shipment_payout(db: Session, shipment_id: str, *, organization_id: str) -> NovaFreightPayout:
    get_shipment(db, shipment_id, organization_id=organization_id)
    row = _active_payout(db, shipment_id, organization_id)
    if row is None:
        raise NovaFreightError("Payout not found", status_code=404)
    return row


def list_org_payouts(db: Session, *, organization_id: str) -> list[NovaFreightPayout]:
    return (
        db.query(NovaFreightPayout)
        .filter(NovaFreightPayout.organization_id == organization_id)
        .order_by(NovaFreightPayout.created_at.desc())
        .all()
    )


def adjust_payout(
    db: Session,
    payout_id: str,
    *,
    organization_id: str,
    carrier_payout_amount: Decimal,
    reason: str | None,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightPayout:
    row = get_payout_or_404(db, payout_id, organization_id=organization_id)
    if row.payout_status not in {"pending", "held", "approved"}:
        raise NovaFreightError("Payout can only be adjusted before it is ready or paid", status_code=409)
    shipment = get_shipment(db, row.shipment_id, organization_id=organization_id)
    previous = money(row.carrier_payout_amount)
    carrier = money(carrier_payout_amount)
    if carrier < money(0) or carrier > money(row.customer_amount):
        raise NovaFreightError("Carrier payout must be between 0 and the customer amount", status_code=409)
    margin = money(row.customer_amount - carrier)
    if money(row.customer_amount) != money(carrier + margin):
        raise NovaFreightError("Customer amount must equal carrier payout plus AMICOR margin", status_code=409)
    row.carrier_payout_amount = carrier
    row.amicor_margin_amount = margin
    row.adjustment_amount = money(carrier - previous)
    row.adjusted_by = actor_user_id
    row.adjusted_at = now()
    row.adjustment_reason = reason
    row.updated_at = now()
    shipment.carrier_payout_amount = carrier
    shipment.amicor_margin = margin
    _add_event(
        db,
        shipment,
        event_type="carrier_payout_adjusted",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"payout={row.payout_id} old={previous} new={carrier} reason={reason or ''}",
        payout_id=row.payout_id,
        carrier_id=row.carrier_id,
    )
    db.commit()
    db.refresh(row)
    return row


def hold_payout(
    db: Session,
    payout_id: str,
    *,
    organization_id: str,
    reason: str | None,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightPayout:
    row = get_payout_or_404(db, payout_id, organization_id=organization_id)
    if row.payout_status in {"paid", "void", "processing"}:
        raise NovaFreightError("Paid or processing payouts cannot be held", status_code=409)
    if row.payout_status == "held":
        return row
    shipment = get_shipment(db, row.shipment_id, organization_id=organization_id)
    row.payout_status = "held"
    row.hold_reason = reason
    row.updated_at = now()
    _add_event(
        db,
        shipment,
        event_type="carrier_payout_held",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"payout={row.payout_id} reason={reason or ''}",
        payout_id=row.payout_id,
        carrier_id=row.carrier_id,
    )
    db.commit()
    db.refresh(row)
    return row


def approve_payout(
    db: Session,
    payout_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightPayout:
    row = get_payout_or_404(db, payout_id, organization_id=organization_id)
    if row.payout_status in {"approved", "ready", "processing", "paid"}:
        return row
    if row.payout_status not in {"pending", "held"}:
        raise NovaFreightError("Only pending or held payouts can be approved", status_code=409)
    shipment = get_shipment(db, row.shipment_id, organization_id=organization_id)
    stamp = now()
    row.payout_status = "approved"
    row.approved_by = actor_user_id
    row.approved_at = stamp
    row.updated_at = stamp
    _add_event(
        db,
        shipment,
        event_type="carrier_payout_approved",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"payout={row.payout_id} amount={row.carrier_payout_amount}",
        payout_id=row.payout_id,
        carrier_id=row.carrier_id,
    )
    row.payout_status = "ready"
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row


def void_payout(
    db: Session,
    payout_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightPayout:
    row = get_payout_or_404(db, payout_id, organization_id=organization_id)
    if row.payout_status in {"paid", "processing"}:
        raise NovaFreightError("Paid or processing payouts cannot be voided", status_code=409)
    if row.payout_status == "void":
        return row
    shipment = get_shipment(db, row.shipment_id, organization_id=organization_id)
    row.payout_status = "void"
    row.updated_at = now()
    _add_event(
        db,
        shipment,
        event_type="carrier_payout_voided",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"payout={row.payout_id}",
        payout_id=row.payout_id,
        carrier_id=row.carrier_id,
    )
    db.commit()
    db.refresh(row)
    return row


def _remittance_text(
    payout: NovaFreightPayout,
    settlement: NovaFreightSettlement,
    carrier_name: str | None,
    completed_at,
) -> str:
    return (
        "AMICOR Nova remittance (SIMULATED / TEST — no money moved)\n"
        f"Settlement/remittance ID: {settlement.settlement_id}\n"
        f"Remittance reference: {settlement.remittance_reference}\n"
        f"Shipment ID: {payout.shipment_id}\n"
        f"Carrier: {carrier_name or payout.carrier_id}\n"
        f"Completed date: {completed_at}\n"
        f"Gross payout: {payout.carrier_payout_amount} {payout.currency}\n"
        f"Adjustments: {settlement.adjustments} {payout.currency}\n"
        f"Net payout: {settlement.net_amount} {payout.currency}\n"
        f"Payment status: {payout.payout_status}\n"
        f"Payment/reference ID: {payout.external_payout_reference}\n"
        f"Paid date: {payout.paid_at}\n"
        f"Notes: Simulated TEST payout. Stripe Connect live transfers were not used.\n"
    )


def execute_simulated_payout(
    db: Session,
    payout_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightPayout:
    assert_test_payout_mode()
    row = get_payout_or_404(db, payout_id, organization_id=organization_id)
    if row.payout_status == "paid":
        return row
    if row.payout_status in {"void", "held"}:
        raise NovaFreightError("Held or void payouts cannot execute until restored", status_code=409)
    if row.payout_status not in {"approved", "ready", "processing", "failed"}:
        raise NovaFreightError("Payout must be approved before TEST execution", status_code=409)
    shipment = get_shipment(db, row.shipment_id, organization_id=organization_id)
    stamp = now()
    if row.payout_status != "processing":
        row.payout_status = "processing"
        row.processing_at = stamp
        row.updated_at = stamp
        _add_event(
            db,
            shipment,
            event_type="carrier_payout_processing",
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            notes=f"payout={row.payout_id} mode=SIMULATED_TEST",
            payout_id=row.payout_id,
            carrier_id=row.carrier_id,
        )
    settlement = (
        db.query(NovaFreightSettlement)
        .filter(NovaFreightSettlement.payout_id == row.payout_id)
        .first()
    )
    created_settlement = settlement is None
    if settlement is None:
        settlement = NovaFreightSettlement(
            settlement_id=_new_settlement_id(),
            payout_id=row.payout_id,
            shipment_id=row.shipment_id,
            carrier_id=row.carrier_id,
            organization_id=organization_id,
            gross_carrier_amount=row.carrier_payout_amount,
            adjustments=row.adjustment_amount,
            net_amount=row.carrier_payout_amount,
            currency=row.currency,
            settlement_status="created",
            remittance_reference="NRM-" + row.payout_id.replace("NFPY-", ""),
            notes="SIMULATED / TEST remittance. No bank transfer occurred.",
            created_at=stamp,
            approved_at=row.approved_at,
        )
        db.add(settlement)
        db.flush()
        _add_event(
            db,
            shipment,
            event_type="settlement_created",
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            notes=f"settlement={settlement.settlement_id} payout={row.payout_id}",
            payout_id=row.payout_id,
            settlement_id=settlement.settlement_id,
            carrier_id=row.carrier_id,
        )
    row.payout_status = "paid"
    row.paid_at = now()
    row.payout_method = PAYOUT_METHOD_SIMULATED
    row.external_payout_reference = f"SIM-TEST-{row.payout_id}"
    row.stripe_transfer_id = None
    row.updated_at = now()
    wrote_remittance = not settlement.remittance_text
    settlement.settlement_status = "paid"
    settlement.paid_at = row.paid_at
    settlement.remittance_text = _remittance_text(
        row,
        settlement,
        _carrier_name(db, row.carrier_id),
        shipment.last_status_at or shipment.updated_at,
    )
    settlement.updated_at = now()
    _add_event(
        db,
        shipment,
        event_type="carrier_payout_paid",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"payout={row.payout_id} ref={row.external_payout_reference} simulated=true",
        payout_id=row.payout_id,
        settlement_id=settlement.settlement_id,
        carrier_id=row.carrier_id,
    )
    if created_settlement or wrote_remittance:
        _add_event(
            db,
            shipment,
            event_type="remittance_created",
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            notes=f"remittance={settlement.remittance_reference}",
            payout_id=row.payout_id,
            settlement_id=settlement.settlement_id,
            carrier_id=row.carrier_id,
        )
    db.commit()
    db.refresh(row)
    return row


def get_settlement_for_payout(db: Session, payout_id: str, *, organization_id: str) -> NovaFreightSettlement:
    get_payout_or_404(db, payout_id, organization_id=organization_id)
    row = db.query(NovaFreightSettlement).filter(NovaFreightSettlement.payout_id == payout_id).first()
    if row is None:
        raise NovaFreightError("Settlement not found", status_code=404)
    return row


def remittance_view(db: Session, payout_id: str, *, organization_id: str) -> dict:
    payout = get_payout_or_404(db, payout_id, organization_id=organization_id)
    settlement = get_settlement_for_payout(db, payout_id, organization_id=organization_id)
    shipment = get_shipment(db, payout.shipment_id, organization_id=organization_id)
    return {
        "brand": "AMICOR Nova",
        "mode": "SIMULATED_TEST",
        "money_moved": False,
        "settlement_id": settlement.settlement_id,
        "remittance_reference": settlement.remittance_reference,
        "shipment_id": payout.shipment_id,
        "carrier_id": payout.carrier_id,
        "carrier_name": _carrier_name(db, payout.carrier_id),
        "gross_payout": settlement.gross_carrier_amount,
        "adjustments": settlement.adjustments,
        "net_payout": settlement.net_amount,
        "currency": payout.currency,
        "payment_status": payout.payout_status,
        "payment_reference": payout.external_payout_reference,
        "paid_at": payout.paid_at,
        "completed_at": shipment.last_status_at or shipment.updated_at,
        "notes": settlement.notes,
        "remittance_text": settlement.remittance_text,
    }


def finance_board_row(db: Session, payout: NovaFreightPayout) -> dict:
    shipment = get_shipment(db, payout.shipment_id, organization_id=payout.organization_id)
    settlement = (
        db.query(NovaFreightSettlement)
        .filter(NovaFreightSettlement.payout_id == payout.payout_id)
        .first()
    )
    return {
        "payout_id": payout.payout_id,
        "shipment_id": payout.shipment_id,
        "carrier_id": payout.carrier_id,
        "carrier_name": _carrier_name(db, payout.carrier_id),
        "customer_amount": payout.customer_amount,
        "carrier_payout_amount": payout.carrier_payout_amount,
        "amicor_margin_amount": payout.amicor_margin_amount,
        "invoice_id": payout.invoice_id,
        "payout_status": payout.payout_status,
        "settlement_status": settlement.settlement_status if settlement else None,
        "has_pickup_proof": bool(shipment.proof_of_pickup_ref),
        "has_delivery_proof": bool(shipment.proof_of_delivery_ref),
        "proof_warning": payout.proof_warning,
        "completed_at": shipment.last_status_at or shipment.updated_at,
        "paid_at": payout.paid_at,
        "external_payout_reference": payout.external_payout_reference,
        "payout_method": payout.payout_method,
    }


def carrier_earnings(
    db: Session,
    *,
    organization_id: str,
    carrier_ids: list[str],
) -> dict:
    if not carrier_ids:
        return {"pending_total": money(0), "approved_total": money(0), "paid_total": money(0), "rows": []}
    rows = (
        db.query(NovaFreightPayout)
        .filter(
            NovaFreightPayout.organization_id == organization_id,
            NovaFreightPayout.carrier_id.in_(carrier_ids),
            NovaFreightPayout.payout_status != "void",
        )
        .order_by(NovaFreightPayout.created_at.desc())
        .all()
    )
    out = []
    pending = money(0)
    approved = money(0)
    paid = money(0)
    for payout in rows:
        shipment = get_shipment(db, payout.shipment_id, organization_id=organization_id)
        settlement = (
            db.query(NovaFreightSettlement)
            .filter(NovaFreightSettlement.payout_id == payout.payout_id)
            .first()
        )
        if payout.payout_status in {"pending", "held", "failed"}:
            pending += money(payout.carrier_payout_amount)
        elif payout.payout_status in {"approved", "ready", "processing"}:
            approved += money(payout.carrier_payout_amount)
        elif payout.payout_status == "paid":
            paid += money(payout.carrier_payout_amount)
        out.append(
            {
                "shipment_id": payout.shipment_id,
                "payout_id": payout.payout_id,
                "completed_at": shipment.last_status_at or shipment.updated_at,
                "pickup_city": shipment.pickup_city,
                "pickup_state": shipment.pickup_state,
                "delivery_city": shipment.delivery_city,
                "delivery_state": shipment.delivery_state,
                "carrier_payout_amount": payout.carrier_payout_amount,
                "payout_status": payout.payout_status,
                "remittance_reference": settlement.remittance_reference if settlement else None,
                "paid_at": payout.paid_at,
            }
        )
    return {
        "pending_total": pending,
        "approved_total": approved,
        "paid_total": paid,
        "rows": out,
    }
