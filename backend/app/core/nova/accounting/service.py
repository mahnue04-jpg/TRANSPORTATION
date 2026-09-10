"""Read-only accounting aggregates from existing canonical sources."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

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
from app.core.nova.freight.money import from_minor_units, money
from app.core.nova.freight.ops import UNPAID_INVOICE_STATUSES
from app.helpers import now

ACCOUNTING_ROLES = {
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
}

WINDOWS = ("all", "30d", "7d")
WINDOW_DAYS = {"all": None, "30d": 30, "7d": 7}
WINDOW_LABELS = {"all": "All time", "30d": "Last 30 days", "7d": "Last 7 days"}
ALL_TIME_ONLY_LABEL = "All time only"


class NovaAccountingError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def parse_window(value: str | None) -> str:
    key = (value or "all").strip().lower()
    if key not in WINDOWS:
        raise NovaAccountingError("Unsupported accounting window", status_code=400)
    return key


def window_cutoff(window: str, *, at: datetime | None = None) -> datetime | None:
    days = WINDOW_DAYS[window]
    if days is None:
        return None
    stamp = at or now()
    return stamp - timedelta(days=days)


def window_display(window: str, *, timestamp_field: str | None) -> tuple[str, bool]:
    """Return (window_label, window_supported). Unfilterable metrics stay All time only."""
    if not timestamp_field:
        return ALL_TIME_ONLY_LABEL, False
    return WINDOW_LABELS[window], True


def _usd(value: object) -> float:
    return float(money(value))


def _metric(
    *,
    key: str,
    label: str,
    definition: str,
    state: str,
    window: str,
    timestamp_field: str | None,
    source_note: str,
    amount_usd: float | None = None,
    count: int | None = None,
    status: str = "ok",
    complete: bool = True,
) -> NovaAccountingMetric:
    label_text, supported = window_display(window, timestamp_field=timestamp_field)
    return NovaAccountingMetric(
        key=key,
        label=label,
        definition=definition,
        state=state,  # type: ignore[arg-type]
        amount_usd=amount_usd,
        count=count,
        status=status,  # type: ignore[arg-type]
        window=window,  # type: ignore[arg-type]
        window_supported=supported,
        window_label=label_text,
        timestamp_field=timestamp_field,
        source_note=source_note,
        complete=complete,
    )


def _unavailable(
    key: str,
    label: str,
    definition: str,
    state: str,
    window: str,
    timestamp_field: str | None,
    source_note: str,
) -> NovaAccountingMetric:
    return _metric(
        key=key,
        label=label,
        definition=definition,
        state="unavailable",
        window=window,
        timestamp_field=timestamp_field,
        source_note=source_note,
        status="unavailable",
        complete=False,
    )


def _sum_count(db: Session, amount_col, *filters) -> tuple[object, int]:
    total, count = (
        db.query(func.coalesce(func.sum(amount_col), 0), func.count())
        .filter(*filters)
        .one()
    )
    return total, int(count or 0)


def _confirmed_customer_payments(
    db: Session, organization_id: str, window: str, cutoff: datetime | None
) -> NovaAccountingMetric:
    from app.modules.payments.models import PAYMENT_SUCCEEDED, AmicorCustomerPayment

    timestamp_field = "amicor_customer_payments.paid_at"
    filters = [
        AmicorCustomerPayment.organization_id == organization_id,
        AmicorCustomerPayment.payment_status == PAYMENT_SUCCEEDED,
    ]
    query_filters = list(filters)
    if cutoff is not None:
        query_filters.extend(
            [AmicorCustomerPayment.paid_at.isnot(None), AmicorCustomerPayment.paid_at >= cutoff]
        )
    total_minor, count = _sum_count(db, AmicorCustomerPayment.amount_minor, *query_filters)
    return _metric(
        key="confirmed_customer_payments",
        label="Confirmed customer payments",
        definition=(
            "SQL sum of amicor_customer_payments.amount_minor where payment_status=succeeded, "
            "same organization, all eligible rows. Window uses paid_at. Stripe TEST ledger only. "
            "Not calculated trip shares and not Freight invoices."
        ),
        state="confirmed",
        window=window,
        timestamp_field=timestamp_field,
        source_note="Confirmed Stripe TEST cash. Separate from calculated trip totals and Freight invoices.",
        amount_usd=_usd(from_minor_units(int(total_minor or 0))),
        count=count,
    )


def _pending_customer_payments(
    db: Session, organization_id: str, window: str, cutoff: datetime | None
) -> NovaAccountingMetric:
    from app.modules.payments.models import PAYMENT_PENDING, AmicorCustomerPayment

    timestamp_field = "amicor_customer_payments.created_at"
    filters = [
        AmicorCustomerPayment.organization_id == organization_id,
        AmicorCustomerPayment.payment_status == PAYMENT_PENDING,
    ]
    if cutoff is not None:
        filters.extend(
            [AmicorCustomerPayment.created_at.isnot(None), AmicorCustomerPayment.created_at >= cutoff]
        )
    total_minor, count = _sum_count(db, AmicorCustomerPayment.amount_minor, *filters)
    return _metric(
        key="pending_customer_payments",
        label="Pending customer payments",
        definition=(
            "SQL sum of amicor_customer_payments.amount_minor where payment_status=pending, "
            "same organization, all eligible rows. Window uses created_at. Stripe TEST. Not collected."
        ),
        state="pending",
        window=window,
        timestamp_field=timestamp_field,
        source_note="Pending Stripe TEST PaymentIntents. Not treated as collected cash.",
        amount_usd=_usd(from_minor_units(int(total_minor or 0))),
        count=count,
    )


def _completed_trip_ride(
    db: Session, organization_id: str, window: str, cutoff: datetime | None
) -> NovaAccountingMetric:
    from app.modules.health_isf.models import HealthISFTripFinancialRecord

    timestamp_field = "health_isf_trip_financial_records.created_at"
    filters = [HealthISFTripFinancialRecord.organization_id == organization_id]
    if cutoff is not None:
        filters.extend(
            [
                HealthISFTripFinancialRecord.created_at.isnot(None),
                HealthISFTripFinancialRecord.created_at >= cutoff,
            ]
        )
    total, count = _sum_count(db, HealthISFTripFinancialRecord.ride_price_usd, *filters)
    return _metric(
        key="completed_trip_calculated_ride_totals",
        label="Completed-trip calculated ride totals",
        definition=(
            "SQL sum of health_isf_trip_financial_records.ride_price_usd for the organization. "
            "All eligible completion records; not the admin-revenue 1,000-row display cap. "
            "Window uses created_at (record written at trip completion). Not confirmed collected cash."
        ),
        state="calculated",
        window=window,
        timestamp_field=timestamp_field,
        source_note="Calculated at trip completion. Not collected cash. Not combined with Stripe payments.",
        amount_usd=_usd(total),
        count=count,
    )


def _completed_trip_platform(
    db: Session, organization_id: str, window: str, cutoff: datetime | None
) -> NovaAccountingMetric:
    from app.modules.health_isf.models import HealthISFTripFinancialRecord

    timestamp_field = "health_isf_trip_financial_records.created_at"
    filters = [HealthISFTripFinancialRecord.organization_id == organization_id]
    if cutoff is not None:
        filters.extend(
            [
                HealthISFTripFinancialRecord.created_at.isnot(None),
                HealthISFTripFinancialRecord.created_at >= cutoff,
            ]
        )
    total, count = _sum_count(db, HealthISFTripFinancialRecord.platform_revenue_usd, *filters)
    return _metric(
        key="completed_trip_calculated_platform_share",
        label="Completed-trip calculated platform share",
        definition=(
            "SQL sum of health_isf_trip_financial_records.platform_revenue_usd for the organization. "
            "All eligible completion records; not the admin-revenue 1,000-row display cap. "
            "Window uses created_at. Not confirmed collected cash."
        ),
        state="calculated",
        window=window,
        timestamp_field=timestamp_field,
        source_note="Calculated platform share at trip completion. Not collected cash. TEST/internal ledger.",
        amount_usd=_usd(total),
        count=count,
    )


def _freight_paid_invoices(
    db: Session, organization_id: str, window: str, cutoff: datetime | None
) -> NovaAccountingMetric:
    from app.core.nova.freight.models import NovaFreightInvoice

    timestamp_field = "nova_freight_invoices.paid_at"
    filters = [
        NovaFreightInvoice.organization_id == organization_id,
        NovaFreightInvoice.invoice_status == "paid",
    ]
    if cutoff is not None:
        filters.extend([NovaFreightInvoice.paid_at.isnot(None), NovaFreightInvoice.paid_at >= cutoff])
    total, count = _sum_count(db, NovaFreightInvoice.total_amount, *filters)
    return _metric(
        key="freight_paid_invoice_totals",
        label="Freight paid invoice totals",
        definition=(
            "SQL sum of nova_freight_invoices.total_amount where invoice_status=paid, same organization, "
            "all eligible rows. Window uses paid_at. Stripe TEST. Not Ride/Delivery payments."
        ),
        state="confirmed",
        window=window,
        timestamp_field=timestamp_field,
        source_note="Freight invoices marked paid. Stripe TEST. Separate from Ride/Delivery payments.",
        amount_usd=_usd(total),
        count=count,
    )


def _freight_unpaid_invoices(
    db: Session, organization_id: str, window: str, cutoff: datetime | None
) -> NovaAccountingMetric:
    from app.core.nova.freight.models import NovaFreightInvoice

    timestamp_field = "nova_freight_invoices.created_at"
    filters = [
        NovaFreightInvoice.organization_id == organization_id,
        NovaFreightInvoice.invoice_status.in_(UNPAID_INVOICE_STATUSES),
    ]
    if cutoff is not None:
        filters.extend(
            [NovaFreightInvoice.created_at.isnot(None), NovaFreightInvoice.created_at >= cutoff]
        )
    total, count = _sum_count(db, NovaFreightInvoice.total_amount, *filters)
    return _metric(
        key="freight_unpaid_invoice_totals",
        label="Freight unpaid invoice totals",
        definition=(
            "SQL sum of nova_freight_invoices.total_amount where invoice_status is draft, ready, "
            "payment_pending, or failed. All eligible rows. Window uses created_at. Not collected."
        ),
        state="pending",
        window=window,
        timestamp_field=timestamp_field,
        source_note="Unpaid Freight invoices (draft, ready, payment_pending, failed). Not collected.",
        amount_usd=_usd(total),
        count=count,
    )


Reader = Callable[[Session, str, str, datetime | None], NovaAccountingMetric]


def _safe(
    reader: Reader,
    db: Session,
    organization_id: str,
    window: str,
    cutoff: datetime | None,
    *,
    key: str,
    label: str,
    state: str,
    definition: str,
    timestamp_field: str | None,
    source_note: str,
) -> NovaAccountingMetric:
    try:
        return reader(db, organization_id, window, cutoff)
    except Exception:
        return _unavailable(key, label, definition, state, window, timestamp_field, source_note)


def summary(
    db: Session, *, organization_id: str, user: UserContext, window: str | None = None
) -> NovaAccountingSummaryOut:
    if normalize_role(user.role) not in ACCOUNTING_ROLES:
        raise NovaAccountingError("Accounting summary is limited to finance-authorized Nova roles", status_code=403)

    resolved = parse_window(window)
    cutoff = window_cutoff(resolved)
    metrics: list[NovaAccountingMetric] = []
    metrics.append(
        _safe(
            _confirmed_customer_payments,
            db,
            organization_id,
            resolved,
            cutoff,
            key="confirmed_customer_payments",
            label="Confirmed customer payments",
            state="confirmed",
            definition="amicor_customer_payments succeeded totals",
            timestamp_field="amicor_customer_payments.paid_at",
            source_note="Confirmed Stripe TEST cash.",
        )
    )
    metrics.append(
        _safe(
            _pending_customer_payments,
            db,
            organization_id,
            resolved,
            cutoff,
            key="pending_customer_payments",
            label="Pending customer payments",
            state="pending",
            definition="amicor_customer_payments pending totals",
            timestamp_field="amicor_customer_payments.created_at",
            source_note="Pending Stripe TEST amounts.",
        )
    )
    metrics.append(
        _safe(
            _completed_trip_ride,
            db,
            organization_id,
            resolved,
            cutoff,
            key="completed_trip_calculated_ride_totals",
            label="Completed-trip calculated ride totals",
            state="calculated",
            definition="Completed-trip ride_price_usd totals",
            timestamp_field="health_isf_trip_financial_records.created_at",
            source_note="Calculated at trip completion.",
        )
    )
    metrics.append(
        _safe(
            _completed_trip_platform,
            db,
            organization_id,
            resolved,
            cutoff,
            key="completed_trip_calculated_platform_share",
            label="Completed-trip calculated platform share",
            state="calculated",
            definition="Completed-trip platform_revenue_usd totals",
            timestamp_field="health_isf_trip_financial_records.created_at",
            source_note="Calculated platform share at completion.",
        )
    )
    metrics.append(
        _safe(
            _freight_paid_invoices,
            db,
            organization_id,
            resolved,
            cutoff,
            key="freight_paid_invoice_totals",
            label="Freight paid invoice totals",
            state="confirmed",
            definition="Freight paid invoice totals",
            timestamp_field="nova_freight_invoices.paid_at",
            source_note="Freight invoices marked paid. Stripe TEST.",
        )
    )
    metrics.append(
        _safe(
            _freight_unpaid_invoices,
            db,
            organization_id,
            resolved,
            cutoff,
            key="freight_unpaid_invoice_totals",
            label="Freight unpaid invoice totals",
            state="pending",
            definition="Freight unpaid invoice totals",
            timestamp_field="nova_freight_invoices.created_at",
            source_note="Unpaid Freight invoices. Not collected.",
        )
    )
    return NovaAccountingSummaryOut(
        organization_id=organization_id,
        window=resolved,  # type: ignore[arg-type]
        window_label=WINDOW_LABELS[resolved],
        window_cutoff_utc=cutoff.isoformat() if cutoff else None,
        metrics=metrics,
    )
