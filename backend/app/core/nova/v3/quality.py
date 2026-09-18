"""Deliverable quality gates. Do not invent evidence."""
from __future__ import annotations

import re
from typing import Any

from app.core.nova.v3.errors import V3Error

PII_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PROHIBITED = ("enable live discovery", "bypass captcha", "<script")


def evaluate_deliverable(*, body: str, source_inputs: dict[str, Any], evidence_links: list[str]) -> dict[str, Any]:
    text = (body or "").strip()
    flags: list[str] = []
    if not text:
        flags.append("output_empty")
    if "INTERNAL" not in text.upper() and "internal" not in text.lower():
        flags.append("missing_internal_section")
    if "source" not in text.lower() and not evidence_links:
        flags.append("source_list_missing")
    fabricated = "client confirmed" in text.lower() and not source_inputs
    if fabricated:
        flags.append("unverified_factual_claim")
    if any(token in text.lower() for token in PROHIBITED):
        flags.append("prohibited_content")
    pii = bool(PII_RE.search(text))
    if pii:
        flags.append("pii_warning")
    missing_client_input = not source_inputs
    if missing_client_input:
        flags.append("missing_client_input")
    passed = not any(
        item in flags
        for item in ("output_empty", "unverified_factual_claim", "prohibited_content")
    )
    return {
        "passed": passed,
        "flags": flags,
        "required_sections_present": "missing_internal_section" not in flags,
        "output_not_empty": "output_empty" not in flags,
        "source_list_present": "source_list_missing" not in flags,
        "factual_support": not fabricated,
        "formatting_ok": len(text) < 20_000,
        "prohibited_content": "prohibited_content" in flags,
        "pii_warning": pii,
        "missing_client_input": missing_client_input,
        "uncertainty": "Owner review required. Nova did not verify external facts.",
        "owner_review_required": True,
        "fake_evidence": False,
    }


def require_quality(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("passed"):
        raise V3Error("QUALITY_GATE_FAILED", "deliverable failed quality gate", http_status=409)
    return result
