"""Owner-controlled autonomous execution planning for Nova Work & Revenue."""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.work_packets import build_work_packet

SAFE_INTERNAL = "SAFE_INTERNAL"
OWNER_GATE = "OWNER_GATE"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"

_VERTICAL_PROFILES: dict[str, dict[str, Any]] = {
    "delivery_logistics": {
        "signals": ("delivery", "courier", "dispatch", "logistics", "shipment", "fleet", "route"),
        "supported_work": (
            "dispatch administration",
            "shipment/order tracking",
            "route and fleet spreadsheet analysis",
            "customer-update drafting",
            "proof-of-delivery organization",
            "daily/weekly operations reporting",
            "invoice-support preparation",
        ),
    },
    "property_management": {
        "signals": ("property management", "tenant", "maintenance", "lease", "vendor"),
        "supported_work": (
            "maintenance request organization",
            "vendor tracking",
            "tenant follow-up drafting",
            "schedule preparation",
            "document and report preparation",
            "work-order tracking",
        ),
    },
    "home_care_admin": {
        "signals": ("home care", "homecare", "healthcare", "caregiver", "client schedule"),
        "supported_work": (
            "non-clinical scheduling support",
            "administrative follow-up drafting",
            "records organization",
            "non-clinical reporting",
            "document preparation",
        ),
    },
    "staffing_recruiting": {
        "signals": ("staffing", "recruiting", "candidate", "applicant", "talent"),
        "supported_work": (
            "candidate research",
            "interview schedule preparation",
            "follow-up drafting",
            "applicant record organization",
            "pipeline reporting",
        ),
    },
    "construction_services": {
        "signals": ("construction", "roofing", "plumbing", "contractor", "service company", "work order"),
        "supported_work": (
            "estimate and proposal drafting support",
            "job schedule preparation",
            "customer follow-up drafting",
            "work-order organization",
            "project reporting",
            "vendor/material research",
        ),
    },
}

_EXTERNAL_ACTION_WORDS = (
    "send", "submit", "contact client", "contact customer", "accept contract",
    "sign", "deploy", "invoice", "charge", "payment", "payout", "move money",
)
_OWNER_REVIEW_WORDS = (
    "approve", "owner-review", "owner review", "pricing", "credential",
    "connector access", "production change",
)


def detect_vertical(opportunity: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        str(opportunity.get(key) or "")
        for key in ("opportunity_title", "title", "company_name", "description", "requirements")
    ).lower()
    for vertical_id, spec in _VERTICAL_PROFILES.items():
        if any(signal in text for signal in spec["signals"]):
            return {"vertical_id": vertical_id, "supported_work": list(spec["supported_work"])}
    return {"vertical_id": "general_business_operations", "supported_work": []}


def _classify_task(task: str) -> str:
    value = str(task or "").lower()
    if any(word in value for word in _EXTERNAL_ACTION_WORDS):
        return BLOCKED_EXTERNAL
    if any(word in value for word in _OWNER_REVIEW_WORDS):
        return OWNER_GATE
    return SAFE_INTERNAL


def build_autonomous_execution_session(opportunity: dict[str, Any]) -> dict[str, Any]:
    """Convert a qualified work packet into a safe internal autonomous session."""
    packet = build_work_packet(opportunity)
    vertical = detect_vertical(opportunity)

    base = {
        "session_version": 1,
        "work_packet": packet,
        "vertical": vertical,
        "external_submission": False,
        "client_contact": False,
        "contract_acceptance": False,
        "production_deploy": False,
        "financial_execution": False,
    }
    if not packet.get("execution_ready"):
        return {
            **base,
            "autonomous_execution_ready": False,
            "status": "BLOCKED",
            "reason": "Work packet is not execution-ready.",
            "stages": [],
        }

    execution_tasks = []
    for row in packet.get("tasks") or []:
        task = str(row.get("task") or "")
        classification = _classify_task(task)
        execution_tasks.append(
            {
                **row,
                "execution_class": classification,
                "nova_may_advance": classification == SAFE_INTERNAL,
                "requires_owner_action": classification != SAFE_INTERNAL,
            }
        )

    stages = [
        {
            "stage": "INTAKE_AND_SCOPE",
            "status": "READY",
            "nova_may_advance": True,
            "checks": [
                "scope is tied to the qualified opportunity",
                "required inputs are identified",
                "missing facts remain explicit",
            ],
        },
        {
            "stage": "AUTONOMOUS_INTERNAL_EXECUTION",
            "status": "READY",
            "nova_may_advance": True,
            "tasks": execution_tasks,
            "rule": "Advance SAFE_INTERNAL tasks only; stop at owner gates or external actions.",
        },
        {
            "stage": "QUALITY_REVIEW",
            "status": "READY",
            "nova_may_advance": True,
            "checks": list(packet.get("quality_checks") or []),
        },
        {
            "stage": "OWNER_HANDOFF",
            "status": "WAITING_FOR_OWNER",
            "nova_may_advance": False,
            "owner_gates": list(packet.get("owner_gates") or []),
            "deliverables": list(packet.get("deliverables") or []),
        },
        {
            "stage": "EXTERNAL_DELIVERY_OR_FINANCIAL_ACTION",
            "status": "BLOCKED",
            "nova_may_advance": False,
            "blocked_actions": [
                "external submission",
                "client/customer contact",
                "contract acceptance or signature",
                "production deployment",
                "invoice sending or charging",
                "payment or payout execution",
            ],
        },
    ]
    return {
        **base,
        "autonomous_execution_ready": True,
        "status": "READY_FOR_AUTONOMOUS_INTERNAL_WORK",
        "primary_capability_id": packet.get("primary_capability_id"),
        "supported_vertical_work": vertical.get("supported_work") or [],
        "required_inputs": list(packet.get("required_inputs") or []),
        "deliverables": list(packet.get("deliverables") or []),
        "completion_evidence_required": list(packet.get("completion_evidence_required") or []),
        "stages": stages,
    }
