"""Read-only invoice/receipt extraction for Nova Accounting.

This processor never creates an invoice, posts a ledger entry, sends a message,
or initiates payment. It only structures text extracted by the existing upload
pipeline and flags uncertainty for user review.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_AMOUNT_RE = re.compile(r"(?<![A-Za-z0-9])\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.\d{2})|[0-9]+\.\d{2})(?![A-Za-z0-9])")
_DATE_RE = re.compile(
    r"\b((?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12][0-9]|3[01])[/\-](?:20)?\d{2}|"
    r"(?:20\d{2})[/\-](?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12][0-9]|3[01]))\b"
)
_INVOICE_RE = re.compile(r"(?i)\b(?:invoice|inv)\s*(?:number|no\.?|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,40})")
_RECEIPT_RE = re.compile(r"(?i)\b(?:receipt|transaction)\s*(?:number|no\.?|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,40})")

_LABELS = {
    "subtotal": ("subtotal", "sub total"),
    "tax": ("sales tax", "tax"),
    "tip": ("tip", "gratuity"),
    "total": ("grand total", "amount due", "balance due", "total"),
}


def _clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines() if line.strip()]


def _amount_on_line(line: str) -> Decimal | None:
    found = _AMOUNT_RE.findall(line)
    if not found:
        return None
    try:
        return Decimal(found[-1].replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _labeled_amount(lines: list[str], labels: tuple[str, ...]) -> Decimal | None:
    for line in reversed(lines):
        low = line.lower()
        if any(label in low for label in labels):
            amount = _amount_on_line(line)
            if amount is not None:
                return amount
    return None


def _document_kind(text: str, upload_category: str | None) -> str:
    low = str(text or "").lower()
    category = str(upload_category or "").lower()
    if "invoice" in category or "invoice" in low or "amount due" in low or "balance due" in low:
        return "invoice"
    if "receipt" in category or "receipt" in low or "thank you for your purchase" in low:
        return "receipt"
    return "financial_document"


def analyze_financial_document(
    *,
    text: str,
    filename: str | None = None,
    upload_category: str | None = None,
) -> dict[str, Any]:
    lines = _clean_lines(text)
    kind = _document_kind(text, upload_category)
    first_lines = [line for line in lines[:8] if not _AMOUNT_RE.fullmatch(line)]
    vendor = first_lines[0][:160] if first_lines else None

    invoice_match = _INVOICE_RE.search(text or "")
    receipt_match = _RECEIPT_RE.search(text or "")
    dates = _DATE_RE.findall(text or "")

    subtotal = _labeled_amount(lines, _LABELS["subtotal"])
    tax = _labeled_amount(lines, _LABELS["tax"])
    tip = _labeled_amount(lines, _LABELS["tip"])
    total = _labeled_amount(lines, _LABELS["total"])

    all_amounts = [_amount_on_line(line) for line in lines]
    all_amounts = [a for a in all_amounts if a is not None]
    if total is None and all_amounts:
        total = all_amounts[-1]

    warnings: list[str] = []
    if not vendor:
        warnings.append("Vendor/customer name was not confidently identified.")
    if total is None:
        warnings.append("Total amount was not confidently identified.")
    if kind == "invoice" and not invoice_match:
        warnings.append("Invoice number was not confidently identified.")
    if not dates:
        warnings.append("Document date was not confidently identified.")

    math_check: dict[str, Any] = {
        "status": "not_enough_data",
        "expected_total": None,
        "difference": None,
    }
    if subtotal is not None and total is not None:
        expected = subtotal + (tax or Decimal("0")) + (tip or Decimal("0"))
        difference = total - expected
        math_check = {
            "status": "matches" if abs(difference) <= Decimal("0.02") else "review",
            "expected_total": float(expected),
            "difference": float(difference),
        }
        if math_check["status"] == "review":
            warnings.append("Extracted subtotal/tax/tip do not reconcile to the extracted total.")

    confidence_fields = [
        bool(vendor),
        bool(total is not None),
        bool(dates),
        bool(invoice_match or receipt_match or kind == "financial_document"),
    ]
    confidence = round(sum(1 for value in confidence_fields if value) / len(confidence_fields), 2)

    return {
        "document_type": kind,
        "filename": filename,
        "vendor_or_customer": vendor,
        "invoice_number": invoice_match.group(1) if invoice_match else None,
        "receipt_number": receipt_match.group(1) if receipt_match else None,
        "document_date": dates[0] if dates else None,
        "due_date": dates[1] if kind == "invoice" and len(dates) > 1 else None,
        "subtotal": float(subtotal) if subtotal is not None else None,
        "tax": float(tax) if tax is not None else None,
        "tip": float(tip) if tip is not None else None,
        "total": float(total) if total is not None else None,
        "currency": "USD" if "$" in str(text or "") else "UNKNOWN",
        "math_check": math_check,
        "confidence": confidence,
        "warnings": warnings,
        "review_required": bool(warnings),
        "source_preview": "\n".join(lines[:20])[:2400],
        "actions": {
            "save_to_ledger": False,
            "send_invoice": False,
            "collect_payment": False,
            "note": "Review-only extraction. No financial action has been executed.",
        },
    }
