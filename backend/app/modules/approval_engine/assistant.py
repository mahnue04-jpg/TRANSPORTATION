"""AI Assistant query handlers for approval-engine live data."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.modules.approval_engine.audit import list_audit_events, serialize_audit
from app.modules.approval_engine.compliance import list_expiring
from app.modules.approval_engine.eligibility import evaluate_driver_ride_eligibility
from app.modules.approval_engine.models import ApprovalCase
from app.modules.approval_engine.driver_001 import get_driver_001_status
from app.modules.approval_engine.walkthrough import base_walkthrough
from app.modules.approval_engine.workflow import (
    blocking_requirements,
    build_approval_card,
    get_case,
    get_case_by_badge,
    list_cases,
)


def _resolve_case(db: Session, organization_id: str, token: str) -> ApprovalCase | None:
    text = str(token or "").strip()
    if not text:
        return None
    upper = text.upper()
    if upper.startswith("DRV-") or upper.startswith("DRIVER #") or upper.startswith("DRIVER#"):
        badge = upper.replace("DRIVER #", "DRV-").replace("DRIVER#", "DRV-")
        if badge.startswith("DRV") and not badge.startswith("DRV-"):
            badge = "DRV-" + badge[3:]
        if re.fullmatch(r"DRV-[A-Z0-9-]+", badge):
            found = get_case_by_badge(db, organization_id, badge)
            if found:
                return found
        # Driver #001 → DRV-001
        digits = re.sub(r"\D", "", upper)
        if digits:
            found = get_case_by_badge(db, organization_id, f"DRV-{int(digits):03d}")
            if found:
                return found
    case = get_case(db, text)
    if case and case.organization_id == organization_id:
        return case
    return (
        db.query(ApprovalCase)
        .filter(
            ApprovalCase.organization_id == organization_id,
            (ApprovalCase.health_isf_driver_id == text)
            | (ApprovalCase.application_id == text)
            | (ApprovalCase.entity_id == text),
        )
        .first()
    )


def handle_assistant_query(
    db: Session,
    *,
    organization_id: str,
    query: str,
    ride: Any | None = None,
) -> dict[str, Any]:
    text = str(query or "").strip()
    lower = text.lower()

    if "waiting for approval" in lower or "ready for approval" in lower:
        cases = list_cases(db, organization_id=organization_id, workflow_status="READY_FOR_APPROVAL")
        return {
            "intent": "drivers_waiting_for_approval",
            "count": len(cases),
            "cases": [
                {
                    "case_id": c.id,
                    "display_badge": c.display_badge,
                    "name": c.legal_name,
                    "readiness_percentage": c.readiness_percentage,
                    "summary": c.ai_summary,
                }
                for c in cases
            ],
            "source": "live_approval_engine",
        }

    if "expiring" in lower or "expire" in lower:
        days = 30
        match = re.search(r"(\d+)\s*day", lower)
        if match:
            days = int(match.group(1))
        rows = list_expiring(db, organization_id=organization_id, within_days=days)
        return {
            "intent": "documents_expiring",
            "within_days": days,
            "count": len(rows),
            "items": rows,
            "source": "live_approval_engine",
        }

    if "suspended" in lower:
        cases = list_cases(db, organization_id=organization_id, workflow_status="SUSPENDED")
        restricted = list_cases(db, organization_id=organization_id, workflow_status="RESTRICTED")
        return {
            "intent": "suspended_and_restricted",
            "suspended": [
                {
                    "case_id": c.id,
                    "display_badge": c.display_badge,
                    "name": c.legal_name,
                    "reason": c.suspension_restriction_reason,
                }
                for c in cases
            ],
            "restricted": [
                {
                    "case_id": c.id,
                    "display_badge": c.display_badge,
                    "name": c.legal_name,
                    "reason": c.suspension_restriction_reason,
                }
                for c in restricted
            ],
            "source": "live_approval_engine",
        }

    if "approval summary" in lower or "prepare approval" in lower:
        token = text
        for prefix in ("prepare approval summary for", "approval summary for", "show approval summary for"):
            if prefix in lower:
                token = text[lower.index(prefix) + len(prefix) :].strip(" .?")
                break
        case = _resolve_case(db, organization_id, token)
        if not case:
            return {"intent": "approval_summary", "error": "Case not found", "token": token}
        return {
            "intent": "approval_summary",
            "card": build_approval_card(case),
            "source": "live_approval_engine",
        }

    if "blocking" in lower or "what is blocking" in lower:
        token = text
        for prefix in ("what is blocking", "what's blocking", "blocking"):
            if prefix in lower:
                token = text[lower.index(prefix) + len(prefix) :].strip(" .?")
                break
        case = _resolve_case(db, organization_id, token)
        if not case:
            return {"intent": "blocking_items", "error": "Case not found", "token": token}
        blockers = blocking_requirements(case)
        return {
            "intent": "blocking_items",
            "case_id": case.id,
            "display_badge": case.display_badge,
            "workflow_status": case.workflow_status,
            "readiness_percentage": case.readiness_percentage,
            "ai_summary": case.ai_summary,
            "next_required_action": case.next_required_action,
            "blockers": [
                {
                    "key": b.requirement_key,
                    "label": b.label,
                    "status": b.status,
                    "traffic_light": b.traffic_light,
                    "is_legal_block": b.is_legal_block,
                }
                for b in blockers
            ],
            "source": "live_approval_engine",
        }

    if "driver #001" in lower or "drv-001" in lower or "driver 001" in lower:
        if "walkthrough" in lower or "requirements" in lower or "onboarding" in lower:
            status = get_driver_001_status(db, organization_id=organization_id)
            return {
                "intent": "driver_001_walkthrough",
                "status": status,
                "base_steps": base_walkthrough(),
                "source": "live_approval_engine",
            }
        status = get_driver_001_status(db, organization_id=organization_id)
        return {
            "intent": "driver_001_status",
            "status": status,
            "source": "live_approval_engine",
        }

    if "why was" in lower and "excluded" in lower:
        match = re.search(r"why was (.+?) excluded", lower)
        token = match.group(1).strip() if match else text
        case = _resolve_case(db, organization_id, token)
        if not case:
            return {"intent": "exclusion_reason", "error": "Case not found", "token": token}
        return {
            "intent": "exclusion_reason",
            "case_id": case.id,
            "display_badge": case.display_badge,
            "workflow_status": case.workflow_status,
            "reason": case.suspension_restriction_reason or case.next_required_action or case.ai_summary,
            "approved_tiers": case.approved_service_tiers_json,
            "source": "live_approval_engine",
        }

    if "can legally accept" in lower or "eligible for this ride" in lower:
        if ride is None:
            return {
                "intent": "ride_eligibility",
                "error": "Ride context required",
                "source": "live_approval_engine",
            }
        cases = list_cases(db, organization_id=organization_id, workflow_status="ACTIVE")
        eligible = []
        excluded = []
        for case in cases:
            driver_id = case.health_isf_driver_id or case.entity_id
            if not driver_id:
                continue
            result = evaluate_driver_ride_eligibility(
                db, organization_id=organization_id, driver_id=driver_id, ride=ride
            )
            row = {
                "case_id": case.id,
                "display_badge": case.display_badge,
                "name": case.legal_name,
                "driver_id": driver_id,
                **result,
            }
            if result.get("eligible"):
                eligible.append(row)
            else:
                excluded.append(row)
        return {
            "intent": "ride_eligibility",
            "eligible": eligible,
            "excluded": excluded,
            "source": "live_approval_engine",
        }

    if "audit" in lower:
        token = text
        case = _resolve_case(db, organization_id, token) if "driver" in lower else None
        events = list_audit_events(
            db,
            organization_id=organization_id,
            case_id=case.id if case else None,
            limit=50,
        )
        return {
            "intent": "audit_log",
            "count": len(events),
            "events": [serialize_audit(e) for e in events],
            "source": "live_approval_engine",
        }

    return {
        "intent": "unknown",
        "message": (
            "Supported queries: waiting for approval; blocking Driver #001; "
            "Driver #001 walkthrough; documents expiring in 30 days; "
            "legally accept this ride; why excluded; approval summary; suspended drivers."
        ),
        "source": "live_approval_engine",
    }
