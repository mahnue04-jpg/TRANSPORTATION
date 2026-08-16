"""Driver + vehicle eligibility checks for trip assignment."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.approval_engine.models import ApprovalCase, ApprovalVehicleRecord
from app.modules.approval_engine.requirements import normalize_tiers


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return []


def dispatch_gate_enabled() -> bool:
    return str(os.getenv("AMICOR_APPROVAL_ENGINE_DISPATCH_GATE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def sts_mhcp_dispatch_enabled() -> bool:
    """STS/MHCP passenger dispatch stays disabled until AMICOR is authorized."""
    return str(os.getenv("AMICOR_STS_MHCP_DISPATCH_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _driver_is_onboarding_origin(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> tuple[bool, str]:
    from app.modules.health_isf.models import HealthISFDriver
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

    application = (
        db.query(PlatformDriverOnboardingApplication)
        .filter(PlatformDriverOnboardingApplication.activated_driver_id == driver_id)
        .first()
    )
    if application is not None:
        return True, "Driver is linked to a Platform Ops onboarding application"
    case = (
        db.query(ApprovalCase)
        .filter(
            ApprovalCase.organization_id == organization_id,
            ApprovalCase.health_isf_driver_id == driver_id,
        )
        .first()
    )
    if case is not None:
        badge = str(getattr(case, "display_badge", "") or "").upper()
        if badge == "DRV-001" or case.platform_ops_application_id:
            return True, "Driver is linked to an Approval Engine onboarding case"
    driver = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
    plate = str(getattr(driver, "vehicle_plate", "") or "").upper()
    if plate.startswith("ONBD-"):
        return True, "Driver vehicle plate is an onboarding placeholder"
    return False, ""


def driver_blocked_from_live_dispatch(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    ride: Any = None,
) -> dict[str, Any]:
    """Always-on hold for onboarding applicants and STS/MHCP. Independent of the dispatch gate."""
    required_tier = _ride_required_tier(ride) if ride is not None else "BASE_PRIVATE_AMBULATORY"
    if required_tier in {"STS_ELIGIBLE", "FUTURE_MHCP_NEMT"} and not sts_mhcp_dispatch_enabled():
        return {
            "blocked": True,
            "reason": "STS/MHCP passenger dispatch is disabled. AMICOR is not authorized.",
            "required_tier": required_tier,
        }
    origin, origin_reason = _driver_is_onboarding_origin(
        db, organization_id=organization_id, driver_id=driver_id
    )
    if origin:
        return {
            "blocked": True,
            "reason": (
                origin_reason
                + "; onboarding-origin drivers are not eligible for live passenger dispatch"
            ),
            "required_tier": required_tier,
        }
    case = get_active_case_for_driver(db, organization_id=organization_id, driver_id=driver_id)
    if case is not None and str(case.workflow_status or "").upper() != "ACTIVE":
        return {
            "blocked": True,
            "reason": f"Approval Engine status is {case.workflow_status}, not ACTIVE",
            "required_tier": required_tier,
            "case_id": case.id,
        }
    return {"blocked": False, "reason": "ok", "required_tier": required_tier}


def _ride_required_tier(ride: Any) -> str:
    raw = (
        getattr(ride, "service_tier", None)
        or getattr(ride, "required_service_tier", None)
        or getattr(ride, "priority_tag", None)
        or getattr(ride, "service_type", None)
        or "BASE_PRIVATE_AMBULATORY"
    )
    text = str(raw or "").strip().upper()
    if "STS" in text:
        return "STS_ELIGIBLE"
    if "MHCP" in text or "NEMT" in text:
        return "FUTURE_MHCP_NEMT"
    return "BASE_PRIVATE_AMBULATORY"


def get_active_case_for_driver(db: Session, *, organization_id: str, driver_id: str) -> ApprovalCase | None:
    return (
        db.query(ApprovalCase)
        .filter(
            ApprovalCase.organization_id == organization_id,
            ApprovalCase.health_isf_driver_id == driver_id,
        )
        .order_by(ApprovalCase.updated_at.desc())
        .first()
    )


def vehicle_is_assignable(vehicle: ApprovalVehicleRecord, *, required_tier: str) -> tuple[bool, str]:
    today = date.today()
    eligibility = str(getattr(vehicle, "eligibility_status", None) or "").upper()
    if eligibility in {"BLOCKED", "EXPIRED"}:
        return False, f"Vehicle {vehicle.id} eligibility is {eligibility}"
    if vehicle.vehicle_status in {"RESTRICTED", "EXPIRED", "SUSPENDED"}:
        return False, f"Vehicle {vehicle.id} status is {vehicle.vehicle_status}"
    if getattr(vehicle, "dispatch_activated", None) is False:
        return False, "Vehicle is recorded but not activated for live dispatch"
    for label, exp in (
        ("registration", vehicle.registration_expiration),
        ("insurance", vehicle.insurance_expiration),
        ("inspection", vehicle.inspection_expiration),
    ):
        if exp is not None and exp < today:
            return False, f"Vehicle {label} expired on {exp.isoformat()}"
    if required_tier in {"STS_ELIGIBLE", "FUTURE_MHCP_NEMT"}:
        # Wheelchair/specialized capability only if separately verified.
        needs_wheelchair = required_tier != "BASE_PRIVATE_AMBULATORY"
        if needs_wheelchair and getattr(vehicle, "wheelchair_required_hint", False):
            if not (vehicle.wheelchair_capable and vehicle.wheelchair_verified):
                return False, "Wheelchair capability not separately verified"
    if not vehicle.ambulatory_eligible and required_tier == "BASE_PRIVATE_AMBULATORY":
        return False, "Vehicle not ambulatory-eligible"
    return True, "ok"


def evaluate_driver_ride_eligibility(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    ride: Any,
) -> dict[str, Any]:
    required_tier = _ride_required_tier(ride)
    hold = driver_blocked_from_live_dispatch(
        db, organization_id=organization_id, driver_id=driver_id, ride=ride
    )
    if hold.get("blocked"):
        return {
            "eligible": False,
            "reason": hold.get("reason"),
            "required_tier": required_tier,
            "case_id": hold.get("case_id"),
            "onboarding_hold": True,
        }
    case = get_active_case_for_driver(db, organization_id=organization_id, driver_id=driver_id)
    if case is None:
        # Legacy drivers without an approval case remain eligible unless gate hard-requires cases.
        return {
            "eligible": not dispatch_gate_enabled(),
            "reason": "No approval-engine case on file"
            + ("; blocked by dispatch gate" if dispatch_gate_enabled() else "; legacy pass-through"),
            "required_tier": required_tier,
            "case_id": None,
        }

    if case.workflow_status != "ACTIVE":
        return {
            "eligible": False,
            "reason": f"Driver workflow status is {case.workflow_status}, not ACTIVE",
            "required_tier": required_tier,
            "case_id": case.id,
            "workflow_status": case.workflow_status,
        }

    approved = set(normalize_tiers(_json_list(case.approved_service_tiers_json)))
    if required_tier not in approved and required_tier != "BASE_PRIVATE_AMBULATORY":
        if "BASE_PRIVATE_AMBULATORY" in approved and required_tier == "BASE_PRIVATE_AMBULATORY":
            pass
        else:
            return {
                "eligible": False,
                "reason": (
                    f"Driver approved tiers {sorted(approved)} do not include required {required_tier}"
                ),
                "required_tier": required_tier,
                "approved_tiers": sorted(approved),
                "case_id": case.id,
            }
    if required_tier == "STS_ELIGIBLE" and "STS_ELIGIBLE" not in approved:
        return {
            "eligible": False,
            "reason": "Driver approved only for base ambulatory; STS trip excluded",
            "required_tier": required_tier,
            "approved_tiers": sorted(approved),
            "case_id": case.id,
        }
    if required_tier == "FUTURE_MHCP_NEMT" and "FUTURE_MHCP_NEMT" not in approved:
        return {
            "eligible": False,
            "reason": "Driver lacks MHCP/NEMT-eligible approval",
            "required_tier": required_tier,
            "approved_tiers": sorted(approved),
            "case_id": case.id,
        }

    # Expired mandatory items for the tier block assignment.
    today = date.today()
    if case.insurance_expiration and case.insurance_expiration < today:
        return {
            "eligible": False,
            "reason": f"Insurance expired on {case.insurance_expiration.isoformat()}",
            "required_tier": required_tier,
            "case_id": case.id,
        }
    vehicles = list(case.vehicles or [])
    if vehicles:
        reviewed = any(
            str(getattr(vehicle, "eligibility_status", None) or "").upper()
            in {"REVIEWED", "ELIGIBLE_NOT_ACTIVE", "ELIGIBLE"}
            or str(vehicle.vehicle_status or "").upper() in {"REVIEWED", "APPROVED", "ACTIVE"}
            for vehicle in vehicles
        )
        if not reviewed:
            return {
                "eligible": False,
                "reason": "Required vehicle review is incomplete",
                "required_tier": required_tier,
                "case_id": case.id,
            }
    base_modules = [
        module
        for module in (case.training_modules or [])
        if module.module_key not in {"sts_service_rules", "behind_wheel_eval"}
    ]
    if base_modules and any(module.status != "completed" for module in base_modules):
        return {
            "eligible": False,
            "reason": "Required training is incomplete",
            "required_tier": required_tier,
            "case_id": case.id,
        }
    for req in case.requirements or []:
        if not req.is_blocking:
            continue
        if req.expiration_date and req.expiration_date < today and req.timing in {
            "required_now",
            "required_before_activation",
        }:
            return {
                "eligible": False,
                "reason": f"Mandatory requirement expired: {req.requirement_key}",
                "required_tier": required_tier,
                "case_id": case.id,
            }

    if vehicles:
        ok_any = False
        reasons = []
        for vehicle in vehicles:
            ok, reason = vehicle_is_assignable(vehicle, required_tier=required_tier)
            if ok:
                ok_any = True
                break
            reasons.append(reason)
        if not ok_any:
            return {
                "eligible": False,
                "reason": "; ".join(reasons) or "No assignable vehicle",
                "required_tier": required_tier,
                "case_id": case.id,
            }

    return {
        "eligible": True,
        "reason": "Driver and vehicle eligibility satisfied",
        "required_tier": required_tier,
        "approved_tiers": sorted(approved),
        "case_id": case.id,
        "workflow_status": case.workflow_status,
    }


def filter_dispatch_candidates(
    db: Session,
    *,
    organization_id: str,
    ride: Any,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter onboarding/STS holds always; apply the full dispatch gate only when enabled."""
    kept: list[dict[str, Any]] = []
    for item in candidates:
        driver = item.get("driver")
        driver_id = str(getattr(driver, "id", None) or item.get("driver_id") or "")
        if not driver_id:
            continue
        hold = driver_blocked_from_live_dispatch(
            db, organization_id=organization_id, driver_id=driver_id, ride=ride
        )
        item = dict(item)
        item["approval_engine_hold"] = hold
        if hold.get("blocked"):
            continue
        if dispatch_gate_enabled():
            result = evaluate_driver_ride_eligibility(
                db, organization_id=organization_id, driver_id=driver_id, ride=ride
            )
            item["approval_engine_eligibility"] = result
            if not result.get("eligible"):
                continue
        kept.append(item)
    return kept
