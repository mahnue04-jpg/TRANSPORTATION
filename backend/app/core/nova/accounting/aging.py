"""Read-only pending-funds aging. Does not change summary calculations."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.auth import UserContext, normalize_role
from app.core.nova.accounting.schemas import (
    NovaAccountingAgingOut,
    NovaAgingBucket,
    NovaAgingCurrencySlice,
    NovaAgingGroup,
    NovaAgingSection,
)
from app.core.nova.accounting.service import ACCOUNTING_ROLES, NovaAccountingError
from app.core.nova.freight.money import from_minor_units, money
from app.core.nova.freight.ops import UNPAID_INVOICE_STATUSES
from app.helpers import now

BUCKETS = (
    ("0_7", "0–7 days", 0, 7),
    ("8_30", "8–30 days", 8, 30),
    ("31_60", "31–60 days", 31, 60),
    ("61_plus", "61+ days", 61, None),
)
FREIGHT_STATUS_LABELS = {
    "draft": "Freight draft invoices",
    "ready": "Freight ready invoices",
    "payment_pending": "Freight payment-pending invoices",
    "failed": "Freight failed invoices",
}


def age_days(created_at: datetime | None, *, as_of: datetime) -> int | None:
    if created_at is None:
        return None
    stamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    reference = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    seconds = (reference - stamp).total_seconds()
    if seconds < 0:
        return None
    return int(seconds // 86400)


def bucket_key(days: int) -> str:
    if days <= 7:
        return "0_7"
    if days <= 30:
        return "8_30"
    if days <= 60:
        return "31_60"
    return "61_plus"


def _normalize_currency(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _to_aware(value: datetime, as_of: datetime) -> datetime:
    if value.tzinfo:
        return value
    return value.replace(tzinfo=as_of.tzinfo or timezone.utc)


def _aggregate(
    rows: list[tuple[datetime | None, object, object]],
    *,
    as_of: datetime,
    amount_mode: str,
) -> list[NovaAgingCurrencySlice]:
    grouped: dict[str, dict] = {}
    for created_at, raw_amount, raw_currency in rows:
        currency = _normalize_currency(raw_currency) or ""
        slot = grouped.setdefault(
            currency,
            {
                "count": 0,
                "amount": money(0),
                "oldest": None,
                "unaged": 0,
                "missing_amount": 0,
                "buckets": {key: {"count": 0, "amount": money(0)} for key, _label, _lo, _hi in BUCKETS},
            },
        )
        slot["count"] += 1
        amount = None
        if raw_amount is not None:
            if amount_mode == "minor":
                amount = from_minor_units(int(raw_amount))
            else:
                amount = money(raw_amount)
        else:
            slot["missing_amount"] += 1
        if amount is not None:
            slot["amount"] = money(slot["amount"] + amount)
        days = age_days(_to_aware(created_at, as_of) if created_at is not None else None, as_of=as_of)
        if days is None:
            slot["unaged"] += 1
            continue
        key = bucket_key(days)
        if amount is not None:
            slot["buckets"][key]["amount"] = money(slot["buckets"][key]["amount"] + amount)
        slot["buckets"][key]["count"] += 1
        if slot["oldest"] is None or days > slot["oldest"]:
            slot["oldest"] = days
    slices: list[NovaAgingCurrencySlice] = []
    for currency, slot in grouped.items():
        buckets = []
        for key, label, _lo, _hi in BUCKETS:
            bucket = slot["buckets"][key]
            buckets.append(
                NovaAgingBucket(
                    key=key,  # type: ignore[arg-type]
                    label=label,
                    count=int(bucket["count"]),
                    amount=float(money(bucket["amount"])),
                )
            )
        slices.append(
            NovaAgingCurrencySlice(
                currency=currency,
                count=int(slot["count"]),
                amount=float(money(slot["amount"])),
                oldest_age_days=slot["oldest"],
                unaged_count=int(slot["unaged"]),
                missing_amount_count=int(slot["missing_amount"]),
                buckets=buckets,
            )
        )
    slices.sort(key=lambda row: row.currency)
    return slices


def _unavailable_group(key: str, label: str, timestamp_field: str, source_note: str, *, collectible: bool) -> NovaAgingGroup:
    return NovaAgingGroup(
        key=key,
        label=label,
        status="unavailable",
        timestamp_field=timestamp_field,
        source_note=source_note,
        collectible=collectible,
        currencies=[],
    )


def _unavailable_section(key: str, label: str, groups: list[NovaAgingGroup]) -> NovaAgingSection:
    return NovaAgingSection(key=key, label=label, status="unavailable", groups=groups)


def _customer_group(db: Session, organization_id: str, as_of: datetime) -> NovaAgingGroup:
    from app.modules.payments.models import PAYMENT_PENDING, AmicorCustomerPayment

    rows = (
        db.query(
            AmicorCustomerPayment.created_at,
            AmicorCustomerPayment.amount_minor,
            AmicorCustomerPayment.currency,
        )
        .filter(
            AmicorCustomerPayment.organization_id == organization_id,
            AmicorCustomerPayment.organization_id.isnot(None),
            AmicorCustomerPayment.payment_status == PAYMENT_PENDING,
        )
        .all()
    )
    return NovaAgingGroup(
        key="customer_pending",
        label="Pending customer payments",
        timestamp_field="amicor_customer_payments.created_at",
        due_date_field=None,
        uses_due_date=False,
        collectible=False,
        stripe_mode="TEST",
        source_note=(
            "Stripe TEST PaymentIntents with payment_status=pending. Age since created_at. "
            "No canonical due date exists. Not confirmed cash and not Freight invoices."
        ),
        currencies=_aggregate(list(rows), as_of=as_of, amount_mode="minor"),
    )


def _freight_group(db: Session, organization_id: str, as_of: datetime, status: str) -> NovaAgingGroup:
    from app.core.nova.freight.models import NovaFreightInvoice

    rows = (
        db.query(
            NovaFreightInvoice.created_at,
            NovaFreightInvoice.total_amount,
            NovaFreightInvoice.currency,
        )
        .filter(
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.organization_id.isnot(None),
            NovaFreightInvoice.invoice_status == status,
        )
        .all()
    )
    collectible = False
    note = (
        f"Freight invoices with invoice_status={status}. Age since created_at. "
        "No canonical due date exists. Stripe TEST. Not Ride/Delivery payments."
    )
    if status == "draft":
        note = (
            "Draft Freight invoices are not collectible revenue. Age since created_at. "
            "No canonical due date exists. Stripe TEST. Not combined with customer payments."
        )
    return NovaAgingGroup(
        key=f"freight_{status}",
        label=FREIGHT_STATUS_LABELS[status],
        timestamp_field="nova_freight_invoices.created_at",
        due_date_field=None,
        uses_due_date=False,
        collectible=collectible,
        stripe_mode="TEST",
        source_note=note,
        currencies=_aggregate(list(rows), as_of=as_of, amount_mode="money"),
    )


def _safe_group(reader, *args, fallback: NovaAgingGroup) -> NovaAgingGroup:
    try:
        return reader(*args)
    except Exception:
        return fallback


def aging(db: Session, *, organization_id: str, user: UserContext) -> NovaAccountingAgingOut:
    if normalize_role(user.role) not in ACCOUNTING_ROLES:
        raise NovaAccountingError("Accounting aging is limited to finance-authorized Nova roles", status_code=403)
    as_of = now()
    try:
        customer_group = _customer_group(db, organization_id, as_of)
        customer = NovaAgingSection(
            key="customer_payment_pipeline",
            label="Customer payment pipeline",
            groups=[customer_group],
        )
    except Exception:
        customer = _unavailable_section(
            "customer_payment_pipeline",
            "Customer payment pipeline",
            [
                _unavailable_group(
                    "customer_pending",
                    "Pending customer payments",
                    "amicor_customer_payments.created_at",
                    "Pending customer payment aging is unavailable.",
                    collectible=False,
                )
            ],
        )
    freight_groups: list[NovaAgingGroup] = []
    freight_section_ok = True
    try:
        for status in UNPAID_INVOICE_STATUSES:
            freight_groups.append(
                _safe_group(
                    _freight_group,
                    db,
                    organization_id,
                    as_of,
                    status,
                    fallback=_unavailable_group(
                        f"freight_{status}",
                        FREIGHT_STATUS_LABELS[status],
                        "nova_freight_invoices.created_at",
                        f"Freight {status} aging is unavailable.",
                        collectible=False,
                    ),
                )
            )
    except Exception:
        freight_section_ok = False
        freight_groups = [
            _unavailable_group(
                f"freight_{status}",
                FREIGHT_STATUS_LABELS[status],
                "nova_freight_invoices.created_at",
                f"Freight {status} aging is unavailable.",
                collectible=False,
            )
            for status in UNPAID_INVOICE_STATUSES
        ]
    freight = NovaAgingSection(
        key="freight_invoice_pipeline",
        label="Freight invoice pipeline",
        status="ok" if freight_section_ok else "unavailable",
        groups=freight_groups,
    )
    return NovaAccountingAgingOut(
        organization_id=organization_id,
        calculated_as_of_utc=as_of.isoformat(),
        customer_payment_pipeline=customer,
        freight_invoice_pipeline=freight,
    )
