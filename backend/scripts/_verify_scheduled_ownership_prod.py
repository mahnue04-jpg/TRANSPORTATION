"""Production browser + API proof for scheduled ride ownership isolation."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa

BASE = pa.BASE
EVIDENCE = BACKEND.parent / "PRODUCTION_QA_EVIDENCE"
MAHUNE_OUTBOUND = "a6722aae-4466-4080-9241-a358b143147a"
MAHUNE_RETURN = "cba6723a-764b-49a2-a5c9-fcb37a78cbfb"
OWNER_1002 = "0c94f59d-a766-4f93-ab41-e7f9cc6d519c"
PHONES = (
    ("917-555-1002", OWNER_1002),
    ("917-555-1004", "06d221a2-8fe0-41e5-80d3-86973133d7ac"),
    ("917-555-1005", "22e24a60-270a-40c3-b36d-b852b363551b"),
)


def _login_api(phone: str) -> dict:
    resp = requests.post(f"{BASE}/api/health-isf/drivers/mobile-login", json={"phone": phone}, timeout=120)
    body = resp.json() if resp.content else {}
    if not resp.ok:
        return {"phone": phone, "ok": False, "status": resp.status_code, "body": body}
    driver_id = str(body.get("driver_id") or "")
    token = str(body.get("session_token") or "")
    headers = {"X-Driver-Session-Token": token}
    active = requests.get(f"{BASE}/api/health-isf/drivers/{driver_id}/active-ride", headers=headers, timeout=120).json()
    upcoming = requests.get(
        f"{BASE}/api/health-isf/drivers/{driver_id}/upcoming-schedule",
        headers=headers,
        timeout=120,
    ).json()
    mahune = [
        row
        for row in (upcoming.get("upcoming_schedule") or [])
        if str(row.get("ride_id")) in {MAHUNE_OUTBOUND, MAHUNE_RETURN}
        and str(row.get("assignment_state") or "") == "scheduled_accepted"
    ]
    return {
        "phone": phone,
        "ok": True,
        "driver_id": driver_id,
        "has_active_ride": active.get("has_active_ride"),
        "mahune_reserved_count": len(mahune),
        "mahune_rows": mahune,
        "upcoming_total": len(upcoming.get("upcoming_schedule") or []),
        "session_token": token,
        "session_id": body.get("session_id"),
        "driver_name": body.get("driver_name"),
    }


def _browser_proof(phone: str, expected_driver_id: str, session: dict, stamp: str) -> dict:
    init = f"""
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('amicor_platform_role', 'driver');
    localStorage.setItem('amicor_shell_role', 'driver');
    localStorage.setItem('amicor_last_mobile_surface', 'driver');
    localStorage.setItem('amicor_driver_session', JSON.stringify({{
      driver_id: {json.dumps(expected_driver_id)},
      driver_name: {json.dumps(session.get('driver_name') or 'Driver')},
      role: 'driver',
      session_token: {json.dumps(session.get('session_token') or '')},
      session_id: {json.dumps(session.get('session_id') or '')},
      organization_id: {json.dumps('308dc05a-6781-4ef7-91fc-ff22606937e3')},
      updated_at: new Date().toISOString()
    }}));
    """
    png = EVIDENCE / f"SCHEDULED_OWNERSHIP_BROWSER_{phone.replace('-', '')}_{stamp}.png"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        context.add_init_script(init)
        page = context.new_page()
        page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(18000)
        content = page.locator("#page-content").inner_text(timeout=15000)
        page.screenshot(path=str(png), full_page=True)
        browser.close()
    return {
        "phone": phone,
        "driver_id": expected_driver_id,
        "browser_shows_mahune": "mahune" in content.lower(),
        "browser_shows_reserved": "reserved" in content.lower(),
        "screenshot": str(png),
        "content_preview": content[:1200],
    }


def main() -> int:
    tokens = pa.resolve_production_tokens()
    headers = {"Authorization": f"Bearer {tokens['dispatcher_token']}"}
    requests.get(
        f"{BASE}/api/health-isf/dispatch/queue?organization_id=308dc05a-6781-4ef7-91fc-ff22606937e3&limit=5&force_maintenance=true",
        headers=headers,
        timeout=120,
    )

    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    api_sessions = [_login_api(phone) for phone, _ in PHONES]

    owner = next(s for s in api_sessions if s.get("phone") == "917-555-1002")
    other_sessions = [s for s in api_sessions if s.get("phone") != "917-555-1002"]

    cross_accept = None
    if owner.get("ok") and other_sessions and other_sessions[0].get("ok"):
        other = other_sessions[0]
        cross = requests.post(
            f"{BASE}/api/health-isf/drivers/{other['driver_id']}/accept-scheduled-ride",
            headers={"X-Driver-Session-Token": other["session_token"]},
            json={"ride_id": MAHUNE_OUTBOUND},
            timeout=120,
        )
        cross_accept = {"status": cross.status_code, "body": cross.json() if cross.content else cross.text[:200]}

    browser_proofs = []
    for phone, expected_id in PHONES:
        session = next(s for s in api_sessions if s.get("phone") == phone)
        if session.get("ok"):
            browser_proofs.append(_browser_proof(phone, expected_id, session, stamp))

    report = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mahune_outbound": MAHUNE_OUTBOUND,
        "mahune_return": MAHUNE_RETURN,
        "owner_driver_id": OWNER_1002,
        "api_sessions": api_sessions,
        "cross_driver_accept_attempt": cross_accept,
        "browser_proofs": browser_proofs,
        "pass_checks": {
            "owner_sees_mahune_reserved": (owner.get("mahune_reserved_count") or 0) >= 2,
            "others_do_not_see_mahune_reserved": all(
                (s.get("mahune_reserved_count") or 0) == 0 for s in other_sessions if s.get("ok")
            ),
            "cross_accept_blocked": bool(cross_accept and cross_accept.get("status") in {400, 403, 404}),
            "owner_browser_shows_mahune": any(
                p.get("phone") == "917-555-1002" and p.get("browser_shows_mahune") for p in browser_proofs
            ),
            "other_browsers_hide_mahune": all(
                p.get("browser_shows_mahune") is False for p in browser_proofs if p.get("phone") != "917-555-1002"
            ),
        },
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"SCHEDULED_OWNERSHIP_PROOF_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["pass_checks"], indent=2))
    print(f"EVIDENCE={out}")
    return 0 if all(report["pass_checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
