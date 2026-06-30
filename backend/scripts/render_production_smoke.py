"""Production smoke test for Render deployment."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

import browser_ride_lifecycle_demo as lifecycle  # noqa: E402

BASE = os.getenv("AMICOR_BROWSER_BASE", "https://amicor-health-isf-py.onrender.com")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
OUT = Path(__file__).resolve().parent.parent / "artifacts" / "render_production_smoke_report.json"
SHOT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "render_production_smoke"

TABS = [
    ("dashboard", "#health-dashboard-cards", ["loading dashboard"]),
    ("rides", "#health-dispatch-board", ["loading dispatch board"]),
    ("dispatch", "#health-dispatch-worklist", ["loading dispatch worklist"]),
    ("drivers", "#health-drivers-cards", ["loading drivers"]),
    ("providers", "#health-providers-cards", ["loading providers"]),
    ("customer", "#health-customer-request-history", ["loading customer"]),
    ("analytics", "#health-analytics-operational-feed", ["waiting for analytics"]),
    ("billing", "#health-billing-kpis", ["loading billing"]),
    ("grant", "#health-grant-metrics", ["loading grant"]),
    ("admin", "#health-admin-summary", ["loading admin"]),
]

FEED_SELECTORS = [
    ("operational_feed", "#health-dashboard-operational-feed"),
    ("operational_alerts", "#health-ai-alerts"),
    ("dispatch_intel", "#health-dispatch-intel-queue"),
]


def sign_in(page, email: str, route: str = "dashboard") -> None:
    page.goto(f"{BASE}/#/health-isf/{route}", wait_until="domcontentloaded", timeout=120000)
    lifecycle.dismiss_blocking_overlays(page)
    page.wait_for_timeout(1500)
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
        lifecycle.wait_authenticated(page)
        wait_refresh(page)
        return
    page.locator('[data-health-action="shell-login"]').first.wait_for(state="visible", timeout=30000)
    page.locator('[data-health-action="shell-login"]').first.click(force=True)
    page.locator("#amicor-auth-overlay").wait_for(state="visible", timeout=30000)
    page.locator(".amicor-auth-input").nth(0).fill(email)
    page.locator(".amicor-auth-input").nth(1).fill(PASSWORD)
    page.locator(".amicor-auth-modal form button[type='submit']").click()
    page.locator("#amicor-auth-overlay").wait_for(state="hidden", timeout=90000)
    lifecycle.wait_authenticated(page)
    wait_refresh(page)


def wait_refresh(page) -> None:
    page.evaluate(
        """() => window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData
          && window.AmiCorHealthISF.refreshData()"""
    )
    page.wait_for_timeout(6000)


def is_localhost_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost"}


def main() -> int:
    report: dict = {
        "production_url": BASE,
        "environment_audit": {},
        "api": {},
        "app_shell": {},
        "auth": {},
        "tabs": [],
        "feeds": [],
        "screenshots": [],
        "console_errors": [],
        "network_errors": [],
        "verdict": "NO-GO",
    }

    try:
        health = httpx.get(f"{BASE}/api/health", timeout=90)
        report["api"]["health"] = {"status": health.status_code, "pass": health.status_code == 200}
    except Exception as exc:
        report["api"]["health"] = {"pass": False, "error": str(exc)}

    try:
        readiness = httpx.get(f"{BASE}/api/health/readiness", timeout=90)
        body = readiness.json()
        report["api"]["readiness"] = {
            "status": readiness.status_code,
            "overall_status": body.get("overall_status"),
            "pass": readiness.status_code == 200 and body.get("overall_status") == "ready",
            "blocked_reasons": body.get("blocked_reasons") or [],
            "environment": body.get("environment"),
            "production_environment": body.get("production_environment"),
            "config_checks": body.get("config_checks"),
        }
        report["environment_audit"] = {
            "readiness_ready": body.get("overall_status") == "ready",
            "required_env_passed": (body.get("environment") or {}).get("passed", []),
            "production_env_passed": (body.get("production_environment") or {}).get("passed", []),
            "warnings": (body.get("environment") or {}).get("warnings", []),
            "config_checks": body.get("config_checks") or {},
        }
    except Exception as exc:
        report["api"]["readiness"] = {"pass": False, "error": str(exc)}

    try:
        topology = httpx.get(f"{BASE}/api/runtime/topology", timeout=90).json()
        backend_host = urlparse(topology.get("backend_url", "")).hostname or ""
        report["environment_audit"]["topology"] = topology
        report["environment_audit"]["topology_localhost_leak"] = backend_host in {"127.0.0.1", "localhost"}
    except Exception as exc:
        report["environment_audit"]["topology_error"] = str(exc)

    try:
        login = httpx.post(
            f"{BASE}/api/auth/login",
            json={"email": "dispatcher@amicor.local", "password": PASSWORD},
            timeout=90,
        )
        report["auth"]["dispatcher_api"] = {"status": login.status_code, "pass": login.status_code == 200}
        token = login.json().get("access_token") if login.status_code == 200 else ""
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            probes = [
                "/api/health-isf/dashboard",
                "/api/health-isf/rides",
                "/api/health-isf/drivers",
                "/api/health-isf/providers",
                "/api/health-isf/dispatch/queue",
                "/api/health-isf/activity-feed",
            ]
            report["auth"]["dispatcher_apis"] = []
            for path in probes:
                res = httpx.get(BASE + path, headers=headers, timeout=90)
                report["auth"]["dispatcher_apis"].append({
                    "path": path,
                    "status": res.status_code,
                    "pass": res.status_code == 200,
                })
    except Exception as exc:
        report["auth"]["dispatcher_api"] = {"pass": False, "error": str(exc)}

    try:
        app = httpx.get(f"{BASE}/", timeout=90)
        report["app_shell"] = {
            "status": app.status_code,
            "pass": app.status_code == 200 and len(app.text) > 1000,
            "localhost_in_html": "127.0.0.1:8010" in app.text,
        }
    except Exception as exc:
        report["app_shell"] = {"pass": False, "error": str(exc)}

    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")

        console_errors: list[str] = []
        network_errors: list[dict] = []

        def on_console(msg) -> None:
            if msg.type not in ("error", "warning"):
                return
            text = msg.text or ""
            lowered = text.lower()
            if "favicon" in lowered:
                return
            if any(token in text for token in ("401", "403", "500")) or "forbidden" in lowered:
                console_errors.append(text)

        def on_response(resp) -> None:
            if is_localhost_url(resp.url):
                network_errors.append({"url": resp.url, "status": resp.status, "note": "localhost_leak"})
                return
            if resp.status >= 500:
                network_errors.append({"url": resp.url, "status": resp.status})
            elif resp.status in (401, 403) and "/api/" in resp.url and "auth/login" not in resp.url:
                network_errors.append({"url": resp.url, "status": resp.status})

        try:
            sign_in(page, "admin@amicor.local")
            page.on("console", on_console)
            page.on("response", on_response)
            report["auth"]["admin_browser"] = {"pass": True}

            for route, selector, forbidden in TABS:
                page.evaluate(
                    f"() => window.AmiCorHealthISF.navigate('{route}', true, "
                    f"{{ source: 'render_smoke', force: true }})"
                )
                page.wait_for_timeout(5000)
                loc = page.locator(selector)
                if loc.count() == 0:
                    report["tabs"].append({"route": route, "pass": False, "issue": f"missing {selector}"})
                    continue
                text = loc.inner_text(timeout=20000)
                stuck = any(token.lower() in text.lower() for token in forbidden)
                shot = str(SHOT_DIR / f"tab_{route}.png")
                page.screenshot(path=shot, full_page=False)
                report["screenshots"].append(shot)
                report["tabs"].append({
                    "route": route,
                    "pass": not stuck and len(text.strip()) > 15,
                    "stuck_loading": stuck,
                    "snippet": text[:140],
                })

            page.evaluate(
                "() => window.AmiCorHealthISF.navigate('dashboard', true, "
                "{ source: 'render_smoke', force: true })"
            )
            page.wait_for_timeout(4000)
            for label, selector in FEED_SELECTORS:
                loc = page.locator(selector)
                if loc.count() == 0:
                    report["feeds"].append({"label": label, "pass": False, "issue": "selector missing"})
                    continue
                text = loc.inner_text(timeout=15000)
                waiting_tokens = ("loading", "waiting for", "initializing")
                hydrated = len(text.strip()) > 10 and not any(t in text.lower() for t in waiting_tokens)
                report["feeds"].append({"label": label, "pass": hydrated, "snippet": text[:140]})

            sign_in(page, "dispatcher@amicor.local")
            report["auth"]["dispatcher_browser"] = {"pass": True}
        except Exception as exc:
            report["auth"]["browser_error"] = str(exc)
        finally:
            browser.close()

    report["console_errors"] = list(dict.fromkeys(console_errors))[:30]
    report["network_errors"] = network_errors[:40]
    localhost_leaks = [item for item in network_errors if item.get("note") == "localhost_leak"]
    blocking_network = [
        item for item in network_errors
        if item.get("status") in (401, 403, 500) and item.get("note") != "localhost_leak"
    ]
    report["blocking_console"] = report["console_errors"]
    report["blocking_network"] = blocking_network
    report["localhost_leaks"] = localhost_leaks

    topology_ok = not report.get("environment_audit", {}).get("topology_localhost_leak", True)
    apis_ok = all(
        row.get("pass")
        for row in report.get("auth", {}).get("dispatcher_apis", [])
    ) if report.get("auth", {}).get("dispatcher_apis") else True

    checks = [
        report["api"].get("health", {}).get("pass"),
        report["api"].get("readiness", {}).get("pass"),
        topology_ok,
        report["app_shell"].get("pass"),
        report["auth"].get("dispatcher_api", {}).get("pass"),
        report["auth"].get("admin_browser", {}).get("pass"),
        report["auth"].get("dispatcher_browser", {}).get("pass"),
        apis_ok,
        all(item.get("pass") for item in report["tabs"]),
        all(item.get("pass") for item in report["feeds"]),
        len(blocking_network) == 0,
        len(report["blocking_console"]) == 0,
        len(localhost_leaks) == 0,
    ]
    report["checks_passed"] = sum(1 for item in checks if item)
    report["checks_total"] = len(checks)
    report["verdict"] = "GO" if all(checks) else "NO-GO"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
