"""Read-only accounting aggregates from existing canonical sources."""
from __future__ import annotations

from app.auth import (
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_SUPERVISOR,
    UserContext,
    normalize_role,
)
from app.core.nova.accounting.schemas import NovaAccountingMetric, NovaAccountingSummaryOut
from app.core.nova.freight.money import money
from app.core.nova.freight.ops import UNPAID_INVOICE_STATUSES
from sqlalchemy.orm import Session

ACCOUNTING_ROLES = {
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
}


class NovaAccountingError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _usd(value: object) -> float:
    return float(money(value))


def _metric(
    *,
    key: str,
    label: str,
    definition: str,
    state: str,
    amount_usd: float | None = None,
    count: int | None = None,
    status: str = "ok",
) -> NovaAccountingMetric:
    return NovaAccountingMetric(
        key=key,
        label=label,
        definition=definition,
        state=state,  # type: ignore[arg-type]
        amount_usd=amount_usd,
        count=count,
        status=status,  # type: ignore[arg-type]
    )


def _unavailable(key: str, label: str, definition: str, state: str) -> NovaAccountingMetric:
    return _metric(
        key=key,
        label=label,
        definition=definition,
        state="unavailable",
        status="unavailable",
    )


def _confirmed_customer_payments(db: Session, organization_id: str) -> NovaAccountingMetric:
    from app.modules.payments.models import PAYMENT_SUCCEEDED, AmicorCustomerPayment

    rows = (
        db.query(AmicorCustomerPayment.amount_minor)
        .filter(
            AmicorCustomerPayment.organization_id == organization_id,
            AmicorCustomerPayment.payment_status == PAYMENT_SUCCEEDED,
        )
        .all()
    )
    total = money(0)
    for (amount_minor,) in rows:
        total = money(total + (money(int(amount_minor or 0)) / money(100)))
    return _metric(
        key="confirmed_customer_payments",
        label="Confirmed customer payments",
        definition="Sum of amicor_customer_payments.amount_minor where payment_status=succeeded, same organization. Stripe TEST ledger only. Not calculated trip shares and not Freight invoices.",
        state="confirmed",
        amount_usd=_usd(total),
        count=len(rows),
    )


def _pending_customer_payments(db: Session, organization_id: str) -> NovaAccountingMetric:
    from app.modules.payments.models import PAYMENT_PENDING, AmicorCustomerPayment

    rows = (
        db.query(AmicorCustomerPayment.amount_minor)
        .filter(
            AmicorCustomerPayment.organization_id == organization_id,
            AmicorCustomerPayment.payment_status == PAYMENT_PENDING,
        )
        .all()
    )
    total = money(0)
    for (amount_minor,) in rows:
        total = money(total + (money(int(amount_minor or 0)) / money(100)))
    return _metric(
        key="pending_customer_payments",
        label="Pending customer payments",
        definition="Sum of amicor_customer_payments.amount_minor where payment_status=pending, same organization. Stripe TEST ledger only. Not treated as collected.",
        state="pending",
        amount_usd=_usd(total),
        count=len(rows),
    )


def _completed_trip_calculated(db: Session, organization_id: str) -> tuple[NovaAccountingMetric, NovaAccountingMetric]:
    from app.modules.health_isf.financial_engine import TripFinancialEngine

    summary = TripFinancialEngine.get_admin_revenue_summary(db, organization_id=organization_id)
    ride_total = _usd(summary.get("ride_revenue_total_usd") or 0)
    platform_total = _usd(summary.get("platform_revenue_total_usd") or 0)
    sample = int(summary.get("completed_trip_count") or 0)
    ride = _metric(
        key="completed_trip_calculated_ride_totals",
        label="Completed-trip calculated ride totals",
        definition="Existing GET /api/health-isf/operations/admin-revenue ride_revenue_total_usd. Calculated on trip completion from HealthISFTripFinancialRecord. Latest 1,000 records. Not confirmed collected cash.",
        state="calculated",
        amount_usd=ride_total,
        count=sample,
    )
    platform = _metric(
        key="completed_trip_calculated_platform_share",
        label="Completed-trip calculated platform share",
        definition="Existing admin-revenue platform_revenue_total_usd from the same completed-trip financial records. Not confirmed collected cash and not combined with Stripe payments.",
        state="calculated",
        amount_usd=platform_total,
        count=sample,
    )
    return ride, platform


def _freight_paid_invoices(db: Session, organization_id: str) -> NovaAccountingMetric:
    from app.core.nova.freight.ops import ops_summary

    summary = ops_summary(db, organization_id=organization_id)
    return _metric(
        key="freight_paid_invoice_totals",
        label="Freight paid invoice totals",
        definition="Existing Freight ops_summary.gross_customer_revenue: sum of nova_freight_invoices.total_amount where invoice_status=paid. Stripe TEST. Not Ride/Delivery payments.",
        state="confirmed",
        amount_usd=_usd(summary.get("gross_customer_revenue") or 0),
        count=int(summary.get("paid_invoices") or 0),
    )


def _freight_unpaid_invoices(db: Session, organization_id: str) -> NovaAccountingMetric:
    from app.core.nova.freight.models import NovaFreightInvoice

    rows = (
        db.query(NovaFreightInvoice.total_amount)
        .filter(
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.invoice_status.in_(UNPAID_INVOICE_STATUSES),
        )
        .all()
    )
    total = money(0)
    for (amount,) in rows:
        total = money(total + money(amount))
    return _metric(
        key="freight_unpaid_invoice_totals",
        label="Freight unpaid invoice totals",
        definition="Sum of nova_freight_invoices.total_amount where invoice_status is draft, ready, payment_pending, or failed (Freight UNPAID_INVOICE_STATUSES). Not treated as collected.",
        state="pending",
        amount_usd=_usd(total),
        count=len(rows),
    )


def _safe(reader, db: Session, organization_id: str, *, key: str, label: str, state: str, definition: str) -> NovaAccountingMetric:
    try:
        return reader(db, organization_id)
    except Exception:
        return _unavailable(key, label, definition, state)


def summary(db: Session, *, organization_id: str, user: UserContext) -> NovaAccountingSummaryOut:
    if normalize_role(user.role) not in ACCOUNTING_ROLES:
        raise NovaAccountingError("Accounting summary is limited to finance-authorized Nova roles", status_code=403)

    metrics: list[NovaAccountingMetric] = []
    metrics.append(
        _safe(
            _confirmed_customer_payments,
            db,
            organization_id,
            key="confirmed_customer_payments",
            label="Confirmed customer payments",
            state="confirmed",
            definition="amicor_customer_payments succeeded totals",
        )
    )
    metrics.append(
        _safe(
            _pending_customer_payments,
            db,
            organization_id,
            key="pending_customer_payments",
            label="Pending customer payments",
            state="pending",
            definition="amicor_customer_payments pending totals",
        )
    )
    try:
        ride, platform = _completed_trip_calculated(db, organization_id)
        metrics.extend([ride, platform])
    except Exception:
        metrics.append(
            _unavailable(
                "completed_trip_calculated_ride_totals",
                "Completed-trip calculated ride totals",
                "Existing admin-revenue ride_revenue_total_usd",
                "calculated",
            )
        )
        metrics.append(
            _unavailable(
                "completed_trip_calculated_platform_share",
                "Completed-trip calculated platform share",
                "Existing admin-revenue platform_revenue_total_usd",
                "calculated",
            )
        )
    metrics.append(
        _safe(
            _freight_paid_invoices,
            db,
            organization_id,
            key="freight_paid_invoice_totals",
            label="Freight paid invoice totals",
            state="confirmed",
            definition="Freight ops_summary.gross_customer_revenue",
        )
    )
    metrics.append(
        _safe(
            _freight_unpaid_invoices,
            db,
            organization_id,
            key="freight_unpaid_invoice_totals",
            label="Freight unpaid invoice totals",
            state="pending",
            definition="Freight unpaid invoice totals",
        )
    )
    return NovaAccountingSummaryOut(organization_id=organization_id, metrics=metrics)
