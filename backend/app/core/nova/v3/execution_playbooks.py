"""Execution playbooks for AMICOR Nova sellable service capabilities.

These playbooks define HOW Nova should execute work after a legitimate engagement
exists. They do not authorize external submission, contract acceptance, client
contact, credential use, invoicing, payment, or money movement.
"""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.capability_catalog import CAPABILITIES

_COMMON_OWNER_GATES = (
    "approve_scope",
    "approve_external_delivery",
)

PLAYBOOKS: dict[str, dict[str, Any]] = {
    "business_research": {
        "required_inputs": (
            "business question or objective",
            "target market/company/topic",
            "deadline",
            "required format",
        ),
        "steps": (
            "clarify research question and acceptance criteria",
            "build source plan",
            "collect and organize evidence",
            "compare and analyze findings",
            "draft concise conclusions with source traceability",
            "run factual consistency and completeness review",
            "prepare owner-review deliverable",
        ),
        "quality_checks": (
            "sources are attributable",
            "claims match evidence",
            "assumptions are labeled",
            "requested scope is fully covered",
            "no fabricated facts or citations",
        ),
        "owner_gates": _COMMON_OWNER_GATES,
    },
    "administrative_operations": {
        "required_inputs": (
            "task list or operating objective",
            "approved source documents",
            "priority/deadline rules",
            "required output format",
        ),
        "steps": (
            "inventory tasks and constraints",
            "organize tasks by urgency and dependency",
            "extract action items and owners",
            "draft trackers, summaries, SOPs, or schedules",
            "check for missing dates, names, and dependencies",
            "prepare owner-review package",
        ),
        "quality_checks": (
            "no invented appointments or commitments",
            "deadlines are preserved",
            "tasks are traceable to source material",
            "external messages remain draft-only unless separately authorized",
        ),
        "owner_gates": _COMMON_OWNER_GATES,
    },
    "data_spreadsheet": {
        "required_inputs": (
            "source dataset",
            "requested metrics/output",
            "column definitions",
            "business rules",
        ),
        "steps": (
            "profile the source data",
            "identify missing, duplicate, and invalid values",
            "clean and normalize data",
            "apply calculations and transformations",
            "build requested spreadsheet/report structure",
            "validate totals and sample records",
            "prepare owner-review output",
        ),
        "quality_checks": (
            "row counts reconcile where applicable",
            "formulas are internally consistent",
            "no silent data deletion",
            "assumptions and transformations are documented",
        ),
        "owner_gates": _COMMON_OWNER_GATES,
    },
    "ai_workflow_automation": {
        "required_inputs": (
            "current workflow",
            "desired outcome",
            "approved systems/connectors",
            "trigger and action rules",
            "test examples",
        ),
        "steps": (
            "map current-state workflow",
            "define trigger, actions, conditions, and failure paths",
            "design least-privilege integration plan",
            "build or draft automation in an isolated/test context",
            "run deterministic test cases",
            "document rollback and manual fallback",
            "prepare implementation package for owner approval",
        ),
        "quality_checks": (
            "no production mutation without explicit approval",
            "credentials are never exposed in output",
            "failure and retry behavior is documented",
            "test evidence covers success and failure cases",
        ),
        "owner_gates": (
            "approve_scope",
            "approve_credentials_or_connector_access",
            "approve_production_change",
            "approve_external_delivery",
        ),
    },
    "bookkeeping_support": {
        "required_inputs": (
            "transaction/receipt data",
            "chart or category rules if provided",
            "date range",
            "requested report",
        ),
        "steps": (
            "organize source financial records",
            "categorize transactions using provided rules",
            "flag uncertain classifications",
            "prepare reconciliation support",
            "build expense/invoice summary",
            "run arithmetic and duplicate checks",
            "prepare owner-review package",
        ),
        "quality_checks": (
            "does not claim CPA/audit/tax authority",
            "uncertain transactions are flagged rather than guessed",
            "totals reconcile to provided source data",
            "no payments are initiated",
        ),
        "owner_gates": _COMMON_OWNER_GATES,
    },
    "content_documentation": {
        "required_inputs": (
            "audience",
            "purpose",
            "source material",
            "tone/style requirements",
            "deadline",
        ),
        "steps": (
            "extract factual source points",
            "build outline",
            "draft content",
            "check consistency and unsupported claims",
            "edit for clarity and format",
            "prepare owner-review version",
        ),
        "quality_checks": (
            "no invented facts",
            "source-dependent claims are traceable",
            "tone matches client instructions",
            "deliverable satisfies requested format",
        ),
        "owner_gates": _COMMON_OWNER_GATES,
    },
    "web_software": {
        "required_inputs": (
            "functional requirements",
            "existing code or system context",
            "approved environment",
            "acceptance tests",
        ),
        "steps": (
            "translate requirements into implementation tasks",
            "inspect existing architecture before editing",
            "make isolated changes",
            "run focused automated tests",
            "run regression checks for affected paths",
            "document changed files, behavior, and rollback",
            "prepare owner-review build",
        ),
        "quality_checks": (
            "no production deploy without explicit approval",
            "no secret values in logs or code",
            "tests cover the requested behavior",
            "scope creep is identified before implementation",
        ),
        "owner_gates": (
            "approve_scope",
            "approve_repository_or_environment_access",
            "approve_merge",
            "approve_deploy",
            "approve_external_delivery",
        ),
    },
    "customer_support_operations": {
        "required_inputs": (
            "approved support content",
            "ticket examples or categories",
            "escalation rules",
            "response policy",
        ),
        "steps": (
            "classify issue types",
            "map routing and escalation rules",
            "draft response templates",
            "build FAQ/knowledge-base structure",
            "test against representative tickets",
            "prepare owner-review support package",
        ),
        "quality_checks": (
            "no customer contact without separate authorization",
            "escalation rules are preserved",
            "sensitive cases are not auto-resolved",
            "templates do not make unauthorized promises",
        ),
        "owner_gates": _COMMON_OWNER_GATES,
    },
    "proposal_rfp": {
        "required_inputs": (
            "RFP or buyer requirements",
            "approved company facts",
            "pricing authority or pricing inputs",
            "deadline",
        ),
        "steps": (
            "extract mandatory requirements",
            "build compliance matrix",
            "identify missing owner facts",
            "draft technical/business response",
            "flag pricing/legal commitments for owner input",
            "run requirement-by-requirement completeness check",
            "prepare submission package for owner review",
        ),
        "quality_checks": (
            "no invented credentials or past performance",
            "no unapproved price or legal commitment",
            "all mandatory requirements are addressed or flagged",
            "submission remains owner-controlled",
        ),
        "owner_gates": (
            "approve_scope",
            "approve_company_facts",
            "approve_pricing",
            "approve_external_submission",
        ),
    },
    "document_intelligence": {
        "required_inputs": (
            "source documents",
            "requested fields/questions",
            "output schema",
        ),
        "steps": (
            "inventory documents",
            "extract requested fields and passages",
            "normalize structured values",
            "flag unreadable or ambiguous sections",
            "compare or summarize as requested",
            "validate samples against source pages",
            "prepare owner-review deliverable",
        ),
        "quality_checks": (
            "extracted values are source-traceable",
            "uncertain text is flagged",
            "no fabricated missing fields",
            "document boundaries and versions are preserved",
        ),
        "owner_gates": _COMMON_OWNER_GATES,
    },
}


def _validate_catalog_alignment() -> None:
    missing = sorted(set(CAPABILITIES) - set(PLAYBOOKS))
    extra = sorted(set(PLAYBOOKS) - set(CAPABILITIES))
    if missing or extra:
        raise RuntimeError(
            f"Capability/playbook mismatch: missing={missing}, extra={extra}"
        )


_validate_catalog_alignment()


def execution_playbook(capability_id: str) -> dict[str, Any] | None:
    """Return one normalized read-only execution playbook."""
    spec = PLAYBOOKS.get(str(capability_id or "").strip())
    if spec is None:
        return None
    cap = CAPABILITIES[capability_id]
    return {
        "capability_id": capability_id,
        "label": cap["label"],
        "required_inputs": list(spec["required_inputs"]),
        "steps": list(spec["steps"]),
        "quality_checks": list(spec["quality_checks"]),
        "owner_gates": list(spec["owner_gates"]),
        "external_submission": False,
        "financial_execution": False,
    }


def execution_playbooks() -> list[dict[str, Any]]:
    """Return all playbooks in deterministic order."""
    return [
        execution_playbook(capability_id)
        for capability_id in CAPABILITIES
        if execution_playbook(capability_id) is not None
    ]


def execution_plan_for_matches(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Create an owner-controlled execution plan from capability matches."""
    if not matches:
        return {
            "execution_ready": False,
            "primary_capability_id": None,
            "playbook": None,
            "reason": "No matched Nova capability.",
            "external_submission": False,
            "financial_execution": False,
        }
    primary = str(matches[0].get("capability_id") or "")
    playbook = execution_playbook(primary)
    return {
        "execution_ready": playbook is not None,
        "primary_capability_id": primary or None,
        "playbook": playbook,
        "reason": (
            "Execution playbook available; owner approval gates still apply."
            if playbook is not None
            else "No execution playbook available."
        ),
        "external_submission": False,
        "financial_execution": False,
    }
