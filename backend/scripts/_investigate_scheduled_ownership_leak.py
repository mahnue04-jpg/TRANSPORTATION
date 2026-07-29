"""Investigate scheduled ride ownership leak across driver mobile sessions."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa

BASE = pa.BASE
ORG = "308dc05a-6781-4ef7-91fc-ff22606937e3"
MAHUNE_OUTBOUND = "a6722aae-4466-4080-9241-a358b143147a"
MAHUNE_RETURN = "cba6723a-764b-49a2-a5c9-fcb37a78cbfb"
PHONES = ("917-555-1002", "917-555-1004", "917-555-1005")
EVIDENCE = BACKEND.parent / "PRODUCTION_QA_EVIDENCE"


def _login(phone: str) -> dict:
    resp = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": phone},
        timeout=120,
    )
    body = resp.json() if resp.content else {}
    if not resp.ok:
        return {"phone": phone, "ok": False, "status": resp.status_code, "body": body}
    driver_id = str(body.get("driver_id") or "")
    token = str(body.get("session_token") or "")
    headers = {"X-Driver-Session-Token": token}
    active = requests.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/active-ride",
        headers=headers,
        timeout=120,
    ).json()
    upcoming = requests.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/upcoming-schedule",
        headers=headers,
        timeout=120,
    ).json()
    assigned = requests.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/assigned-rides?limit=15",
        headers=headers,
        timeout=120,
    )
    assigned_body = assigned.json() if assigned.ok else {"error": assigned.text[:300]}
    offer = requests.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/active-offer",
        headers=headers,
        timeout=120,
    ).json()
    mahune_in_upcoming = [
        row
        for row in (upcoming.get("upcoming_schedule") or [])
        if str(row.get("ride_id")) in {MAHUNE_OUTBOUND, MAHUNE_RETURN}
    ]
    mahune_in_active = [
        row
        for row in (active.get("upcoming_schedule") or [])
        if str(row.get("ride_id")) in {MAHUNE_OUTBOUND, MAHUNE_RETURN}
    ]
    return {
        "phone": phone,
        "ok": True,
        "driver_id": driver_id,
        "driver_name": body.get("driver_name"),
        "organization_id": body.get("organization_id"),
        "session_id": body.get("session_id"),
        "session_token_prefix": token[:12] + "…" if token else "",
        "has_active_ride": active.get("has_active_ride"),
        "mahune_upcoming_count": len(mahune_in_upcoming),
        "mahune_active_ride_schedule_count": len(mahune_in_active),
        "mahune_rows": mahune_in_upcoming or mahune_in_active,
        "upcoming_total": len(upcoming.get("upcoming_schedule") or []),
        "upcoming_schedule": upcoming.get("upcoming_schedule") or [],
        "active_ride_upcoming": active.get("upcoming_schedule") or [],
        "assigned_ride_ids": [
            str(r.get("id") or r.get("ride_id") or "")
            for r in (assigned_body if isinstance(assigned_body, list) else [])
        ],
        "active_offer": offer.get("offer"),
    }


def main() -> int:
    tokens = pa.resolve_production_tokens()
    headers = {"Authorization": f"Bearer {tokens['dispatcher_token']}"}
    drivers = requests.get(
        f"{BASE}/api/health-isf/drivers?organization_id={ORG}",
        headers=headers,
        timeout=120,
    ).json()
    maria_rows = [d for d in drivers if "maria" in str(d.get("name") or "").lower()]
    outbound = requests.get(
        f"{BASE}/api/health-isf/rides/{MAHUNE_OUTBOUND}",
        headers=headers,
        timeout=120,
    ).json()
    return_ride = requests.get(
        f"{BASE}/api/health-isf/rides/{MAHUNE_RETURN}",
        headers=headers,
        timeout=120,
    ).json()

    sessions = [_login(phone) for phone in PHONES]
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    report = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mahune_outbound": {
            "ride_id": MAHUNE_OUTBOUND,
            "driver_id": outbound.get("driver_id"),
            "driver_name": outbound.get("driver_name"),
        },
        "mahune_return": {
            "ride_id": MAHUNE_RETURN,
            "driver_id": return_ride.get("driver_id"),
            "driver_name": return_ride.get("driver_name"),
        },
        "maria_garcia_driver_records": maria_rows,
        "driver_sessions": sessions,
        "leak_detected": any(
            s.get("ok")
            and s.get("driver_id") != str(outbound.get("driver_id") or "")
            and (s.get("mahune_upcoming_count") or s.get("mahune_active_ride_schedule_count"))
            for s in sessions
        ),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"SCHEDULED_OWNERSHIP_LEAK_INVESTIGATION_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(
        {
            "leak_detected": report["leak_detected"],
            "assigned_driver_id": outbound.get("driver_id"),
            "sessions": [
                {
                    "phone": s.get("phone"),
                    "driver_id": s.get("driver_id"),
                    "mahune_visible": (s.get("mahune_upcoming_count") or 0) + (s.get("mahune_active_ride_schedule_count") or 0),
                    "upcoming_total": s.get("upcoming_total"),
                }
                for s in sessions
            ],
            "evidence": str(out),
        },
        indent=2,
    ))
    return 1 if report["leak_detected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
