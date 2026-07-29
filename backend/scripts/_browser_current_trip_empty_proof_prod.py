"""Browser proof: Current Trip empty state for drivers 1002/1004 on production."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import production_auth as pa

BASE = pa.BASE
EVIDENCE = REPO / "PRODUCTION_QA_EVIDENCE"
PHONES = ("917-555-1002", "917-555-1004")


def _login(phone: str) -> tuple[str, str]:
    r = requests.post(f"{BASE}/api/health-isf/drivers/mobile-login", json={"phone": phone}, timeout=120)
    r.raise_for_status()
    body = r.json()
    return str(body["driver_id"]), str(body["session_token"])


def main() -> int:
    live = requests.get(f"{BASE}/api/health/live", timeout=60).json()
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    report: dict = {"deploy_commit": live.get("deploy_commit"), "drivers": {}}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for phone in PHONES:
            driver_id, token = _login(phone)
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
            init = f"""
            localStorage.clear(); sessionStorage.clear();
            localStorage.setItem('amicor_platform_role','driver');
            localStorage.setItem('amicor_shell_role','driver');
            localStorage.setItem('amicor_last_mobile_surface','driver');
            localStorage.setItem('amicor_driver_session', JSON.stringify({{
              driver_id:{json.dumps(driver_id)}, session_token:{json.dumps(token)},
              role:'driver', updated_at:new Date().toISOString()
            }}));
            """
            ctx.add_init_script(init)
            page = ctx.new_page()
            page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(18000)
            ui = page.evaluate(
                """() => {
                  const app = (window.AmiOpsShellState && window.AmiOpsShellState.driverApp) || {};
                  const wf = (window.AmiOpsShellState && window.AmiOpsShellState.driverWorkflow) || {};
                  const workflowBtns = Array.from(document.querySelectorAll('[data-driver-action="accept_trip"],[data-driver-action="start_route"],[data-driver-action="complete_trip"]'));
                  return {
                    tripQueue: app.tripQueue || [],
                    activeTripId: app.activeTripId || '',
                    mobileUiState: app.mobileUiState || '',
                    upcomingCount: (wf.upcomingSchedule || []).length,
                    workflowButtonCount: workflowBtns.length,
                    hasNoImmediateCopy: (document.body.innerText || '').includes('no immediate trip'),
                    bodySnippet: (document.querySelector('#page-content')||document.body).innerText.slice(0,1200)
                  };
                }"""
            )
            png = EVIDENCE / f"CURRENT_TRIP_EMPTY_PROOF_{phone.replace('-','')}_{stamp}.png"
            page.screenshot(path=str(png), full_page=True)
            report["drivers"][phone] = {
                "driver_id": driver_id,
                "ui": ui,
                "screenshot": str(png),
                "pass": (
                    ui.get("workflowButtonCount") == 0
                    and not ui.get("activeTripId")
                    and not (ui.get("tripQueue") or [])
                    and ui.get("hasNoImmediateCopy")
                ),
            }
            ctx.close()
        browser.close()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"CURRENT_TRIP_EMPTY_PROOF_{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(out), "results": {p: report["drivers"][p]["pass"] for p in PHONES}}, indent=2))
    return 0 if all(report["drivers"][p]["pass"] for p in PHONES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
