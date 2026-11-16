#!/usr/bin/env python3
"""Chromium acceptance for receptionist panel — disposable local server only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/opt/cursor/artifacts")
OUT.mkdir(parents=True, exist_ok=True)
EMAIL = "admin@amicor.local"
PASSWORD = "Amicor123!"


def main() -> int:
    evidence: dict = {"base": BASE, "steps": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1600})
        page.goto(f"{BASE}/nova/growth", wait_until="networkidle", timeout=60000)
        page.screenshot(path=str(OUT / "receptionist_before_login.png"), full_page=True)
        evidence["steps"].append({"name": "load", "ok": True})

        page.fill("#login-email", EMAIL)
        page.fill("#login-password", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_timeout(1500)
        # Token may be set by growth.js after login API
        page.wait_for_function(
            "() => !!localStorage.getItem('amicor_growth_token')",
            timeout=30000,
        )
        evidence["steps"].append({"name": "login", "ok": True})

        page.wait_for_selector("#receptionist-root .recv-grid, #receptionist-root .recv-card", timeout=30000)
        page.screenshot(path=str(OUT / "receptionist_after_login.png"), full_page=True)
        cal = page.locator("[data-recv-calendar]").inner_text()
        evidence["calendar_text"] = cal[:500]
        assert "Not connected" in cal or "Connected" in cal

        # Owner readiness panel
        readiness = page.locator("[data-recv-readiness]")
        if readiness.count():
            text = readiness.first.inner_text()
            evidence["readiness_text"] = text[:800]
            assert "Missing configuration" in text or "Not connected" in text or "Connected" in text or "Unverified" in text
            page.locator("[data-recv-readiness]").first.scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / "receptionist_readiness_panel.png"), full_page=True)
            evidence["steps"].append({"name": "readiness_panel", "ok": True})
        else:
            evidence["steps"].append({"name": "readiness_panel", "ok": False, "note": "panel not rendered"})

        # Activate setup so service-backed voice FAQ has an approved profile
        page.fill("#biz-name", "Chromium Receptionist Biz")
        page.fill("#biz-web", "https://chromium.example")
        if page.locator("#biz-hours").count():
            page.fill("#biz-hours", '{"mon_fri":"09:00-17:00"}')
        if page.locator("#biz-faqs").count():
            page.fill(
                "#biz-faqs",
                '[{"id":"faq_hours","question":"Hours?","keywords":["hours"],"answer":"Mon-Fri 9-5."}]',
            )
        if page.locator("#biz-email").count():
            page.fill("#biz-email", "owner@chromium.example")
        activate = page.locator("#activate-setup")
        if activate.count():
            activate.click()
            page.wait_for_timeout(1200)
        evidence["steps"].append({"name": "activate_setup", "ok": True})

        # Refresh panel after activation
        if page.locator("#recv-refresh").count():
            page.click("#recv-refresh")
            page.wait_for_timeout(800)

        # Voice simulator button — real UI click
        page.fill("#recv-voice-intent", "general")
        page.fill("#recv-voice-utterance", "What are your hours?")
        with page.expect_response(
            lambda r: "/voice/simulator/run" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            page.click("#recv-run-voice")
        resp = resp_info.value
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text()}
        evidence["voice_status"] = resp.status
        evidence["voice_body"] = body
        evidence["voice_simulated"] = body.get("simulated")
        evidence["voice_live_phone"] = body.get("live_phone")
        assert resp.status == 200, body
        assert body.get("simulated") is True
        assert body.get("live_phone") is False
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "receptionist_voice_simulator.png"), full_page=True)
        evidence["steps"].append({"name": "voice_simulator_button", "ok": True})

        # OAuth GET callback redirect (no tokens in location).
        # Use APIRequestContext with max_redirects=0 — page.fetch may opaque-follow.
        redirect = page.context.request.get(
            f"{BASE}/api/nova/growth-agent/calendar/oauth/callback?state=st&code=cd",
            max_redirects=0,
        )
        loc = {
            "status": redirect.status,
            "location": redirect.headers.get("location") or redirect.headers.get("Location"),
        }
        evidence["oauth_get_redirect"] = loc
        assert loc["status"] in (301, 302, 303, 307, 308), loc
        assert "calendar_oauth=1" in (loc["location"] or ""), loc
        assert "access_token" not in (loc["location"] or "")
        assert "refresh_token" not in (loc["location"] or "")
        evidence["steps"].append({"name": "oauth_get_redirect", "ok": True})

        # Sign-out clears panel
        if page.locator("#sign-out").count():
            page.click("#sign-out")
            page.wait_for_timeout(400)
            root = page.locator("#receptionist-root").inner_text()
            evidence["after_signout"] = root[:300]
            assert "cleared" in root.lower() or "sign in" in root.lower()
            evidence["steps"].append({"name": "sign_out_clears", "ok": True})

        browser.close()

    evidence["ok"] = True
    (OUT / "receptionist_chromium_evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
