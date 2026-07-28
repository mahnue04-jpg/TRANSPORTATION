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

from scripts import production_auth as pa

BASE = pa.BASE
OUTBOUND_RIDE_ID = "a6722aae-4466-4080-9241-a358b143147a"
RETURN_RIDE_ID = "cba6723a-764b-49a2-a5c9-fcb37a78cbfb"
CUSTOMER_REQUEST_ID = "257b9f51-a905-4d39-ab48-e1abc557b05f"
DRIVER_PHONE = os.getenv("MAHUNE_VERIFY_DRIVER_PHONE", "917-555-1004")
EVIDENCE_DIR = REPO / "PRODUCTION_QA_EVIDENCE"


def _auth() -> tuple[dict, str]:
    tokens = pa.resolve_production_tokens()
    if not tokens.get("ok"):
        raise RuntimeError(str(tokens.get("error") or "auth failed"))
    headers = {"Authorization": f"Bearer {tokens['dispatcher_token']}"}
    org = os.getenv(
        "AMICOR_ORG_ID",
        "308dc05a-6781-4ef7-91fc-ff22606937e3",
    ).strip()
    session = requests.get(f"{BASE}/api/auth/session", headers=headers, timeout=60)
    if session.ok:
        org = str(session.json().get("organization_id") or org)
    return headers, org


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


def _trigger_maintenance(headers: dict, org_id: str) -> None:
    _get(
        f"/api/health-isf/dispatch/queue?organization_id={org_id}&limit=50&force_maintenance=true",
        headers,
    )


def _run_request_advance_scheduling(headers: dict, request_id: str) -> dict:
    approve = _post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers,
        {},
    )
    _ = approve
    return _post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch",
        headers,
        {"offer_timeout_seconds": 120},
    )


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    headers, org_id = _auth()

    before_outbound = _get(f"/api/health-isf/rides/{OUTBOUND_RIDE_ID}", headers)
    before_return = _get(f"/api/health-isf/rides/{RETURN_RIDE_ID}", headers)

    _trigger_maintenance(headers, org_id)
    try:
        auto_dispatch_result = _run_request_advance_scheduling(headers, CUSTOMER_REQUEST_ID)
    except RuntimeError as exc:
        auto_dispatch_result = {"error": str(exc)}

    after_outbound = _get(f"/api/health-isf/rides/{OUTBOUND_RIDE_ID}", headers)
    after_return = _get(f"/api/health-isf/rides/{RETURN_RIDE_ID}", headers)

    driver_login = _post(
        "/api/health-isf/drivers/mobile-login",
        {},
        {"phone": DRIVER_PHONE},
    )
    driver_id = str(driver_login.get("driver_id") or "")
    driver_headers = {"X-Driver-Session-Token": str(driver_login.get("session_token") or "")}

    for ride_id in (OUTBOUND_RIDE_ID, RETURN_RIDE_ID):
        ride = after_outbound if ride_id == OUTBOUND_RIDE_ID else after_return
        if str(ride.get("driver_id") or "") == driver_id:
            try:
                _post(
                    f"/api/health-isf/drivers/{driver_id}/accept-scheduled-ride",
                    driver_headers,
                    {"ride_id": ride_id},
                )
            except RuntimeError:
                pass

    active = _get(f"/api/health-isf/drivers/{driver_id}/active-ride", driver_headers)
    upcoming = _get(f"/api/health-isf/drivers/{driver_id}/upcoming-schedule", driver_headers)

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "deploy_base": BASE,
        "org_id": org_id,
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
        "auto_dispatch_result": auto_dispatch_result,
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
