"""Application-package readiness review for AMICOR Nova.

This is a pre-owner-review quality gate. It measures completeness and evidence;
it does not predict hiring outcomes and does not authorize external submission.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.nova.v3.capability_proof import build_capability_proof
from app.core.nova.v3.work_packets import build_work_packet
from app.core.nova.work_revenue.verified_profile import OWNER_INPUT_REQUIRED

_REQUIRED_KINDS = {
    "capability_statement",
    "resume",
    "cover_letter",
    "proposal",
    "work_sample_outline",
    "owner_input_checklist",
    "work_plan",
}

_RISKY_CLAIM_PATTERNS = (
    r"\bi have \d+ years\b",
    r"\bwe have \d+ years\b",
    r"\bharvard mba holder\b",
    r"\bcertified public accountant\b",
    r"\blicensed attorney\b",
    r"\bprior client results include\b",
)


def _material_map(materials: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("kind") or ""): item for item in materials}


def review_application_package(
    opportunity: dict[str, Any],
    materials: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a deterministic readiness review with actionable blockers."""
    packet = build_work_packet(opportunity)
    proof = build_capability_proof(opportunity)
    by_kind = _material_map(materials)
    missing_materials = sorted(_REQUIRED_KINDS - set(by_kind))

    all_text = "\n".join(str(item.get("body") or "") for item in materials)
    owner_input_by_material = {
        kind: str(item.get("body") or "").count(OWNER_INPUT_REQUIRED)
        for kind, item in by_kind.items()
        if str(item.get("body") or "").count(OWNER_INPUT_REQUIRED)
    }
    owner_input_count = sum(owner_input_by_material.values())
    risky_claims = [
        pattern
        for pattern in _RISKY_CLAIM_PATTERNS
        if re.search(pattern, all_text, flags=re.IGNORECASE)
    ]

    coverage_checks = {
        "capability_match": bool(packet.get("matched_capabilities")),
        "execution_plan": bool(packet.get("tasks")) and bool(packet.get("quality_checks")),
        "deliverables": bool(packet.get("deliverables")),
        "proof_plan": bool(proof.get("proof_ready")),
        "required_materials": not missing_materials,
        "truthfulness_guard": not risky_claims,
        "external_submission_off": all(
            item.get("externally_submitted") is not True for item in materials
        ),
    }

    blockers: list[str] = []
    if not packet.get("execution_ready"):
        blockers.append("execution_not_ready")
    if missing_materials:
        blockers.append("required_materials_missing")
    if risky_claims:
        blockers.append("potential_unverified_claim")
    if owner_input_count:
        blockers.append("owner_input_required")

    # Readiness is intentionally descriptive, not a prediction of job success.
    score_parts = {
        "capability_and_execution": 30 if coverage_checks["capability_match"] and coverage_checks["execution_plan"] else 0,
        "deliverable_fit": 20 if coverage_checks["deliverables"] else 0,
        "proof_of_capability": 15 if coverage_checks["proof_plan"] else 0,
        "package_completeness": 15 if coverage_checks["required_materials"] else 0,
        "truthfulness": 20 if coverage_checks["truthfulness_guard"] else 0,
    }
    readiness_score = sum(score_parts.values())
    if owner_input_count:
        readiness_score = min(readiness_score, 85)

    if not packet.get("execution_ready") or risky_claims:
        status = "BLOCKED"
    elif missing_materials or owner_input_count:
        status = "OWNER_INPUT_REQUIRED"
    else:
        status = "READY_FOR_OWNER_REVIEW"

    actions: list[str] = []
    if owner_input_count:
        kinds = ", ".join(sorted(owner_input_by_material))
        actions.append(
            "Resolve OWNER INPUT REQUIRED fields using verified or owner-provided facts"
            + (f" in: {kinds}." if kinds else ".")
        )
    if missing_materials:
        actions.append("Generate missing required application materials.")
    if risky_claims:
        actions.append("Remove or verify potentially unsupported credential/experience claims.")
    if not proof.get("proof_ready"):
        actions.append("Create a capability-specific demonstration plan before presenting work samples.")
    if status == "READY_FOR_OWNER_REVIEW":
        actions.append("Owner reviews the complete package before any future external action.")

    return {
        "status": status,
        "readiness_score": readiness_score,
        "score_components": score_parts,
        "coverage_checks": coverage_checks,
        "missing_materials": missing_materials,
        "owner_input_markers": owner_input_count,
        "owner_input_by_material": owner_input_by_material,
        "potential_unverified_claim_patterns": risky_claims,
        "blockers": blockers,
        "recommended_actions": actions,
        "capability_proof": proof,
        "external_submission": False,
        "financial_execution": False,
        "note": (
            "Readiness score measures internal package completeness/evidence only; "
            "it does not predict selection, hiring, or contract award."
        ),
    }
