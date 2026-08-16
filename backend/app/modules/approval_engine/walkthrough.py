"""Ordered BASE ambulatory onboarding walkthrough for production validation.

Classifies each step by who enters data, what is uploaded, what AI can review,
what requires external verification, and what requires owner/admin approval.
STS / FUTURE MHCP steps are listed separately and are not part of BASE activation.
"""
from __future__ import annotations

from typing import Any

# Actor / review classifications used in the walkthrough UI and reports.
DRIVER_ENTERS = "driver_enters"
DRIVER_UPLOADS = "driver_uploads"
AI_AUTO_REVIEW = "ai_auto_review"
EXTERNAL_VERIFICATION = "external_verification"
OWNER_ADMIN_APPROVAL = "owner_admin_approval"

BASE_AMBULATORY_WALKTHROUGH: list[dict[str, Any]] = [
    {
        "order": 1,
        "requirement_key": "identity_complete",
        "label": "Identity and contact information",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_now",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": [
            "Legal first / middle / last name",
            "Email",
            "Mobile phone",
            "Home address, city, state, ZIP",
            "Emergency contact name and phone",
            "Preferred language",
        ],
        "driver_uploads": [],
        "ai_auto_review": [
            "Required fields present",
            "Phone/email format sanity",
            "Inconsistent blank vs filled identity blocks",
        ],
        "external_verification": [],
        "owner_admin_approval": [
            "Final package approval only (not a substitute for missing identity fields)",
        ],
        "notes": "Driver completes via the same Platform Ops application form future drivers use.",
    },
    {
        "order": 2,
        "requirement_key": "age_verified",
        "label": "Date of birth / age verification status",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_now",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": ["Date of birth"],
        "driver_uploads": [],
        "ai_auto_review": [
            "DOB present",
            "Obvious format/range inconsistency flags",
        ],
        "external_verification": [
            "Authoritative age/identity confirmation when required by Amicor policy (not auto-passed by AI)",
        ],
        "owner_admin_approval": [
            "Owner approves package only after requirements are satisfied — cannot invent age verification",
        ],
        "notes": "AI records presence/status only; does not fabricate identity proof.",
    },
    {
        "order": 3,
        "requirement_key": "drivers_license",
        "label": "Driver license",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": True,
        "driver_enters": [
            "License number",
            "Issuing state",
            "License expiration date",
            "Years of driving experience",
            "Declaration: valid license",
        ],
        "driver_uploads": [
            "drivers_license_front",
            "drivers_license_back",
        ],
        "ai_auto_review": [
            "Required license fields present",
            "Expiration not past today (date check)",
            "Front/back upload present vs missing",
            "Inconsistency between entered expiration and missing upload",
        ],
        "external_verification": [
            "License authenticity / DMV confirmation when Amicor uses an external verifier",
        ],
        "owner_admin_approval": [
            "Owner may approve the file only after license requirement is green — APPROVE cannot turn a missing/expired license green",
        ],
        "notes": "Legal blocker. Human/external evidence required before COMPLETE.",
    },
    {
        "order": 4,
        "requirement_key": "mvr",
        "label": "Motor vehicle record (MVR)",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": True,
        "driver_enters": [
            "MVR authorization declaration",
        ],
        "driver_uploads": [
            "motor_vehicle_record_consent",
        ],
        "ai_auto_review": [
            "Consent/declaration present",
            "Creates EXTERNAL task for MVR request — never marks MVR complete automatically",
        ],
        "external_verification": [
            "MVR pull from authorized provider",
            "MVR review result recorded by human/external actor with evidence",
        ],
        "owner_admin_approval": [
            "Owner package approval after MVR COMPLETE with evidence — not a substitute for MVR",
        ],
        "notes": "AI prepares instructions/reminders only. Fabricating MVR results is prohibited.",
    },
    {
        "order": 5,
        "requirement_key": "vehicle_registration",
        "label": "Vehicle registration",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": True,
        "driver_enters": [
            "Vehicle make / model / year / plate (application or vehicle record)",
        ],
        "driver_uploads": [
            "vehicle_registration",
        ],
        "ai_auto_review": [
            "Upload present",
            "Document expiration date vs today when provided",
            "Missing/expired registration flagged",
        ],
        "external_verification": [
            "Registration authenticity when Amicor uses an external verifier",
        ],
        "owner_admin_approval": [
            "Package approval only; cannot override missing/expired registration without evidence/exception",
        ],
        "notes": "Legal blocker for activation.",
    },
    {
        "order": 6,
        "requirement_key": "vehicle_insurance",
        "label": "Auto insurance",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": True,
        "driver_enters": [
            "Insurance policy reference when collected on application",
        ],
        "driver_uploads": [
            "proof_of_auto_insurance",
        ],
        "ai_auto_review": [
            "Upload present/missing",
            "Expiration date check when provided",
            "Opens insurance_verification external task — does not invent insurer confirmation",
        ],
        "external_verification": [
            "Insurance carrier / COI verification",
        ],
        "owner_admin_approval": [
            "Package approval after insurance verified — APPROVE is not insurance verification",
        ],
        "notes": "Legal blocker. Upload ≠ verified until external/human confirms.",
    },
    {
        "order": 7,
        "requirement_key": "vehicle_inspection",
        "label": "Vehicle inspection",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": [],
        "driver_uploads": [
            "vehicle_inspection_record",
        ],
        "ai_auto_review": [
            "Inspection record present/missing",
            "Expiration date check when provided",
        ],
        "external_verification": [
            "Inspection station / authorized inspector confirmation when required",
        ],
        "owner_admin_approval": [
            "Package approval after inspection requirement satisfied",
        ],
        "notes": "Blocking for BASE activation under Amicor readiness rules; authoritative inspection source may still be needed.",
    },
    {
        "order": 8,
        "requirement_key": "base_training",
        "label": "Required BASE training modules",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": [
            "Completes assigned modules in training tracker / uploads certificates when applicable",
        ],
        "driver_uploads": [
            "training_certificates (when used)",
            "cpr_first_aid_certificate (when required by module set)",
        ],
        "ai_auto_review": [
            "Module assignment status (assigned / in_progress / completed / failed / expired)",
            "Incomplete training → next action",
        ],
        "external_verification": [
            "Instructor-led or third-party course completion confirmation when Amicor uses external trainers",
        ],
        "owner_admin_approval": [
            "Package approval after required modules completed — cannot mark training complete by APPROVE alone",
        ],
        "notes": "STS-only modules are not required for BASE.",
    },
    {
        "order": 9,
        "requirement_key": "contractor_agreement",
        "label": "Independent contractor agreement",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": [
            "Electronic signature / signed date on application declarations",
        ],
        "driver_uploads": [
            "independent_contractor_agreement",
        ],
        "ai_auto_review": [
            "Agreement document accepted/present",
            "Signature fields present when required",
        ],
        "external_verification": [],
        "owner_admin_approval": [
            "Confirms agreement accepted as part of READY_FOR_APPROVAL package",
        ],
        "notes": "Required before paid activation.",
    },
    {
        "order": 10,
        "requirement_key": "w9",
        "label": "W-9 / tax documentation status",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": [
            "W-9 status acknowledgment (status-only category — sensitive tax data not stored in plaintext beyond existing patterns)",
        ],
        "driver_uploads": [
            "w9_status (status-only / secure handling per Platform Ops storage rules)",
        ],
        "ai_auto_review": [
            "Status provided/verified/signed vs missing",
        ],
        "external_verification": [
            "Tax form completeness review by authorized admin/finance when required",
        ],
        "owner_admin_approval": [
            "Package approval after W-9 status complete",
        ],
        "notes": "Do not store unnecessary sensitive tax data in plaintext.",
    },
    {
        "order": 11,
        "requirement_key": "payout_setup",
        "label": "Payout method setup",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": [
            "Payout method details in the payout system Amicor configures",
        ],
        "driver_uploads": [],
        "ai_auto_review": [
            "payout_setup_status completeness flag (COMPLETE/READY vs PENDING)",
            "Blocks paid activation when incomplete",
        ],
        "external_verification": [
            "Payout provider / bank account validation",
        ],
        "owner_admin_approval": [
            "Owner/admin confirms payout readiness as part of activation conditions",
        ],
        "notes": "Driver cannot be activated for paid rides until payout setup is complete.",
    },
    {
        "order": 12,
        "requirement_key": "owner_package_approval",
        "label": "Owner / admin material approval gate",
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "timing": "required_before_activation",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": [],
        "driver_uploads": [],
        "ai_auto_review": [
            "Moves case to READY_FOR_APPROVAL only when mandatory BASE blockers are clear",
            "Builds approval card (green/yellow/red requirements, warnings, audit summary)",
        ],
        "external_verification": [],
        "owner_admin_approval": [
            "Authenticated owner/admin APPROVE / REJECT / RETURN FOR CORRECTION",
            "APPROVE records actor + timestamp + immutable audit event",
            "APPROVE cannot green legal blockers; activation still requires valid conditions",
        ],
        "notes": "Human approval is required for the material decision — AI does not self-approve.",
    },
]

# Explicitly NOT part of BASE activation unless requested tiers include them.
NON_BASE_SEPARATE_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "order": 100,
        "requirement_key": "background_study",
        "label": "Minnesota background study",
        "service_tier": "STS_ELIGIBLE / FUTURE_MHCP_NEMT",
        "timing": "not_required_for_base",
        "is_blocking": True,
        "is_legal_block": True,
        "driver_enters": ["Background-study consent / authorization"],
        "driver_uploads": ["background_check_consent"],
        "ai_auto_review": ["Consent present; opens external task — never fabricates clearance"],
        "external_verification": ["Minnesota background-study system result"],
        "owner_admin_approval": ["Only after external clearance recorded with evidence"],
        "notes": "Kept separate from BASE. Not required for BASE ambulatory activation.",
    },
    {
        "order": 101,
        "requirement_key": "fingerprint",
        "label": "Fingerprinting",
        "service_tier": "STS_ELIGIBLE / FUTURE_MHCP_NEMT (conditional)",
        "timing": "not_required_for_base",
        "is_blocking": True,
        "is_legal_block": True,
        "driver_enters": [],
        "driver_uploads": [],
        "ai_auto_review": ["Sets NOT_REQUIRED for BASE; REQUIRED only when STS/MHCP rule applies"],
        "external_verification": ["Fingerprint appointment / vendor result"],
        "owner_admin_approval": ["Cannot universalize fingerprinting via APPROVE"],
        "notes": "NOT_REQUIRED for BASE_PRIVATE_AMBULATORY.",
    },
    {
        "order": 102,
        "requirement_key": "sts_training",
        "label": "STS-specific training / BTW evaluation",
        "service_tier": "STS_ELIGIBLE",
        "timing": "not_required_for_base",
        "is_blocking": True,
        "is_legal_block": False,
        "driver_enters": ["Completes STS modules when STS tier requested"],
        "driver_uploads": [],
        "ai_auto_review": ["Tracks STS module completion only when STS tier applies"],
        "external_verification": ["BTW evaluator confirmation when used"],
        "owner_admin_approval": ["STS package approval separate from BASE"],
        "notes": "Do not force on Driver #001 BASE validation.",
    },
    {
        "order": 103,
        "requirement_key": "mhcp_credentialing",
        "label": "MHCP / NEMT credentialing",
        "service_tier": "FUTURE_MHCP_NEMT",
        "timing": "future_requirement",
        "is_blocking": True,
        "is_legal_block": True,
        "driver_enters": [],
        "driver_uploads": [],
        "ai_auto_review": ["Marked future_requirement — not BASE activation criteria"],
        "external_verification": ["Government / third-party MHCP credentialing"],
        "owner_admin_approval": ["Future pathway only"],
        "notes": "Kept separate from BASE.",
    },
]


def base_walkthrough() -> list[dict[str, Any]]:
    return list(BASE_AMBULATORY_WALKTHROUGH)


def non_base_walkthrough() -> list[dict[str, Any]]:
    return list(NON_BASE_SEPARATE_REQUIREMENTS)


def classify_step(step: dict[str, Any]) -> dict[str, list[str]]:
    return {
        DRIVER_ENTERS: list(step.get("driver_enters") or []),
        DRIVER_UPLOADS: list(step.get("driver_uploads") or []),
        AI_AUTO_REVIEW: list(step.get("ai_auto_review") or []),
        EXTERNAL_VERIFICATION: list(step.get("external_verification") or []),
        OWNER_ADMIN_APPROVAL: list(step.get("owner_admin_approval") or []),
    }


def merge_walkthrough_with_case_state(
    *,
    case_requirements: list[Any] | None,
    next_required_action: str | None = None,
    ai_summary: str | None = None,
    workflow_status: str | None = None,
) -> dict[str, Any]:
    """Attach live traffic-light/status to the ordered BASE walkthrough."""
    by_key = {}
    for req in case_requirements or []:
        key = getattr(req, "requirement_key", None) or (req.get("requirement_key") if isinstance(req, dict) else None)
        if not key:
            continue
        if isinstance(req, dict):
            by_key[key] = req
        else:
            by_key[key] = {
                "status": req.status,
                "traffic_light": req.traffic_light,
                "is_blocking": req.is_blocking,
                "is_legal_block": req.is_legal_block,
                "expiration_date": req.expiration_date.isoformat() if getattr(req, "expiration_date", None) else None,
            }

    steps = []
    first_blocker_order = None
    for step in BASE_AMBULATORY_WALKTHROUGH:
        key = step["requirement_key"]
        live = by_key.get(key) or {}
        if key == "owner_package_approval":
            status = "READY" if workflow_status == "READY_FOR_APPROVAL" else (
                "APPROVED" if workflow_status in {"OWNER_APPROVED", "APPROVED", "ACTIVE"} else "PENDING"
            )
            traffic = "green" if status in {"READY", "APPROVED"} else "yellow"
        else:
            status = live.get("status") or "NOT_STARTED"
            traffic = live.get("traffic_light") or "red"
        if first_blocker_order is None and traffic == "red" and step.get("is_blocking"):
            first_blocker_order = step["order"]
        steps.append(
            {
                **step,
                "classifications": classify_step(step),
                "live_status": status,
                "live_traffic_light": traffic,
                "is_current_focus": first_blocker_order == step["order"],
            }
        )

    return {
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "dispatch_gate_enabled": False,
        "policy": (
            "AI detects missing/expired/inconsistent items and sets next actions. "
            "External verifications are never fabricated. Owner APPROVE cannot green legal blockers. "
            "STS/FUTURE MHCP requirements stay separate unless those tiers are requested."
        ),
        "ordered_steps": steps,
        "non_base_separate_steps": [
            {**step, "classifications": classify_step(step)} for step in NON_BASE_SEPARATE_REQUIREMENTS
        ],
        "next_required_action": next_required_action,
        "ai_summary": ai_summary,
        "workflow_status": workflow_status,
        "current_focus_order": first_blocker_order,
    }
