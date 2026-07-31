"""Production proof: immediate offer auto-reassign after expiry (requires deployed fix)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_auth import BASE, resolve_production_tokens  # noqa: E402

ORG = "308dc05a-6781-4ef7-91fc-ff22606937e3"
DRIVER_PHONES = ["917-555-1006", "917-555-1001", "917-555-1002", "917-555-1005"]
OFFER_TIMEOUT_SECONDS = 45
POLL_SECONDS = 10
MAX_WAIT_SECONDS = 120


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _driver_active_offer(phone: str) -> dict:
    login = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": phone},
        timeout=90,
    )
    if not login.ok:
        return {"phone": phone, "error": login.status_code}
    body = login.json()
    did = body["driver_id"]
    tok = body["session_token"]
    resp = requests.get(
        f"{BASE}/api/health-isf/drivers/{did}/active-offer",
        headers={"X-Driver-Session-Token": tok},
        params={"organization_id": ORG},
        timeout=90,
    )
    offer = (resp.json() if resp.ok else {}).get("offer") or {}
    return {
        "phone": phone,
        "driver_id": did,
        "ride_id": offer.get("ride_id"),
        "assignment_state": offer.get("assignment_state"),
    }


def _assignment_for_ride(token: str, ride_id: str) -> dict | None:
    resp = requests.get(
        f"{BASE}/api/health-isf/dispatch/active-assignments",
        headers=_headers(token),
        params={"organization_id": ORG, "limit": 300},
        timeout=90,
    )
    if not resp.ok:
        return None
    for row in resp.json():
        if str(row.get("ride_id")) == ride_id:
            return row
    return None


def main() -> int:
    tokens = resolve_production_tokens()
    token = tokens["dispatcher_token"]
    report: dict = {
        "base": BASE,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "offer_timeout_seconds": OFFER_TIMEOUT_SECONDS,
    }

    suffix = str(int(time.time()))[-6:]
    create = requests.post(
        f"{BASE}/api/health-isf/customer-requests",
        headers=_headers(tokens["rider_token"]),
        json={
            "rider_name": f"Auto Reassign Prod {suffix}",
            "rider_phone": f"646-555-{suffix}",
            "pickup_address": "10 Auto Reassign Ave, Minneapolis, MN",
            "dropoff_address": "20 Auto Reassign Clinic, Minneapolis, MN",
            "ride_type": "healthcare",
            "recurring": False,
        },
        timeout=120,
    )
    report["create_status"] = create.status_code
    if not create.ok:
        report["create_error"] = create.text[:500]
        print(json.dumps(report, indent=2))
        return 1

    request_id = create.json()["id"]
    ride_id = create.json()["ride_id"]
    report["ride_id"] = ride_id

    approve = requests.post(
        f"{BASE}/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=_headers(token),
        timeout=120,
    )
    report["approve_status"] = approve.status_code

    auto = requests.post(
        f"{BASE}/api/health-isf/dispatch/auto-assign",
        headers=_headers(token),
        json={"ride_id": ride_id, "offer_timeout_seconds": OFFER_TIMEOUT_SECONDS},
        timeout=120,
    )
    report["auto_assign_status"] = auto.status_code
    if auto.ok:
        body = auto.json()
        report["first_driver_id"] = body.get("selected_driver_id") or body.get("driver_id")
        report["first_offer_id"] = body.get("offer_id")

    first_assignment = _assignment_for_ride(token, ride_id)
    report["first_assignment"] = first_assignment
    first_driver = str((first_assignment or {}).get("driver_id") or report.get("first_driver_id") or "")

    expires_raw = (first_assignment or {}).get("offer_expires_at")
    report["offer_expires_at"] = expires_raw
    if expires_raw:
        expires_ts = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00")).timestamp()
        wait_until = expires_ts + 5
    else:
        wait_until = time.time() + OFFER_TIMEOUT_SECONDS + 5

    report["wait_until_utc"] = datetime.fromtimestamp(wait_until, timezone.utc).isoformat()

    while time.time() < wait_until:
        time.sleep(min(POLL_SECONDS, max(1, wait_until - time.time())))

    # Trigger expire + auto-reassign via active-assignments read path
    trigger = requests.get(
        f"{BASE}/api/health-isf/dispatch/active-assignments",
        headers=_headers(token),
        params={"organization_id": ORG, "limit": 300},
        timeout=120,
    )
    report["trigger_status"] = trigger.status_code

    second_assignment = _assignment_for_ride(token, ride_id)
    report["second_assignment"] = second_assignment
    second_driver = str((second_assignment or {}).get("driver_id") or "")
    report["second_driver_id"] = second_driver or None

    report["driver_offers"] = [_driver_active_offer(phone) for phone in DRIVER_PHONES]
    report["reassigned"] = bool(
        first_driver
        and second_driver
        and first_driver != second_driver
        and str((second_assignment or {}).get("assignment_state") or "").lower() == "offered"
    )

    out = Path(__file__).resolve().parents[2] / "PRODUCTION_QA_EVIDENCE" / f"IMMEDIATE_OFFER_AUTO_REASSIGN_{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print("WROTE", out)
    return 0 if report["reassigned"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
