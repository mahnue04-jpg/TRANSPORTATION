"""Simple driver-facing message templates.

Prepared for future notification delivery. Does not send external messages unless
an already-approved messaging integration is wired by the caller.
"""
from __future__ import annotations

from typing import Any

from app.modules.approval_engine.models import ApprovalCase


TEMPLATES = {
    "upload_insurance": "Please upload your current insurance card.",
    "license_expiring": "Your driver's license expires soon. Please upload the renewed license.",
    "next_step_ready": "Your next onboarding step is ready.",
    "additional_verification": "Additional verification is required. Follow these instructions.",
    "application_approved": "Your Amicor driver application has been approved.",
    "application_submitted": (
        "Application submitted. Amicor is reviewing your information. "
        "We will notify you if anything else is needed."
    ),
    "upload_registration": "Please upload your current vehicle registration.",
    "upload_license": "Please upload clear photos of the front and back of your driver's license.",
    "complete_agreement": "Please complete your independent contractor agreement.",
    "complete_payout": "Please finish your secure payout setup so you can get paid.",
}


def render_template(key: str, *, instructions: str | None = None) -> str:
    base = TEMPLATES.get(key) or TEMPLATES["additional_verification"]
    if instructions and key == "additional_verification":
        return f"{base} {instructions}".strip()
    return base


def messages_for_case(case: ApprovalCase) -> list[dict[str, Any]]:
    """Generate simple applicant messages from live case state. Does not send."""
    out: list[dict[str, Any]] = []
    if case.workflow_status in {"OWNER_APPROVED", "APPROVED", "ACTIVE"}:
        out.append(
            {
                "key": "application_approved",
                "message": render_template("application_approved"),
                "delivery": "prepared_not_sent",
            }
        )
        return out

    reqs = {r.requirement_key: r for r in (case.requirements or [])}
    insurance = reqs.get("vehicle_insurance")
    if insurance and insurance.status in {"MISSING", "ACTION_REQUIRED", "EXPIRED"}:
        out.append(
            {
                "key": "upload_insurance",
                "message": render_template("upload_insurance"),
                "delivery": "prepared_not_sent",
            }
        )
    license_req = reqs.get("drivers_license")
    if license_req and license_req.status in {"MISSING", "ACTION_REQUIRED", "EXPIRED"}:
        key = "license_expiring" if license_req.status == "EXPIRED" else "upload_license"
        out.append({"key": key, "message": render_template(key), "delivery": "prepared_not_sent"})
    registration = reqs.get("vehicle_registration")
    if registration and registration.status in {"MISSING", "ACTION_REQUIRED", "EXPIRED"}:
        out.append(
            {
                "key": "upload_registration",
                "message": render_template("upload_registration"),
                "delivery": "prepared_not_sent",
            }
        )
    contractor = reqs.get("contractor_agreement")
    if contractor and contractor.status in {"MISSING", "ACTION_REQUIRED"}:
        out.append(
            {
                "key": "complete_agreement",
                "message": render_template("complete_agreement"),
                "delivery": "prepared_not_sent",
            }
        )
    payout = reqs.get("payout_setup")
    if payout and payout.status in {"MISSING", "ACTION_REQUIRED"}:
        out.append(
            {
                "key": "complete_payout",
                "message": render_template("complete_payout"),
                "delivery": "prepared_not_sent",
            }
        )

    pending_external = [
        r
        for r in (case.requirements or [])
        if r.status in {"PENDING_EXTERNAL", "SUBMITTED", "MANUAL_REVIEW"} and r.is_blocking
    ]
    if pending_external and case.workflow_status in {"EXTERNAL_VERIFICATION", "ACTION_REQUIRED", "AI_REVIEW"}:
        out.append(
            {
                "key": "additional_verification",
                "message": render_template(
                    "additional_verification",
                    instructions="Amicor is completing required checks. No action needed unless we contact you.",
                ),
                "delivery": "prepared_not_sent",
            }
        )
    elif case.next_required_action and case.workflow_status == "ACTION_REQUIRED":
        out.append(
            {
                "key": "next_step_ready",
                "message": render_template("next_step_ready"),
                "delivery": "prepared_not_sent",
            }
        )

    if not out and case.workflow_status in {"PENDING", "AI_REVIEW", "EXTERNAL_VERIFICATION", "submitted"}:
        out.append(
            {
                "key": "application_submitted",
                "message": render_template("application_submitted"),
                "delivery": "prepared_not_sent",
            }
        )
    return out


def applicant_facing_status(case: ApprovalCase | None, *, application_status: str | None = None) -> dict[str, Any]:
    if case is None:
        return {
            "headline": render_template("application_submitted"),
            "needs_action": False,
            "messages": [
                {
                    "key": "application_submitted",
                    "message": render_template("application_submitted"),
                    "delivery": "prepared_not_sent",
                }
            ],
            "internal_status_hidden": True,
        }
    messages = messages_for_case(case)
    action_keys = {
        "upload_insurance",
        "upload_license",
        "license_expiring",
        "upload_registration",
        "complete_agreement",
        "complete_payout",
        "next_step_ready",
    }
    needs_action = any(m["key"] in action_keys for m in messages)
    headline = (
        messages[0]["message"]
        if needs_action and messages
        else render_template("application_submitted")
    )
    if case.workflow_status in {"OWNER_APPROVED", "APPROVED", "ACTIVE"}:
        headline = render_template("application_approved")
    return {
        "headline": headline,
        "needs_action": needs_action,
        "messages": messages,
        "internal_status_hidden": True,
        "application_status": application_status,
    }
