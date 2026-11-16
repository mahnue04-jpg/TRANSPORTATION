#!/usr/bin/env python3
"""Chromium + API owner journey for staging-release prep (disposable local only).

Labels simulated provider results. Does not perform real Google consent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8775"
OUT = Path(
    sys.argv[2]
    if len(sys.argv) > 2
    else str(Path(__file__).resolve().parents[2] / "docs/nova/growth-agent/screenshots")
)
OUT.mkdir(parents=True, exist_ok=True)
EMAIL = "admin@amicor.local"
PASSWORD = "Amicor123!"


def _next_weekday() -> str:
    day = datetime.now(timezone.utc).date() + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


def main() -> int:
    evidence: dict = {"base": BASE, "steps": [], "labels": ["SIMULATED", "STAGING_PREP"]}
    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        readiness_resp = client.get("/api/health/readiness")
        evidence["readiness_http"] = readiness_resp.status_code
        try:
            evidence["readiness_probe"] = readiness_resp.json()
        except Exception:
            evidence["readiness_probe"] = {"raw": readiness_resp.text[:500]}
        if readiness_resp.status_code != 200:
            raise SystemExit(
                f"/api/health/readiness expected 200 for staging traffic, got {readiness_resp.status_code}: "
                f"{evidence['readiness_probe']}"
            )
        probe = evidence["readiness_probe"]
        if probe.get("traffic_ready") is False:
            raise SystemExit(f"traffic_ready must be true: {probe}")
        evidence["steps"].append(
            {
                "name": "infra_readiness_http_200",
                "ok": True,
                "http_probe": probe.get("http_probe"),
                "overall_status": probe.get("overall_status"),
            }
        )

        login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        evidence["steps"].append({"name": "api_login", "ok": True})

        flags_resp = client.get("/api/nova/growth-agent/flags", headers=headers)
        flags_resp.raise_for_status()
        fl = flags_resp.json().get("flags") or flags_resp.json()
        evidence["flags"] = {
            "REAL_CALENDAR_WRITE": fl.get("REAL_CALENDAR_WRITE"),
            "REAL_EMAIL_SEND": fl.get("REAL_EMAIL_SEND"),
            "REAL_VOICE": fl.get("REAL_VOICE"),
            "GOOGLE_OAUTH_CONFIGURED": fl.get("GOOGLE_OAUTH_CONFIGURED"),
            "GOOGLE_OAUTH_HTTP_ENABLED": fl.get("GOOGLE_OAUTH_HTTP_ENABLED"),
            "VOICE_SIMULATOR": fl.get("VOICE_SIMULATOR"),
        }
        assert fl.get("REAL_CALENDAR_WRITE") is False
        assert fl.get("REAL_EMAIL_SEND") is False
        assert fl.get("REAL_VOICE") is False
        assert fl.get("GOOGLE_OAUTH_HTTP_ENABLED") is False

        demo = client.post("/api/nova/growth-agent/demo/synthetic", headers=headers, json={})
        evidence["demo_synthetic"] = {"status": demo.status_code}
        demo.raise_for_status()
        evidence["steps"].append({"name": "demo_synthetic", "ok": True, "label": "SYNTHETIC DEMO"})

        recv = client.get("/api/nova/growth-agent/receptionist/readiness", headers=headers)
        recv.raise_for_status()
        readiness = recv.json()
        cal = readiness.get("calendar") or {}
        evidence["readiness_snapshot"] = {
            "connected": cal.get("connected"),
            "status": cal.get("status"),
            "configuration": cal.get("configuration"),
            "pilot_live_ready": readiness.get("pilot_live_ready"),
        }
        assert cal.get("connected") is not True
        evidence["steps"].append({"name": "readiness_not_connected", "ok": True})

        day = _next_weekday()
        # Prefer inspect service from synthetic demo
        avail = client.get(
            "/api/nova/growth-agent/availability",
            headers=headers,
            params={"service_code": "inspect", "day": day},
        )
        evidence["availability_status"] = avail.status_code
        avail.raise_for_status()
        payload = avail.json()
        slots = payload.get("slots") or []
        evidence["availability_external"] = payload.get("external_calendar")
        evidence["steps"].append(
            {"name": "availability", "ok": bool(slots), "slot_count": len(slots), "label": "SIMULATED"}
        )
        if not slots:
            raise SystemExit("No availability slots for journey")

        leads = client.get("/api/nova/growth-agent/leads", headers=headers)
        leads.raise_for_status()
        contacts = leads.json().get("leads") or leads.json().get("contacts") or []
        if not contacts:
            raise SystemExit("No synthetic leads for booking")
        contact_id = contacts[0].get("id") or contacts[0].get("contact_id")
        start = slots[0]["starts_at_utc"]

        book = client.post(
            "/api/nova/growth-agent/appointments",
            headers=headers,
            json={
                "contact_id": contact_id,
                "service_code": "inspect",
                "starts_at_utc": start,
                "idempotency_key": f"staging-journey-book-{day}",
                "is_synthetic_demo": True,
            },
        )
        evidence["book"] = {"status": book.status_code, "body": book.text[:500]}
        book.raise_for_status()
        appt = book.json()
        appt_id = appt["id"]
        evidence["steps"].append(
            {
                "name": "book",
                "ok": True,
                "label": "SIMULATED_MOCK_CALENDAR",
                "calendar_sync": appt.get("calendar_sync"),
                "owner_notification": appt.get("owner_notification"),
            }
        )

        if len(slots) > 1:
            resched = client.post(
                f"/api/nova/growth-agent/appointments/{appt_id}/reschedule",
                headers=headers,
                json={
                    "starts_at_utc": slots[1]["starts_at_utc"],
                    "idempotency_key": f"staging-journey-resched-{day}",
                },
            )
            evidence["reschedule"] = {"status": resched.status_code}
            resched.raise_for_status()
            evidence["steps"].append({"name": "reschedule", "ok": True, "label": "SIMULATED"})

        cancel = client.post(
            f"/api/nova/growth-agent/appointments/{appt_id}/cancel",
            headers=headers,
            json={"idempotency_key": f"staging-journey-cancel-{day}"},
        )
        evidence["cancel"] = {"status": cancel.status_code}
        cancel.raise_for_status()
        evidence["steps"].append({"name": "cancel", "ok": True, "label": "SIMULATED"})

        rebook = client.post(
            "/api/nova/growth-agent/appointments",
            headers=headers,
            json={
                "contact_id": contact_id,
                "service_code": "inspect",
                "starts_at_utc": start,
                "idempotency_key": f"staging-journey-rebook-{day}",
                "is_synthetic_demo": True,
            },
        )
        evidence["rebook"] = {"status": rebook.status_code}
        rebook.raise_for_status()
        evidence["steps"].append({"name": "rebook", "ok": True, "label": "SIMULATED"})

        notify = client.post(
            "/api/nova/growth-agent/notifications/tick",
            headers=headers,
            json={},
        )
        evidence["notify_tick"] = {"status": notify.status_code, "body": notify.text[:400]}
        evidence["steps"].append(
            {
                "name": "notify_tick",
                "ok": notify.status_code == 200,
                "note": "provider_accepted is not inbox receipt",
                "label": "SIMULATED_MOCK_EMAIL",
            }
        )

        handoffs = client.get("/api/nova/growth-agent/handoffs", headers=headers)
        evidence["handoffs"] = {"status": handoffs.status_code}
        evidence["steps"].append({"name": "handoffs", "ok": handoffs.status_code == 200})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1600})
        page.goto(f"{BASE}/nova/growth", wait_until="networkidle", timeout=60000)
        page.fill("#login-email", EMAIL)
        page.fill("#login-password", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_function(
            "() => !!localStorage.getItem('amicor_growth_token')",
            timeout=30000,
        )
        page.wait_for_timeout(1500)
        if page.locator("[data-recv-readiness]").count():
            page.locator("[data-recv-readiness]").first.scroll_into_view_if_needed()
            text = page.locator("[data-recv-readiness]").first.inner_text()
            evidence["browser_readiness_excerpt"] = text[:800]
            assert "Not connected" in text or "Missing" in text or "Unverified" in text or "Disconnected" in text
        page.screenshot(path=str(OUT / "receptionist_staging_readiness.png"), full_page=True)
        evidence["steps"].append({"name": "browser_readiness", "ok": True})
        browser.close()

    evidence["passed"] = all(bool(s.get("ok")) for s in evidence["steps"])
    out = OUT / "receptionist_staging_owner_journey.json"
    out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"ok": evidence["passed"], "out": str(out), "steps": len(evidence["steps"])}, indent=2))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
