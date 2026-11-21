"""Offline accounts-payable due-date and exception workpaper.

This is a non-posting, review-only calculation. No approval of bills, payments,
tax determination, bank connection, or external data transfer.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

FIELDS = ("bill_id", "vendor", "bill_date", "due_date", "amount", "paid")
MAX_BYTES = 1_000_000
MAX_ROWS = 5000
MAX_FIELD = 500
CENT = Decimal("0.01")


class PayablesInputError(ValueError):
    pass


def _parse_date(value: str, field: str, line: int) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise PayablesInputError(f"row {line}: invalid {field}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise PayablesInputError(f"row {line}: invalid {field}") from None


def _parse_amount(value: str, field: str, line: int) -> Decimal:
    try:
        number = Decimal(value.strip())
        if not number.is_finite() or number < 0 or number.as_tuple().exponent < -2:
            raise InvalidOperation
        return number.quantize(CENT)
    except (ValueError, InvalidOperation):
        raise PayablesInputError(f"row {line}: invalid {field}") from None


def _safe_cell(value: str) -> str:
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def build_payables_workpaper(bills_csv: str, *, as_of: str) -> dict:
    """Create AP due/overdue buckets and exceptions for human verification.

    This does not validate supplier legitimacy, duplicate payment status,
    payment allocation, discounts or tax treatment.
    """
    anchor = _parse_date(as_of, "as_of", 0)
    if not isinstance(bills_csv, str) or len(bills_csv.encode("utf-8")) > MAX_BYTES:
        raise PayablesInputError("Bill input is not text or exceeds 1 MB")
    reader = csv.DictReader(io.StringIO(bills_csv, newline=""), strict=True)
    if reader.fieldnames != list(FIELDS):
        raise PayablesInputError("Expected bill_id,vendor,bill_date,due_date,amount,paid")
    data = []
    try:
        for line, row in enumerate(reader, 2):
            if len(data) >= MAX_ROWS:
                raise PayablesInputError("Too many bills")
            if None in row or any(v is None or len(v) > MAX_FIELD for v in row.values()):
                raise PayablesInputError(f"row {line}: malformed CSV")
            bill_id, vendor = row["bill_id"].strip(), row["vendor"].strip()
            if not bill_id or not vendor:
                raise PayablesInputError(f"row {line}: bill ID and vendor required")
            bill_date = _parse_date(row["bill_date"], "bill_date", line)
            due_date = _parse_date(row["due_date"], "due_date", line)
            if due_date < bill_date:
                raise PayablesInputError(f"row {line}: due date precedes bill date")
            amount = _parse_amount(row["amount"], "amount", line)
            paid = _parse_amount(row["paid"], "paid", line)
            if paid > amount:
                raise PayablesInputError(f"row {line}: paid exceeds bill amount")
            data.append((line, bill_id, vendor, bill_date, due_date, amount, paid))
    except csv.Error:
        raise PayablesInputError("Malformed bill CSV") from None

    ids = Counter(bill_id.casefold() for _, bill_id, *_ in data)
    buckets = dict.fromkeys(("overdue", "due_0_7", "due_8_30", "due_later"), Decimal("0.00"))
    counts = Counter()
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("source_row", *FIELDS, "balance", "due_bucket", "review_status", "issues"))
    for line, bill_id, vendor, bill_date, due_date, amount, paid in data:
        balance = amount - paid
        until_due = (due_date - anchor).days
        bucket = ("overdue" if until_due < 0 else "due_0_7" if until_due <= 7 else
                  "due_8_30" if until_due <= 30 else "due_later")
        issues = []
        if ids[bill_id.casefold()] > 1:
            issues.append("duplicate_bill_id")
        if bill_date > anchor:
            issues.append("future_dated_bill")
        if paid:
            issues.append("verify_payment_allocation")
        if issues:
            counts.update(issues)
        buckets[bucket] += balance
        writer.writerow((line, _safe_cell(bill_id), _safe_cell(vendor),
                         bill_date.isoformat(), due_date.isoformat(),
                         str(amount), str(paid), str(balance), bucket,
                         "NEEDS_HUMAN_REVIEW", ";".join(issues)))
    return {
        "status": "DRAFT_FOR_HUMAN_REVIEW",
        "as_of": anchor.isoformat(),
        "bill_count": len(data),
        "total_unpaid": str(sum(buckets.values(), Decimal("0.00"))),
        "due_buckets": {k: str(v) for k, v in buckets.items()},
        "issue_counts": dict(counts),
        "workpaper_csv": output.getvalue(),
        "payment_authorized": False,
        "limitations": (
            "Amounts and payment allocations require source verification.",
            "No bills are approved or paid by this workpaper.",
            "No external accounting system is changed.",
        ),
    }
