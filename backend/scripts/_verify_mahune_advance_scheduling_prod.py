"""Verify Mahune Monibah advance scheduling on production without manual assignment."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))

from scripts.production_auth import BASE, dispatcher_headers, org_id

OUTBOUND_RIDE_ID = "a6722aae-4466-4080-9241-a358b143147a"
RETURN_RIDE_ID = "cba6723a-764b-49a2-a5c9-fcb37a78cbfb"
DRIVER_PHONE = os.getenv("MAHUNE_VERIFY_DRIVER_PHONE", "917-555-1004")
EVIDENCE_DIR = REPO / "PRODUCTION_QA_EVIDENCE"


def _get(path: str, headers: dict) -> dict:
    resp = requests.get(f"{BASE}{path}", headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _post(path: str, headers: dict, payload: dict | None = None) -> dict:
    resp = requests.post(f"{BASE}{path}", headers=headers, json=payload or {}, timeout=120)
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:500]}
    if resp.status_code >= 400:
        raise RuntimeError(f"{path} -> {resp.status_code}: {body}")
    return body


def _trigger_maintenance(headers: dict) -> None:
    queue = _get(f"/api/health-isf/dispatcher/queue?organization_id={org_id()}", headers)
    _ = queue


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    headers = dispatcher_headers()

    before_outbound = _get(f"/api/health-isf/rides/{OUTBOUND_RIDE_ID}", headers)
    before_return = _get(f"/api/health-isf/rides/{RETURN_RIDE_ID}", headers)

    _trigger_maintenance(headers)

    after_outbound = _get(f"/api/health-isf/rides/{OUTBOUND_RIDE_ID}", headers)
    after_return = _get(f"/api/health-isf/rides/{RETURN_RIDE_ID}", headers)

    driver_login = _post(
        "/api/health-isf/drivers/mobile-login",
        {},
        {"phone": DRIVER_PHONE},
    )
    driver_id = str(driver_login.get("driver_id") or "")
    driver_headers = {"X-Driver-Session-Token": str(driver_login.get("session_token") or "")}

    active = _get(f"/api/health-isf/drivers/{driver_id}/active-ride", driver_headers)
    upcoming = _get(f"/api/health-isf/drivers/{driver_id}/upcoming-schedule", driver_headers)

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "deploy_base": BASE,
        "org_id": org_id(),
        "outbound_ride_id": OUTBOUND_RIDE_ID,
        "return_ride_id": RETURN_RIDE_ID,
        "driver_phone": DRIVER_PHONE,
        "driver_id": driver_id,
        "before": {
            "outbound": before_outbound,
            "return": before_return,
        },
        "after": {
            "outbound": after_outbound,
            "return": after_return,
        },
        "driver_active_ride": active,
        "driver_upcoming_schedule": upcoming,
        "pass_checks": {
            "outbound_has_driver_after_sweep": bool(after_outbound.get("driver_id")),
            "return_has_driver_after_sweep": bool(after_return.get("driver_id")),
            "driver_no_active_trip": not bool(active.get("has_active_ride")),
            "mahune_visible_in_upcoming": any(
                str(row.get("ride_id")) in {OUTBOUND_RIDE_ID, RETURN_RIDE_ID}
                for row in (upcoming.get("upcoming_schedule") or active.get("upcoming_schedule") or [])
            ),
        },
    }

    out_path = EVIDENCE_DIR / f"MAHUNE_ADVANCE_SCHEDULING_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["pass_checks"], indent=2))
    print(f"EVIDENCE={out_path}")
    ok = all(report["pass_checks"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
