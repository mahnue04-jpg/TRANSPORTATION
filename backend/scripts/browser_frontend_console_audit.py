"""Capture post-login console errors, panel hydration, responsive layout, and static assets."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

BASE = os.getenv("AMICOR_BROWSER_BASE", "https://amicor-health-isf-py.onrender.com")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
OUT = Path(__file__).resolve().parent.parent / "artifacts" / "frontend_console_audit.json"

ADMIN_PANELS = [
    ("dashboard", "#health-dashboard-cards", ["loading dashboard"]),
    ("billing", "#health-billing-kpis", ["loading billing"]),
    ("admin", "#health-admin-summary", ["loading admin"]),
    ("dispatch", "#health-dispatch-worklist", ["loading dispatch worklist"]),
]

RIDER_PANELS = [
    ("customer", "#health-customer-request-history", ["loading"]),
]

STATIC_ASSETS = [
    "/static/modules/health_isf/health-isf.js",
    "/static/ux/sessionManager.js",
]


def sign_in(page, email: str) -> None:
    page.goto(f"{BASE}/#/health-isf/dashboard", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(1200)
    page.wait_for_selector("#health-isf-shell:not([hidden])", timeout=60000)
    if page.evaluate(
        """(expectedEmail) => {
          if (!window.AmiCorSession || typeof window.AmiCorSession.getCurrent !== 'function') return false;
          const id = (window.AmiCorSession.getCurrent() || {}).identity || {};
          return String(id.email || '').toLowerCase() === String(expectedEmail || '').toLowerCase()
            && window.AmiCorSession.isActive && window.AmiCorSession.isActive();
        }""",
        email,
    ):
        page.wait_for_timeout(2500)
        return
    page.locator('[data-health-action="shell-login"]').first.wait_for(state="visible", timeout=30000)
    page.locator('[data-health-action="shell-login"]').first.click(force=True)
    page.locator("#amicor-auth-overlay").wait_for(state="visible", timeout=30000)
    page.locator(".amicor-auth-input").nth(0).fill(email)
    page.locator(".amicor-auth-input").nth(1).fill(PASSWORD)
    page.locator(".amicor-auth-modal form button[type='submit']").click()
    page.locator("#amicor-auth-overlay").wait_for(state="hidden", timeout=90000)
    page.wait_for_timeout(2500)
    page.evaluate(
        """() => window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData
          ? window.AmiCorHealthISF.refreshData() : null"""
    )
    page.wait_for_timeout(3500)


def audit_panels(page, panels: list[tuple[str, str, list[str]]]) -> list[dict]:
    rows: list[dict] = []
    for route, selector, forbidden in panels:
        page.evaluate(
            f"""() => window.AmiCorHealthISF.navigate('{route}', true, {{ source: 'console_audit', force: true }})"""
        )
        page.wait_for_timeout(2500)
        text = page.locator(selector).inner_text(timeout=10000)
        stuck = any(token.lower() in text.lower() for token in forbidden)
        rows.append({
            "route": route,
            "selector": selector,
            "stuck_loading": stuck,
            "snippet": text[:160],
        })
    return rows


def is_ignorable_console_error(message: str) -> bool:
    lowered = message.lower()
    if "401" in lowered and ("unauthorized" in lowered or "failed to load resource" in lowered):
        return True
    if "favicon" in lowered:
        return True
    return False


def check_static_assets() -> list[dict]:
    rows: list[dict] = []
    with httpx.Client(base_url=BASE, timeout=20) as client:
        for path in STATIC_ASSETS:
            res = client.get(path)
            rows.append({
                "path": path,
                "status": res.status_code,
                "ok": res.status_code == 200 and len(res.content) > 0,
            })
    return rows


def main() -> int:
    console_errors: list[str] = []
    page_errors: list[str] = []
    panel_results: list[dict] = []
    responsive_results: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        def run_session(email: str, panels: list[tuple[str, str, list[str]]], viewport: dict) -> None:
            nonlocal console_errors, page_errors, panel_results, responsive_results
            page = browser.new_page(viewport=viewport)
            page.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")

            def on_console(msg):
                if msg.type not in ("error", "warning"):
                    return
                text = msg.text or ""
                if is_ignorable_console_error(text):
                    return
                console_errors.append(f"{msg.type}: {text}")

            def on_page_error(err):
                page_errors.append(str(err))

            page.on("console", on_console)
            page.on("pageerror", on_page_error)
            sign_in(page, email)
            panel_results.extend(audit_panels(page, panels))
            shell = page.locator("#health-isf-shell")
            responsive_results.append({
                "viewport": viewport,
                "email": email,
                "shell_visible": shell.is_visible(),
                "shell_width": shell.evaluate("el => el.getBoundingClientRect().width") if shell.count() else 0,
            })
            page.close()

        run_session("admin@amicor.local", ADMIN_PANELS, {"width": 1440, "height": 960})

        rider_page = browser.new_page(viewport={"width": 1440, "height": 960})
        rider_page.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")
        rider_page.on("console", lambda msg: (
            console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type in ("error", "warning") and not is_ignorable_console_error(msg.text or "")
            else None
        ))
        rider_page.on("pageerror", lambda err: page_errors.append(str(err)))
        sign_in(rider_page, "rider@amicor.local")
        rider_page.goto(f"{BASE}/#/health-isf/rides", wait_until="domcontentloaded")
        rider_page.wait_for_timeout(1500)
        form = rider_page.locator("#health-customer-request-form")
        if form.count():
            form.locator('[name="rider_name"]').fill("Cert Audit Rider")
            form.locator('[name="rider_phone"]').fill("646-555-8800")
            form.locator('[name="pickup_address"]').fill("50 Cert Audit Ave")
            form.locator('[name="dropoff_address"]').fill("75 Clinic Audit Rd")
            form.locator("button[type='submit']").click()
            rider_page.wait_for_timeout(2500)
        panel_results.extend(audit_panels(rider_page, RIDER_PANELS))
        rider_page.close()

        run_session("admin@amicor.local", [("dashboard", "#health-dashboard-cards", ["loading dashboard"])], {"width": 390, "height": 844})

        browser.close()

    assets = check_static_assets()
    report = {
        "console_errors": console_errors,
        "page_errors": page_errors,
        "panels": panel_results,
        "responsive": responsive_results,
        "static_assets": assets,
        "passed": (
            len(console_errors) == 0
            and len(page_errors) == 0
            and not any(p["stuck_loading"] for p in panel_results)
            and all(a["ok"] for a in assets)
            and all(r["shell_visible"] for r in responsive_results)
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
