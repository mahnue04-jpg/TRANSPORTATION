"""Read-only monthly accounting trends. Does not change summary or aging calculations."""
from __future__ import annotations

from calendar import month_abbr
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.auth import UserContext, normalize_role
from app.core.nova.accounting.schemas import (
    NovaAccountingTrendsOut,
    NovaTrendCurrencySlice,
    NovaTrendGroup,
    NovaTrendMonth,
    NovaTrendStream,
)
from app.core.nova.accounting.service import ACCOUNTING_ROLES, NovaAccountingError
from app.core.nova.freight.money import from_minor_units, money
from app.core.nova.freight.ops import UNPAID_INVOICE_STATUSES
from app.helpers import now

TREND_MONTHS = (3, 6, 12)
FREIGHT_STATUS_LABELS = {
    "draft": "Freight draft invoices",
    "ready": "Freight ready invoices",
    "payment_pending": "Freight payment-pending invoices",
    "failed": "Freight failed invoices",
}


def parse_months(value: int | str | None) -> int:
    if value is None or value == "":
        return 12
    try:
        months = int(value)
    except (TypeError, ValueError) as exc:
        raise NovaAccountingError("Unsupported trends window", status_code=400) from exc
    if months not in TREND_MONTHS:
        raise NovaAccountingError("Unsupported trends window", status_code=400)
    return months


def utc_month_start(stamp: datetime) -> datetime:
    aware = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(start: datetime, delta: int) -> datetime:
    year = start.year
    month = start.month + delta
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return start.replace(year=year, month=month)


def month_key(stamp: datetime | None) -> str | None:
    if stamp is None:
        return None
    start = utc_month_start(stamp)
    return f"{start.year:04d}-{start.month:02d}"


def month_window(as_of: datetime, months: int) -> tuple[datetime, list[str]]:
    current = utc_month_start(as_of)
    first = add_months(current, -(months - 1))
    keys = []
    cursor = first
    for _ in range(months):
        keys.append(f"{cursor.year:04d}-{cursor.month:02d}")
        cursor = add_months(cursor, 1)
    return first, keys


def month_label(key: str, *, month_to_date: bool) -> str:
    year, month = key.split("-")
    text = f"{month_abbr[int(month)]} {year}"
    if month_to_date:
        return f"{text} (Month to date)"
    return text


def _normalize_currency(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _empty_months(keys: list[str], current_key: str) -> list[NovaTrendMonth]:
    return [
        NovaTrendMonth(
            month=key,
            label=month_label(key, month_to_date=key == current_key),
            month_to_date=key == current_key,
            count=0,
            amount=0.0,
        )
        for key in keys
    ]


def _aggregate(
    rows: list[tuple[datetime | None, object, object]],
    *,
    keys: list[str],
    current_key: str,
    first: datetime,
    as_of: datetime,
    amount_mode: str,
) -> list[NovaTrendCurrencySlice]:
    grouped: dict[str, dict] = {}
    for stamp, raw_amount, raw_currency in rows:
        currency = _normalize_currency(raw_currency)
        slot = grouped.setdefault(
            currency,
            {
                "missing": 0,
                "months": {key: {"count": 0, "amount": money(0)} for key in keys},
            },
        )
        if stamp is None:
            slot["missing"] += 1
            continue
        key = month_key(stamp)
        if key is None or key not in slot["months"]:
            continue
        aware = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        aware = aware.astimezone(timezone.utc)
        if aware < first or aware > as_of:
            continue
        if raw_amount is None:
            continue
        if amount_mode == "minor":
            amount = from_minor_units(int(raw_amount))
        else:
            amount = money(Decimal(str(raw_amount)))
        slot["months"][key]["count"] += 1
        slot["months"][key]["amount"] = money(slot["months"][key]["amount"] + amount)
    if not grouped:
        return [
            NovaTrendCurrencySlice(
                currency="USD",
                excluded_missing_timestamp_count=0,
                months=_empty_months(keys, current_key),
            )
        ]
    slices = []
    for currency, slot in grouped.items():
        months = []
        for key in keys:
            bucket = slot["months"][key]
            months.append(
                NovaTrendMonth(
                    month=key,
                    label=month_label(key, month_to_date=key == current_key),
                    month_to_date=key == current_key,
                    count=int(bucket["count"]),
                    amount=float(money(bucket["amount"])),
                )
            )
        slices.append(
            NovaTrendCurrencySlice(
                currency=currency or "",
                excluded_missing_timestamp_count=int(slot["missing"]),
                months=months,
            )
        )
    slices.sort(key=lambda row: row.currency)
    return slices


def _unavailable_group(key: str, label: str, state: str, cohort: str, timestamp_field: str, source_note: str) -> NovaTrendGroup:
    return NovaTrendGroup(
        key=key,
        label=label,
        status="unavailable",
        state="unavailable",
        cohort=cohort,
        timestamp_field=timestamp_field,
        source_note=source_note,
        currencies=[],
    )


def _unavailable_stream(key: str, label: str, group: NovaTrendGroup) -> NovaTrendStream:
    return NovaTrendStream(key=key, label=label, status="unavailable", groups=[group])


def _customer_confirmed(db: Session, organization_id: str, keys: list[str], current_key: str, first: datetime, as_of: datetime) -> NovaTrendGroup:
    from app.modules.payments.models import PAYMENT_SUCCEEDED, AmicorCustomerPayment

    rows = (
        db.query(AmicorCustomerPayment.paid_at, AmicorCustomerPayment.amount_minor, AmicorCustomerPayment.currency)
        .filter(
            AmicorCustomerPayment.organization_id == organization_id,
            AmicorCustomerPayment.organization_id.isnot(None),
            AmicorCustomerPayment.payment_status == PAYMENT_SUCCEEDED,
        )
        .all()
    )
    return NovaTrendGroup(
        key="confirmed_customer_payments",
        label="Confirmed customer payments",
        state="confirmed",
        cohort="paid_at_month",
        timestamp_field="amicor_customer_payments.paid_at",
        stripe_mode="TEST",
        source_note="Succeeded Stripe TEST payments grouped by paid_at UTC month. Not calculated trip totals and not Freight invoices.",
        currencies=_aggregate(list(rows), keys=keys, current_key=current_key, first=first, as_of=as_of, amount_mode="minor"),
    )


def _customer_pending(db: Session, organization_id: str, keys: list[str], current_key: str, first: datetime, as_of: datetime) -> NovaTrendGroup:
    from app.modules.payments.models import PAYMENT_PENDING, AmicorCustomerPayment

    rows = (
        db.query(AmicorCustomerPayment.created_at, AmicorCustomerPayment.amount_minor, AmicorCustomerPayment.currency)
        .filter(
            AmicorCustomerPayment.organization_id == organization_id,
            AmicorCustomerPayment.organization_id.isnot(None),
            AmicorCustomerPayment.payment_status == PAYMENT_PENDING,
        )
        .all()
    )
    return NovaTrendGroup(
        key="current_pending_customer_payments",
        label="Current pending payments by creation month",
        state="pending",
        cohort="current_pending_by_created_month",
        timestamp_field="amicor_customer_payments.created_at",
        stripe_mode="TEST",
        source_note="Currently pending Stripe TEST PaymentIntents grouped by created_at UTC month. This is a current pending cohort, not a historical month-end balance.",
        currencies=_aggregate(list(rows), keys=keys, current_key=current_key, first=first, as_of=as_of, amount_mode="minor"),
    )


def _trip_totals(db: Session, organization_id: str, keys: list[str], current_key: str, first: datetime, as_of: datetime, *, field: str, key: str, label: str) -> NovaTrendGroup:
    from app.modules.health_isf.models import HealthISFTripFinancialRecord

    column = getattr(HealthISFTripFinancialRecord, field)
    rows = (
        db.query(HealthISFTripFinancialRecord.created_at, column)
        .filter(
            HealthISFTripFinancialRecord.organization_id == organization_id,
            HealthISFTripFinancialRecord.organization_id.isnot(None),
        )
        .all()
    )
    typed = [(stamp, amount, "USD") for stamp, amount in rows]
    return NovaTrendGroup(
        key=key,
        label=label,
        state="calculated",
        cohort="created_at_month",
        timestamp_field="health_isf_trip_financial_records.created_at",
        source_note=f"Calculated {field} grouped by created_at UTC month. Not collected cash. Currency is USD from the canonical field.",
        currencies=_aggregate(typed, keys=keys, current_key=current_key, first=first, as_of=as_of, amount_mode="money"),
    )


def _freight_paid(db: Session, organization_id: str, keys: list[str], current_key: str, first: datetime, as_of: datetime) -> NovaTrendGroup:
    from app.core.nova.freight.models import NovaFreightInvoice

    rows = (
        db.query(NovaFreightInvoice.paid_at, NovaFreightInvoice.total_amount, NovaFreightInvoice.currency)
        .filter(
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.organization_id.isnot(None),
            NovaFreightInvoice.invoice_status == "paid",
        )
        .all()
    )
    return NovaTrendGroup(
        key="freight_paid_invoice_totals",
        label="Freight paid invoice totals",
        state="confirmed",
        cohort="paid_at_month",
        timestamp_field="nova_freight_invoices.paid_at",
        stripe_mode="TEST",
        source_note="Paid Freight invoices grouped by paid_at UTC month. Stripe TEST. Not Ride/Delivery payments.",
        currencies=_aggregate(list(rows), keys=keys, current_key=current_key, first=first, as_of=as_of, amount_mode="money"),
    )


def _freight_unpaid(db: Session, organization_id: str, keys: list[str], current_key: str, first: datetime, as_of: datetime, status: str) -> NovaTrendGroup:
    from app.core.nova.freight.models import NovaFreightInvoice

    rows = (
        db.query(NovaFreightInvoice.created_at, NovaFreightInvoice.total_amount, NovaFreightInvoice.currency)
        .filter(
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.organization_id.isnot(None),
            NovaFreightInvoice.invoice_status == status,
        )
        .all()
    )
    note = (
        f"Currently unpaid Freight invoices with invoice_status={status}, grouped by created_at UTC month. "
        "This is a current unpaid cohort, not a historical month-end balance. Stripe TEST."
    )
    if status == "draft":
        note = "Draft Freight invoices are not collectible. Current draft cohort grouped by created_at UTC month. Not a historical month-end balance."
    return NovaTrendGroup(
        key=f"freight_{status}",
        label=FREIGHT_STATUS_LABELS[status],
        state="pending",
        cohort="current_unpaid_by_created_month",
        timestamp_field="nova_freight_invoices.created_at",
        collectible=False,
        stripe_mode="TEST",
        source_note=note,
        currencies=_aggregate(list(rows), keys=keys, current_key=current_key, first=first, as_of=as_of, amount_mode="money"),
    )


def _safe_group(reader, *args, fallback: NovaTrendGroup, **kwargs) -> NovaTrendGroup:
    try:
        return reader(*args, **kwargs)
    except Exception:
        return fallback


def _stream(key: str, label: str, group: NovaTrendGroup) -> NovaTrendStream:
    return NovaTrendStream(key=key, label=label, status=group.status, groups=[group])


def trends(db: Session, *, organization_id: str, user: UserContext, months: int | str | None = None) -> NovaAccountingTrendsOut:
    if normalize_role(user.role) not in ACCOUNTING_ROLES:
        raise NovaAccountingError("Accounting trends are limited to finance-authorized Nova roles", status_code=403)
    resolved = parse_months(months)
    as_of = now()
    first, keys = month_window(as_of, resolved)
    current_key = month_key(as_of) or keys[-1]
    streams: list[NovaTrendStream] = []
    streams.append(
        _stream(
            "confirmed_customer_payments",
            "Confirmed customer payments",
            _safe_group(
                _customer_confirmed,
                db,
                organization_id,
                keys,
                current_key,
                first,
                as_of,
                fallback=_unavailable_group(
                    "confirmed_customer_payments",
                    "Confirmed customer payments",
                    "confirmed",
                    "paid_at_month",
                    "amicor_customer_payments.paid_at",
                    "Confirmed customer payment trends are unavailable.",
                ),
            ),
        )
    )
    streams.append(
        _stream(
            "current_pending_customer_payments",
            "Current pending payments by creation month",
            _safe_group(
                _customer_pending,
                db,
                organization_id,
                keys,
                current_key,
                first,
                as_of,
                fallback=_unavailable_group(
                    "current_pending_customer_payments",
                    "Current pending payments by creation month",
                    "pending",
                    "current_pending_by_created_month",
                    "amicor_customer_payments.created_at",
                    "Current pending payment trends are unavailable.",
                ),
            ),
        )
    )
    streams.append(
        _stream(
            "completed_trip_calculated_ride_totals",
            "Completed-trip calculated ride totals",
            _safe_group(
                _trip_totals,
                db,
                organization_id,
                keys,
                current_key,
                first,
                as_of,
                field="ride_price_usd",
                key="completed_trip_calculated_ride_totals",
                label="Completed-trip calculated ride totals",
                fallback=_unavailable_group(
                    "completed_trip_calculated_ride_totals",
                    "Completed-trip calculated ride totals",
                    "calculated",
                    "created_at_month",
                    "health_isf_trip_financial_records.created_at",
                    "Calculated ride trends are unavailable.",
                ),
            ),
        )
    )
    streams.append(
        _stream(
            "completed_trip_calculated_platform_share",
            "Completed-trip calculated platform share",
            _safe_group(
                _trip_totals,
                db,
                organization_id,
                keys,
                current_key,
                first,
                as_of,
                field="platform_revenue_usd",
                key="completed_trip_calculated_platform_share",
                label="Completed-trip calculated platform share",
                fallback=_unavailable_group(
                    "completed_trip_calculated_platform_share",
                    "Completed-trip calculated platform share",
                    "calculated",
                    "created_at_month",
                    "health_isf_trip_financial_records.created_at",
                    "Calculated platform-share trends are unavailable.",
                ),
            ),
        )
    )
    streams.append(
        _stream(
            "freight_paid_invoice_totals",
            "Freight paid invoice totals",
            _safe_group(
                _freight_paid,
                db,
                organization_id,
                keys,
                current_key,
                first,
                as_of,
                fallback=_unavailable_group(
                    "freight_paid_invoice_totals",
                    "Freight paid invoice totals",
                    "confirmed",
                    "paid_at_month",
                    "nova_freight_invoices.paid_at",
                    "Freight paid invoice trends are unavailable.",
                ),
            ),
        )
    )
    freight_groups = []
    freight_ok = True
    try:
        for status in UNPAID_INVOICE_STATUSES:
            freight_groups.append(
                _safe_group(
                    _freight_unpaid,
                    db,
                    organization_id,
                    keys,
                    current_key,
                    first,
                    as_of,
                    status,
                    fallback=_unavailable_group(
                        f"freight_{status}",
                        FREIGHT_STATUS_LABELS[status],
                        "pending",
                        "current_unpaid_by_created_month",
                        "nova_freight_invoices.created_at",
                        f"Freight {status} trends are unavailable.",
                    ),
                )
            )
    except Exception:
        freight_ok = False
        freight_groups = [
            _unavailable_group(
                f"freight_{status}",
                FREIGHT_STATUS_LABELS[status],
                "pending",
                "current_unpaid_by_created_month",
                "nova_freight_invoices.created_at",
                f"Freight {status} trends are unavailable.",
            )
            for status in UNPAID_INVOICE_STATUSES
        ]
    streams.append(
        NovaTrendStream(
            key="current_unpaid_freight_invoices",
            label="Current unpaid Freight invoices by creation month",
            status="ok" if freight_ok else "unavailable",
            groups=freight_groups,
        )
    )
    return NovaAccountingTrendsOut(
        organization_id=organization_id,
        months=resolved,  # type: ignore[arg-type]
        calculated_as_of_utc=as_of.isoformat(),
        range_start_utc=first.isoformat(),
        streams=streams,
    )
