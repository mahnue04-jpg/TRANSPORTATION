"""Capability-proof portfolio builder for AMICOR Nova.

Creates internal demonstration briefs that prove a capability without claiming the
demo was prior paid client work. Nothing here publishes, sends, applies, deploys,
or moves money.
"""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.capability_catalog import capability_fit
from app.core.nova.v3.work_packets import build_work_packet


_SAMPLE_TYPES = {
    "business_research": "research brief with sourced comparison table",
    "administrative_operations": "operations tracker plus SOP",
    "data_spreadsheet": "cleaned sample dataset plus reporting workbook",
    "ai_workflow_automation": "workflow map plus isolated automation test plan",
    "bookkeeping_support": "sample categorized ledger plus reconciliation support sheet",
    "content_documentation": "client-style documentation sample",
    "web_software": "small isolated implementation with test evidence",
    "customer_support_operations": "ticket taxonomy plus response/knowledge-base sample",
    "proposal_rfp": "sample compliance matrix plus proposal section",
    "document_intelligence": "sample extraction/comparison report",
}


def build_capability_proof(opportunity: dict[str, Any]) -> dict[str, Any]:
    """Build an internal-only proof-of-capability plan for an opportunity."""
    packet = build_work_packet(opportunity)
    matches = packet.get("matched_capabilities") or []
    fit = capability_fit(
        " ".join(
            str(value or "")
            for value in (
                opportunity.get("opportunity_title"),
                opportunity.get("title"),
                opportunity.get("description"),
                opportunity.get("requirements"),
            )
        ),
        title=str(opportunity.get("opportunity_title") or opportunity.get("title") or "") or None,
    )

    if not packet.get("execution_ready") or not matches:
        return {
            "proof_ready": False,
            "primary_capability_id": packet.get("primary_capability_id"),
            "sample_type": None,
            "sample_brief": None,
            "evidence_to_show": [],
            "quality_checks": [],
            "disclosure": (
                "No capability demo should be presented until Nova has a confirmed capability fit."
            ),
            "blockers": packet.get("blockers") or ["no_confirmed_capability"],
            "external_publish": False,
            "external_submission": False,
            "financial_execution": False,
        }

    primary = str(packet.get("primary_capability_id") or "")
    label = str(matches[0].get("label") or primary)
    sample_type = _SAMPLE_TYPES.get(primary, "capability-specific demonstration")
    deliverables = packet.get("deliverables") or []
    quality_checks = packet.get("quality_checks") or []

    sample_brief = (
        f"Create a new AMICOR/Nova demonstration for {label}. "
        f"Use synthetic, public, or owner-approved non-confidential inputs. "
        f"Show the same class of deliverable the opportunity requests: "
        f"{', '.join(deliverables[:6]) or sample_type}. "
        f"Clearly label the artifact as a demonstration, not prior paid client work."
    )

    evidence = [
        "problem statement",
        "input/source description",
        "method or workflow used",
        "finished deliverable",
        "quality-check results",
        "limitations/assumptions",
    ]
    if primary == "web_software":
        evidence.extend(["test results", "changed-file summary", "rollback notes"])
    if primary == "ai_workflow_automation":
        evidence.extend(["workflow diagram", "success/failure test cases", "manual fallback"])

    return {
        "proof_ready": bool(fit.get("fit")),
        "primary_capability_id": primary,
        "capability_label": label,
        "sample_type": sample_type,
        "sample_brief": sample_brief,
        "evidence_to_show": evidence,
        "quality_checks": quality_checks,
        "disclosure": (
            "This is a newly created capability demonstration. "
            "It is not represented as prior paid client work, employment history, "
            "or a client result."
        ),
        "blockers": [],
        "external_publish": False,
        "external_submission": False,
        "financial_execution": False,
    }
