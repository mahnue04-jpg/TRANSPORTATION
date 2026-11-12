"""Offline, review-only accounts receivable aging worksheet for Nova.

No customer connector, payment execution, QuickBooks posting, filing or send.
This accepts synthetic/owner-authorized tabular data only. Before customer
usage it must be wrapped with authenticated tenant-scoped durable job storage.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

FIELDS = ("invoice_id", "customer", "invoice_date", "due_date", "amount", "paid")
MAX_BYTES = 1_000_000
MAX_ROWS = 5000
MAX_CELL = 500
CENT = Decimal("0.01")


class ReceivableInputError(ValueError):
    pass


def _currency(raw: str, row: int, name: str) -> Decimal:
    try:
        amount = Decimal(raw.strip())
        if not amount.is_finite() or amount.as_tuple().exponent < -2 or amount < 0:
            raise InvalidOperation
        return amount.quantize(CENT)
    except (InvalidOperation, ValueError):
        raise ReceivableInputError(f"row {row}: invalid {name}") from None


def _date(raw: str, row: int, name: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip()):
        raise ReceivableInputError(f"row {row}: invalid {name}")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ReceivableInputError(f"row {row}: invalid {name}") from None


def _safe(value: Any) -> str:
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


def build_receivables_aging(invoices_csv: str, *, as_of: str) -> dict[str, Any]:
    """Return non-posting aging candidates; unknowns/duplicates require review.

    Age buckets are based on days past due: current, 1-30, 31-60, 61-90,
    and 91+. Not a GAAP financial statement or collection authorization.
    """
    anchor = _date(as_of, 0, "as_of")
    if not isinstance(invoices_csv, str) or len(invoices_csv.encode("utf-8")) > MAX_BYTES:
        raise ReceivableInputError("Invoice input is not text or exceeds 1 MB")
    reader = csv.DictReader(io.StringIO(invoices_csv, newline=""), strict=True)
    if not reader.fieldnames or reader.fieldnames != list(FIELDS):
        raise ReceivableInputError("Invoice headers must be invoice_id,customer,invoice_date,due_date,amount,paid")
    try:
        rows = []
        for line, row in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                raise ReceivableInputError("Too many invoices")
            if None in row or any(v is None or len(v) > MAX_CELL for v in row.values()):
                raise ReceivableInputError(f"row {line}: malformed CSV")
            invoice_id = row["invoice_id"].strip()
            customer = row["customer"].strip()
            if not invoice_id or not customer:
                raise ReceivableInputError(f"row {line}: invoice and customer required")
            start = _date(row["invoice_date"], line, "invoice_date")
            due = _date(row["due_date"], line, "due_date")
            amount = _currency(row["amount"], line, "amount")
            paid = _currency(row["paid"], line, "paid")
            if due < start:
                raise ReceivableInputError(f"row {line}: due date precedes invoice date")
            if paid > amount:
                raise ReceivableInputError(f"row {line}: payments exceed invoice amount")
            rows.append({
                "source_row": line, "invoice_id": invoice_id, "customer": customer,
                "invoice_date": start.isoformat(), "due_date": due.isoformat(),
                "amount": amount, "paid": paid, "balance": amount - paid,
            })
    except csv.Error:
        raise ReceivableInputError("Malformed invoice CSV") from None

    duplicates = Counter(r["invoice_id"].casefold() for r in rows)
    buckets = {key: CENT * 0 for key in ("current", "1-30", "31-60", "61-90", "91+")}
    issues = Counter()
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("source_row", *FIELDS, "balance", "age_bucket", "status", "issue"))
    for r in rows:
        balance = r["balance"]
        days = (anchor - date.fromisoformat(r["due_date"])).days
        age = ("current" if days <= 0 else "1-30" if days <= 30 else
               "31-60" if days <= 60 else "61-90" if days <= 90 else "91+")
        issues_row = []
        if duplicates[r["invoice_id"].casefold()] > 1:
            issues_row.append("duplicate_invoice_id")
        if date.fromisoformat(r["invoice_date"]) > anchor:
            issues_row.append("future_dated_invoice")
        if r["paid"] > 0:
            issues_row.append("verify_payment_allocation")
        if balance > 0:
            buckets[age] += balance
        if issues_row:
            issues.update(issues_row)
        writer.writerow((
            r["source_row"], _safe(r["invoice_id"]), _safe(r["customer"]),
            r["invoice_date"], r["due_date"], str(r["amount"]),
            str(r["paid"]), str(balance), age,
            "NEEDS_HUMAN_REVIEW", ";".join(issues_row),
        ))
    return {
        "status": "DRAFT_FOR_HUMAN_REVIEW",
        "as_of": anchor.isoformat(),
        "invoice_count": len(rows),
        "total_outstanding": str(sum(buckets.values(), CENT * 0)),
        "aging_buckets": {key: str(value) for key, value in buckets.items()},
        "issue_counts": dict(issues),
        "workpaper_csv": output.getvalue(),
        "limitations": [
            "Source invoices and payments have not been independently verified.",
            "No collection activity, accounting entry, tax filing or payment occurs.",
            "All results require authorized human review before external use.",
        ],
    }
