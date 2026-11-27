"""Owner-reviewed bookkeeping support for Nova Operations Agent.

A deterministic, offline workpaper builder. No ledger posting, payroll, tax,
bank access, payment execution, or third-party data transfer. This module is
not connected to a customer-facing route until security review and staging QA.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_BYTES = 1_000_000
MAX_ROWS = 5000
MAX_FIELD_LENGTH = 500
FIELDS = ("date", "description", "amount", "reference")
OUTPUT_FIELDS = ("row", "date", "description", "amount", "reference", "suggested_category", "review_status", "issue")

CATEGORY_HINTS = (
    ("Software subscriptions", ("software", "subscription", "hosting", "cloud service")),
    ("Office supplies", ("office supplies", "stationery", "printer paper")),
    ("Shipping", ("postage", "shipping label", "courier")),
    ("Travel", ("airfare", "hotel", "taxi", "rideshare")),
)


class BookkeepingInputError(ValueError):
    """Invalid workpaper input: do not disclose customer row data in logs."""


def _safe_cell(value: str) -> str:
    # Prefix spreadsheet formulas to stop CSV formula execution on opening.
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def _read_csv(raw: str, source_name: str) -> list[dict[str, Any]]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise BookkeepingInputError(f"{source_name}: input exceeds size limit or is not text")
    try:
        stream = io.StringIO(raw, newline="")
        reader = csv.DictReader(stream, strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise BookkeepingInputError(f"{source_name}: missing or duplicate headers")
        if set(reader.fieldnames) != set(FIELDS):
            raise BookkeepingInputError(f"{source_name}: expected date,description,amount,reference")
        rows = []
        for index, row in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                raise BookkeepingInputError(f"{source_name}: too many rows")
            if None in row or any(value is None for value in row.values()):
                raise BookkeepingInputError(f"{source_name}: malformed CSV row {index}")
            if any(len(value) > MAX_FIELD_LENGTH for value in row.values()):
                raise BookkeepingInputError(f"{source_name}: field too long on row {index}")
            try:
                parsed_date = date.fromisoformat(row["date"].strip())
                amount = Decimal(row["amount"].strip())
                if not amount.is_finite() or amount.as_tuple().exponent < -2:
                    raise InvalidOperation
            except (ValueError, InvalidOperation):
                raise BookkeepingInputError(f"{source_name}: invalid date or amount on row {index}") from None
            if not row["description"].strip():
                raise BookkeepingInputError(f"{source_name}: missing description on row {index}")
            rows.append({
                "row": index,
                "date": parsed_date.isoformat(),
                "description": row["description"].strip(),
                "amount": amount.quantize(Decimal("0.01")),
                "reference": row["reference"].strip(),
            })
        return rows
    except csv.Error:
        raise BookkeepingInputError(f"{source_name}: invalid CSV") from None


def _hint(description: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", description.lower())
    text = " " + re.sub(r"\s+", " ", text).strip() + " "
    matches = [
        label for label, keywords in CATEGORY_HINTS
        if any(" " + keyword + " " in text for keyword in keywords)
    ]
    return matches[0] if len(matches) == 1 else "Uncategorized"


def _export(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: (str(row.get(field, "")) if field in ("row", "amount") else _safe_cell(row.get(field, ""))) for field in OUTPUT_FIELDS})
    return output.getvalue()


def build_bookkeeping_workpaper(transactions_csv: str, bank_csv: str | None = None) -> dict[str, Any]:
    """Return candidate classifications and exact-reference bank matches for human review.

    Bank matches require same date, signed amount, and nonempty unique reference.
    Missing/ambiguous matches are flagged, never guessed or silently reconciled.
    Duplicate source rows are flagged but preserved in the report.
    """
    transactions = _read_csv(transactions_csv, "transactions")
    bank = _read_csv(bank_csv, "bank") if bank_csv is not None else None
    seen = Counter((r["date"], r["description"], r["amount"], r["reference"]) for r in transactions)
    bank_index: dict[tuple[str, Decimal, str], list[int]] = defaultdict(list)
    transaction_match_counts = Counter(
        (r["date"], r["amount"], r["reference"])
        for r in transactions if r["reference"]
    )
    if bank is not None:
        for bank_row in bank:
            if bank_row["reference"]:
                bank_index[(bank_row["date"], bank_row["amount"], bank_row["reference"])].append(bank_row["row"])

    output_rows = []
    matched_bank_rows = []
    totals = {"incoming": Decimal("0.00"), "outgoing": Decimal("0.00")}
    counts = Counter()
    for transaction in transactions:
        amount = transaction["amount"]
        totals["incoming" if amount >= 0 else "outgoing"] += abs(amount)
        signature = (transaction["date"], transaction["description"], amount, transaction["reference"])
        issues = []
        if seen[signature] > 1:
            issues.append("possible_duplicate")
        category = _hint(transaction["description"])
        if category == "Uncategorized":
            issues.append("category_review")
        if bank is not None:
            key = (transaction["date"], amount, transaction["reference"])
            possible = bank_index.get(key, []) if transaction["reference"] else []
            if len(possible) != 1 or transaction_match_counts[key] != 1:
                issues.append("bank_match_missing_or_ambiguous")
            else:
                matched_bank_rows.append(possible[0])
        if issues:
            counts.update(issues)
        output_rows.append({
            "row": transaction["row"], "date": transaction["date"],
            "description": transaction["description"], "amount": f"{amount:.2f}",
            "reference": transaction["reference"], "suggested_category": category,
            "review_status": "NEEDS_HUMAN_REVIEW",
            "issue": ";".join(issues),
        })

    unmatched_bank = []
    if bank is not None:
        matched_counts = Counter(matched_bank_rows)
        unmatched_bank = [r["row"] for r in bank if matched_counts[r["row"]] != 1]

    return {
        "status": "DRAFT_FOR_HUMAN_REVIEW",
        "transaction_count": len(transactions),
        "bank_row_count": len(bank) if bank is not None else None,
        "incoming_total": f"{totals['incoming']:.2f}",
        "outgoing_total": f"{totals['outgoing']:.2f}",
        "net_total": f"{totals['incoming'] - totals['outgoing']:.2f}",
        "issue_counts": dict(counts),
        "unmatched_bank_rows": unmatched_bank,
        "matched_bank_row_count": len(set(matched_bank_rows)),
        "all_bank_rows_accounted_for": bank is not None and not unmatched_bank and len(matched_bank_rows) == len(transactions),
        "workpaper_csv": _export(output_rows),
        "limitations": [
            "Categories are keyword hints, not approved accounting classifications.",
            "Bank matches are reference/date/amount checks, not formal bank reconciliation.",
            "All rows require human review before any client deliverable.",
            "No accounting ledger entries, tax filings, payroll, or payments are performed.",
        ],
    }
