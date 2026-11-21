"""Pure, default-deny Work & Revenue scheduled-run configuration check.

No SQLAlchemy, network or credentials are accessed by this module.
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
FORBIDDEN_DATABASES = {"amicor-prod", "amicor-casting-staging-db"}


def inspect_configuration(config: Mapping[str, str], *, at: datetime | None = None) -> dict:
    labels = [
        str(config.get(key) or "").strip().lower()
        for key in ("APP_ENV", "AMICOR_ENVIRONMENT", "ENVIRONMENT")
        if str(config.get(key) or "").strip()
    ]
    expected_db = str(config.get("NOVA_WORK_AUTOPILOT_APPROVED_DATABASE") or "").strip()
    org = str(config.get("NOVA_WORK_AUTOPILOT_OWNER_ORG_ID") or "").strip()
    owner = str(config.get("NOVA_WORK_AUTOPILOT_OWNER_USER_ID") or "").strip()
    staging = bool(labels) and all(label == "staging" for label in labels)
    enabled = str(config.get("NOVA_WORK_AUTOPILOT_STAGING_ENABLED") or "").lower() == "true"
    identity_ok = bool(org and owner and org.lower() != "global" and owner.lower() != "global")
    db_ok = bool(expected_db and expected_db.lower() not in FORBIDDEN_DATABASES)
    local_time = (at or datetime.now(TZ)).astimezone(TZ)
    hour_ok = local_time.hour == 5
    blockers = []
    for code, ok in (
        ("not_isolated_staging", staging),
        ("staging_autopilot_not_enabled", enabled),
        ("owner_identity_not_approved", identity_ok),
        ("database_identity_not_approved", db_ok),
        ("outside_owner_5am_central_window", hour_ok),
    ):
        if not ok:
            blockers.append(code)
    return {
        "status": "READY_TO_ATTEMPT_STAGING_CYCLE" if not blockers else "BLOCKED",
        "blockers": blockers,
        "production_release_authorized": False,
        "external_submission_allowed": False,
        "customer_contact_allowed": False,
        "paid_processing_allowed": False,
        "owner_approval_required": True,
        "local_period": local_time.date().isoformat(),
    }
