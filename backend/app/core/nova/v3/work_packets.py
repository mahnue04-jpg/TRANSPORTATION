"""Owner-controlled work packet builder for Nova Capability & Work Execution Engine.

A work packet converts a qualified opportunity into concrete internal tasks,
required inputs, deliverables, checkpoints, and completion evidence. It does not
authorize external submission, client contact, production deploys, signatures,
invoicing, or money movement.
"""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.capability_catalog import capability_fit
from app.core.nova.v3.execution_playbooks import execution_plan_for_matches


def _opportunity_text(opportunity: dict[str, Any]) -> str:
    parts = (
        opportunity.get("opportunity_title"),
        opportunity.get("title"),
        opportunity.get("company_name"),
        opportunity.get("description"),
        opportunity.get("requirements"),
        " ".join(opportunity.get("skills_required") or []),
    )
    return " ".join(str(item or "") for item in parts)


def build_work_packet(opportunity: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, internal-only execution packet."""
    text = _opportunity_text(opportunity)
    title = str(
        opportunity.get("opportunity_title")
        or opportunity.get("title")
        or ""
    ).strip()
    fit = capability_fit(text, title=title or None)
    plan = execution_plan_for_matches(fit["capabilities"])
    playbook = plan.get("playbook") or {}

    title = title or "Untitled opportunity"
    company = str(opportunity.get("company_name") or "Unknown client").strip()

    required_inputs = list(playbook.get("required_inputs") or [])
    steps = list(playbook.get("steps") or [])
    checks = list(playbook.get("quality_checks") or [])
    owner_gates = list(playbook.get("owner_gates") or [])

    tasks = [
        {
            "sequence": index + 1,
            "task": step,
            "status": "NOT_STARTED",
            "owner_approval_required": step.startswith("prepare owner-review"),
        }
        for index, step in enumerate(steps)
    ]

    deliverables: list[str] = []
    if fit["capabilities"]:
        for item in fit["capabilities"][:3]:
            for deliverable in item.get("deliverables") or []:
                if deliverable not in deliverables:
                    deliverables.append(deliverable)

    evidence = [
        "source inputs retained or referenced",
        "task completion notes",
        "quality-check results",
        "owner approval state",
    ]
    if plan.get("primary_capability_id") == "web_software":
        evidence.extend(["focused test results", "changed-file list", "rollback notes"])
    if plan.get("primary_capability_id") == "ai_workflow_automation":
        evidence.extend(["workflow test cases", "failure-path evidence", "rollback/manual fallback"])

    blockers: list[str] = []
    if not fit["fit"]:
        blockers.extend(fit.get("blockers") or [])
        if not blockers:
            blockers.append("no_confirmed_nova_capability")
    if not plan.get("execution_ready"):
        blockers.append("execution_playbook_missing")

    return {
        "packet_version": 1,
        "title": title,
        "company_name": company,
        "execution_ready": not blockers,
        "primary_capability_id": plan.get("primary_capability_id"),
        "capability_score": fit.get("score"),
        "matched_capabilities": fit.get("capabilities") or [],
        "required_inputs": required_inputs,
        "tasks": tasks,
        "deliverables": deliverables,
        "quality_checks": checks,
        "completion_evidence_required": evidence,
        "owner_gates": owner_gates,
        "blockers": blockers,
        "status": "READY_FOR_INTERNAL_WORK" if not blockers else "BLOCKED",
        "external_submission": False,
        "client_contact": False,
        "contract_acceptance": False,
        "production_deploy": False,
        "financial_execution": False,
    }


def work_packet_summary(packet: dict[str, Any]) -> str:
    """Human-readable internal summary for application/work-plan drafts."""
    if not packet.get("execution_ready"):
        return "Nova execution packet is blocked until capability fit and owner requirements are resolved."
    primary = packet.get("primary_capability_id") or "unknown"
    deliverables = ", ".join(packet.get("deliverables") or []) or "owner-confirmed deliverables"
    checks = "; ".join(packet.get("quality_checks") or []) or "owner review"
    return (
        f"Primary capability: {primary}. "
        f"Planned deliverables: {deliverables}. "
        f"Quality controls: {checks}."
    )
