"""App-level browser E2E checks for Health ISF surfaces on live preview."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8010")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
ARTIFACT_ROOT = Path(__file__).resolve().parent.parent / "artifacts" / "app_surfaces_e2e"
PROOF_PRIOR = Path(__file__).resolve().parent.parent / "artifacts" / "browser_e2e_ride_lifecycle.json"
REPORT_JSON = Path(__file__).resolve().parent.parent / "artifacts" / "app_surfaces_e2e_report.json"

ACCOUNTS = {
    "dispatcher": ("dispatcher@amicor.local", "dispatcher"),
    "driver_user": ("driver@amicor.local", "driver"),
    "rider": ("rider@amicor.local", "customer"),
    "provider": ("provider@amicor.local", "provider"),
    "admin": ("admin@amicor.local", "admin"),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_proof_context() -> dict:
    if PROOF_PRIOR.is_file():
        with open(PROOF_PRIOR, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("pass"):
            return data
    return {}


def snap(page, name: str, shots: list[str]) -> str:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    path = str(ARTIFACT_ROOT / f"{name}.png")
    page.screenshot(path=path, full_page=True)
    shots.append(path)
    return path


def dismiss_overlays(page) -> None:
    page.evaluate(
        """() => {
          try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}
          const ob = document.getElementById('amicor-onboarding-overlay');
          if (ob && ob.parentNode) ob.parentNode.removeChild(ob);
        }"""
    )
    skip = page.locator("#amicor-onboarding-overlay .ob-btn-skip")
    if skip.count() and skip.first.is_visible():
        skip.first.click()
        page.wait_for_timeout(400)


def wait_authenticated(page, timeout_ms: int = 45000) -> None:
    page.wait_for_function(
        """() => {
          const bar = document.getElementById('health-shell-session');
          if (!bar) return false;
          if (bar.textContent && bar.textContent.includes('Session required')) return false;
          if (window.AmiCorSession && typeof window.AmiCorSession.isActive === 'function') {
            return window.AmiCorSession.isActive();
          }
          return !bar.textContent.includes('Session required');
        }""",
        timeout=timeout_ms,
    )


def current_session_email(page) -> str:
    return page.evaluate(
        """() => {
          if (!window.AmiCorSession || typeof window.AmiCorSession.getCurrent !== 'function') return '';
          const current = window.AmiCorSession.getCurrent() || {};
          const identity = current.identity || {};
          return String(identity.email || '').toLowerCase();
        }"""
    )


def ensure_health_shell(page, route: str = "dashboard") -> None:
    page.goto(f"{BASE}/#/health-isf/{route}", wait_until="domcontentloaded")
    dismiss_overlays(page)
    page.wait_for_timeout(1200)
    shell = page.locator("#health-isf-shell")
    if shell.is_hidden():
        nav = page.locator(f'[data-health-nav-open="{route}"]').first
        if nav.count():
            nav.click(force=True)
            page.wait_for_timeout(800)
            dismiss_overlays(page)
    if shell.is_hidden():
        page.evaluate(
            """(route) => {
              if (window.AmiCorHealthISF && window.AmiCorHealthISF.navigate) {
                window.AmiCorHealthISF.navigate(route, true, { source: 'app_e2e', force: true });
              }
            }""",
            route,
        )
        page.wait_for_timeout(1500)
    page.wait_for_selector("#health-isf-shell:not([hidden])", timeout=30000)


def open_health_route(page, route: str) -> None:
    ensure_health_shell(page, route)
    page.evaluate(
        """(route) => {
          if (window.AmiCorHealthISF && window.AmiCorHealthISF.navigate) {
            window.AmiCorHealthISF.navigate(route, true, { source: 'app_e2e', force: true });
          }
        }""",
        route,
    )
    page.wait_for_timeout(1200)


def sign_out_if_needed(page) -> None:
    if not page.evaluate(
        "() => window.AmiCorSession && window.AmiCorSession.isActive && window.AmiCorSession.isActive()"
    ):
        return
    logout = page.locator('[data-health-action="logout"]')
    if logout.count():
        logout.first.click(force=True)
        page.wait_for_timeout(1500)
    page.evaluate(
        """() => {
          if (window.AmiCorSession && typeof window.AmiCorSession.clear === 'function') {
            window.AmiCorSession.clear();
          }
        }"""
    )
    page.wait_for_timeout(800)


def sign_in(page, email: str) -> None:
    ensure_health_shell(page, "dashboard")
    if current_session_email(page) == email.lower():
        wait_authenticated(page)
        return
    sign_out_if_needed(page)
    if not page.evaluate(
        "() => window.AmiCorSession && window.AmiCorSession.isActive && window.AmiCorSession.isActive()"
    ):
        login_btn = page.locator('[data-health-action="shell-login"]')
        login_btn.first.wait_for(state="visible", timeout=30000)
        dismiss_overlays(page)
        login_btn.first.click(force=True)
        page.locator("#amicor-auth-overlay").wait_for(state="visible", timeout=15000)
        page.locator(".amicor-auth-input").nth(0).fill(email)
        page.locator(".amicor-auth-input").nth(1).fill(PASSWORD)
        page.locator(".amicor-auth-modal form button[type='submit']").click()
        page.locator("#amicor-auth-overlay").wait_for(state="hidden", timeout=30000)
        dismiss_overlays(page)
    wait_authenticated(page)


def refresh_shell(page) -> None:
    btn = page.locator('#health-isf-shell [data-health-action="refresh"]').first
    if btn.count():
        btn.click()
    else:
        page.evaluate(
            "() => window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData && window.AmiCorHealthISF.refreshData()"
        )
    page.wait_for_timeout(2500)


def api_probe(page, checks: list[tuple[str, str, str]]) -> list[dict]:
    """Each check: (label, method_path, expect_substring in body or '200')."""
    return page.evaluate(
        """async (checks) => {
          const org = window.AmiCorSession && window.AmiCorSession.getOrganizationId
            ? window.AmiCorSession.getOrganizationId() : '';
          const q = org ? ('?organization_id=' + encodeURIComponent(org)) : '';
          const out = [];
          for (const item of checks) {
            const label = item[0];
            const path = item[1];
            const expect = item[2] || '200';
            const url = path.indexOf("?") >= 0
              ? (org ? path + "&organization_id=" + encodeURIComponent(org) : path)
              : path + q;
            try {
              const res = await window.AmiCorSession.authFetch(url, { method: 'GET' });
              const text = await res.text();
              let ok = res.ok;
              if (expect !== '200' && expect !== 'ok') {
                ok = ok && text.toLowerCase().indexOf(String(expect).toLowerCase()) >= 0;
              }
              out.push({ label, path, status: res.status, ok, sample: text.slice(0, 200) });
            } catch (err) {
              out.push({ label, path, status: 0, ok: false, sample: String(err) });
            }
          }
          return out;
        }""",
        checks,
    )


def panel_ok(text: str, *, forbid: tuple[str, ...] = ("loading...", "failed", "error", "unavailable")) -> bool:
    low = (text or "").lower()
    if len(low.strip()) < 8:
        return False
    return not any(bad in low for bad in forbid)


def result(name: str, passed: bool, **extra) -> dict:
    row = {"app": name, "pass": passed, **extra}
    log(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" — {extra.get('blocker')}" if extra.get("blocker") else ""))
    return row


def check_driver_app(page, ctx: dict, shots: list[str]) -> dict:
    name = "driver_app"
    issues: list[str] = []
    driver_id = str(ctx.get("driver_id") or "")
    ride_id = str(ctx.get("ride_id") or "")
    driver_phone = str(ctx.get("driver_phone") or "")

    sign_in(page, ACCOUNTS["dispatcher"][0])
    open_health_route(page, "drivers")
    refresh_shell(page)
    snap(page, "driver_01_drivers_tab", shots)

    if not driver_id:
        issues.append("missing proof driver_id")

    page.evaluate(
        """(driverId) => {
          const sel = document.getElementById('health-driver-runtime-id');
          if (!sel) throw new Error('driver select missing');
          let found = false;
          for (const opt of sel.options) {
            if (String(opt.value) === String(driverId)) found = true;
          }
          if (!found && driverId) {
            const opt = document.createElement('option');
            opt.value = driverId;
            opt.textContent = driverId.slice(0, 8);
            sel.appendChild(opt);
          }
          if (driverId) {
            sel.value = driverId;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }""",
        driver_id,
    )
    if driver_phone:
        page.locator("#health-driver-runtime-phone").fill(driver_phone)
    page.locator("#health-driver-login").click()
    page.wait_for_timeout(2000)
    snap(page, "driver_02_logged_in", shots)

    status_text = page.locator("#health-driver-runtime-status").inner_text()
    session_valid = panel_ok(status_text) and "active" in status_text.lower()
    if not session_valid:
        issues.append("driver runtime status not active/loaded")

    apis = api_probe(
        page,
        [
            ("driver_status", f"/api/health-isf/drivers/{driver_id}/status", "driver"),
            ("driver_workspace", f"/api/health-isf/drivers/{driver_id}/live-workspace", "driver"),
            ("assigned_rides", f"/api/health-isf/drivers/{driver_id}/assigned-rides", ride_id[:8] if ride_id else "200"),
        ],
    )
    for row in apis:
        if not row.get("ok"):
            issues.append(f"API {row.get('label')} {row.get('path')} status={row.get('status')}")

    refresh_shell(page)
    history = page.locator("#health-driver-auth-history").inner_text()
    if ride_id and "completed" not in history.lower() and ride_id[:8].lower() not in history.lower():
        # completed ride may have aged out of top-8; verify via API instead
        assigned = [a for a in apis if a.get("label") == "assigned_rides"][0]
        if not assigned.get("ok"):
            issues.append("completed ride not visible in driver history/API")

    route_btns = page.locator("[data-driver-route-progress]").count()
    if route_btns < 1:
        issues.append("driver route progress buttons missing")

    snap(page, "driver_03_final", shots)
    return result(
        name,
        len(issues) == 0,
        route=f"{BASE}/#/health-isf/drivers",
        driver_session_valid=session_valid,
        api_checks=apis,
        issues=issues,
        blocker="; ".join(issues) if issues else None,
    )


def check_rider_app(page, ctx: dict, shots: list[str]) -> dict:
    name = "rider_customer_app"
    issues: list[str] = []
    ride_id = str(ctx.get("ride_id") or "")
    rider_phone = "646-555-9900"

    sign_in(page, ACCOUNTS["rider"][0])
    open_health_route(page, "customer")
    page.evaluate(
        """(phone) => {
          if (window.AmiCorHealthISF && window.AmiCorHealthISF.state) {
            window.AmiCorHealthISF.state.customerWorkspace = window.AmiCorHealthISF.state.customerWorkspace || {};
            window.AmiCorHealthISF.state.customerWorkspace.riderPhone = phone;
          }
        }""",
        rider_phone,
    )
    refresh_shell(page)
    snap(page, "rider_01_customer_tab", shots)

    apis = api_probe(
        page,
        [
            ("customer_history", f"/api/health-isf/customers/workspace/history?rider_phone={rider_phone}&limit=40", "history"),
            ("customer_active", f"/api/health-isf/customers/workspace/active?rider_phone={rider_phone}", "200"),
            ("customer_tracking", f"/api/health-isf/customers/workspace/live-tracking?rider_phone={rider_phone}&limit=60", "200"),
            ("rides_by_phone", "/api/health-isf/rides", rider_phone.replace("-", "")),
        ],
    )
    hist_row = next((a for a in apis if a["label"] == "customer_history"), None)
    rides_row = next((a for a in apis if a["label"] == "rides_by_phone"), None)
    if not hist_row or not hist_row.get("ok"):
        issues.append("GET /api/health-isf/customers/workspace/history failed")
    elif '"history":[]' in (hist_row.get("sample") or ""):
        issues.append(
            "customer workspace history empty — dispatcher-created rides are not linked to customer-requests"
        )
    if ride_id and rides_row and rides_row.get("ok"):
        sample = (rides_row.get("sample") or "").lower()
        if ride_id[:8].lower() not in sample and rider_phone.replace("-", "") not in sample.replace("-", ""):
            issues.append(f"proof ride {ride_id[:8]} not found in /api/health-isf/rides for rider phone")
    elif ride_id:
        issues.append("GET /api/health-isf/rides failed while checking proof ride")

    active_panel = page.locator("#health-customer-active-ride").inner_text()
    history_panel = page.locator("#health-customer-request-history").inner_text()
    timeline_panel = page.locator("#health-customer-timeline").inner_text()
    booking_panel = page.locator("#health-customer-booking-management").inner_text()
    if "will appear here" in history_panel.lower() or "no customer request history" in history_panel.lower():
        issues.append("UI #health-customer-request-history shows empty placeholder")
    if "no active ride selected" in active_panel.lower() and ride_id:
        issues.append("UI #health-customer-active-ride shows no completed ride visibility")
    if "awaiting ride lifecycle" in timeline_panel.lower():
        issues.append("UI #health-customer-timeline not hydrated")
    if not panel_ok(booking_panel, forbid=("failed", "error")):
        issues.append("UI #health-customer-booking-management failed to load")

    open_health_route(page, "rides")
    refresh_shell(page)
    form = page.locator("#health-customer-request-form")
    if not form.count():
        issues.append("customer request intake form missing on rides tab (#health-customer-request-form)")
    elif form.locator("button[type='submit']").count() < 1:
        issues.append("customer request submit button missing on rides tab")

    snap(page, "rider_02_final", shots)
    return result(
        name,
        len(issues) == 0,
        route=f"{BASE}/#/health-isf/customer",
        rider_phone=rider_phone,
        api_checks=apis,
        panels={"active": active_panel[:120], "history": history_panel[:120], "timeline": timeline_panel[:120]},
        issues=issues,
        blocker="; ".join(issues) if issues else None,
    )


def check_provider_app(page, ctx: dict, shots: list[str]) -> dict:
    name = "provider_app"
    issues: list[str] = []

    sign_in(page, ACCOUNTS["provider"][0])
    open_health_route(page, "providers")
    refresh_shell(page)
    snap(page, "provider_01_providers_tab", shots)

    cards = page.locator("#health-providers-cards")
    cards.wait_for(state="attached", timeout=30000)
    card_text = cards.inner_text()
    if not panel_ok(card_text, forbid=("loading", "failed", "error", "no providers")):
        issues.append("provider cards empty or failed to load")

    provider_id = page.evaluate(
        """() => {
          const cards = document.querySelectorAll('#health-providers-cards .health-card, #health-providers-cards article, #health-providers-cards .health-item-card');
          if (cards.length) return null;
          const sel = document.getElementById('health-provider-select');
          if (!sel) return null;
          for (const opt of sel.options) {
            if (opt.value) return opt.value;
          }
          return null;
        }"""
    )
    if not provider_id:
        provider_id = page.evaluate(
            """async () => {
              const org = window.AmiCorSession.getOrganizationId();
              const res = await window.AmiCorSession.authFetch('/api/health-isf/providers'
                + (org ? ('?organization_id=' + encodeURIComponent(org)) : ''));
              const rows = res.ok ? await res.json() : [];
              return Array.isArray(rows) && rows[0] ? rows[0].id : null;
            }"""
        )

    apis = api_probe(
        page,
        [
            ("providers_list", "/api/health-isf/providers", "id"),
        ],
    )
    if provider_id:
        apis.extend(
            api_probe(
                page,
                [
                    (
                        "transport_queue",
                        f"/api/health-isf/providers/{provider_id}/transport-queue?include_completed=true&limit=120",
                        "items",
                    ),
                ],
            )
        )
    else:
        issues.append("no provider_id resolved")

    for row in apis:
        if not row.get("ok"):
            issues.append(f"API {row.get('label')} failed status={row.get('status')}")

    feed = page.locator("#health-provider-operational-feed").inner_text()
    sync = page.locator("#health-provider-sync").inner_text()
    if not panel_ok(feed, forbid=("waiting for", "failed", "error")):
        issues.append("provider operational feed not hydrated")
    if not panel_ok(sync, forbid=("waiting for", "failed", "error")):
        issues.append("provider sync timeline not hydrated")

    snap(page, "provider_02_final", shots)
    return result(
        name,
        len(issues) == 0,
        route=f"{BASE}/#/health-isf/providers",
        provider_id=provider_id,
        api_checks=apis,
        issues=issues,
        blocker="; ".join(issues) if issues else None,
    )


def check_dispatch_app(page, ctx: dict, shots: list[str]) -> dict:
    name = "dispatch_app"
    issues: list[str] = []
    ride_id = str(ctx.get("ride_id") or "")
    passenger = str(ctx.get("passenger_name") or "")

    sign_in(page, ACCOUNTS["dispatcher"][0])
    open_health_route(page, "dispatch")
    refresh_shell(page)
    snap(page, "dispatch_01_control_center", shots)

    worklist = page.locator("#health-dispatch-worklist").inner_text()
    workflow = page.locator("#health-dispatch-workflow").inner_text()
    assignments = page.locator("#health-dispatch-assignments").inner_text()
    if not panel_ok(worklist, forbid=("loading dispatch worklist", "failed", "error")):
        issues.append("UI #health-dispatch-worklist stuck loading")
    if not panel_ok(workflow, forbid=("loading assignment workflow", "failed", "error")):
        issues.append("UI #health-dispatch-workflow stuck loading")
    if not panel_ok(assignments, forbid=("loading active assignment", "failed", "error")):
        issues.append("UI #health-dispatch-assignments stuck loading")

    apis = api_probe(
        page,
        [
            ("dispatch_queue", "/api/health-isf/dispatch/queue", "ride_id"),
            ("dispatch_active", "/api/health-isf/dispatch/active-assignments", "200"),
        ],
    )
    for row in apis:
        if not row.get("ok"):
            issues.append(f"API {row.get('path')} failed (status={row.get('status')})")

    open_health_route(page, "rides")
    refresh_shell(page)
    snap(page, "dispatch_02_rides_board", shots)

    for btn_id in ("health-dispatch-auto-assign", "health-dispatch-reassign", "health-dispatch-refresh-intel", "health-ai-refresh"):
        if page.locator(f"#{btn_id}").count() < 1:
            issues.append(f"missing button #{btn_id} on rides tab")

    refresh_btn = page.locator("#health-ai-refresh")
    if refresh_btn.count():
        refresh_btn.first.scroll_into_view_if_needed()
        refresh_btn.first.click(force=True)
        page.wait_for_timeout(2000)

    queue_text = page.locator("#health-dispatch-intel-queue").inner_text()
    assignments_text = page.locator("#health-dispatch-active-assignments").inner_text()
    board_text = page.locator("#health-dispatch-board").inner_text()
    if not panel_ok(queue_text, forbid=("loading dispatch queue", "failed", "error")):
        issues.append("UI #health-dispatch-intel-queue stuck loading on rides tab")
    if not panel_ok(assignments_text, forbid=("loading active", "failed", "error")):
        issues.append("UI #health-dispatch-active-assignments stuck loading on rides tab")
    if not panel_ok(board_text, forbid=("failed", "error")):
        issues.append("UI #health-dispatch-board failed on rides tab")

    if ride_id:
        rides_api = api_probe(page, [("rides", "/api/health-isf/rides", ride_id[:8])])[0]
        found = (
            ride_id[:8].lower() in board_text.lower()
            or passenger.lower() in board_text.lower()
            or (rides_api.get("ok") and "completed" in (rides_api.get("sample") or "").lower())
        )
        if not found:
            issues.append(f"proof ride {ride_id[:8]} not visible on dispatch rides board or rides API")

    snap(page, "dispatch_03_final", shots)
    return result(
        name,
        len(issues) == 0,
        routes={
            "dispatch_control_center": f"{BASE}/#/health-isf/dispatch",
            "rides_dispatch_board": f"{BASE}/#/health-isf/rides",
        },
        api_checks=apis,
        panels={"queue": queue_text[:150], "assignments": assignments_text[:150], "worklist": worklist[:150]},
        issues=issues,
        blocker="; ".join(issues) if issues else None,
    )


def check_dashboard_admin_billing(page, ctx: dict, shots: list[str]) -> dict:
    name = "dashboard_admin_billing"
    issues: list[str] = []
    ride_id = str(ctx.get("ride_id") or "")

    sign_in(page, ACCOUNTS["admin"][0])
    open_health_route(page, "dashboard")
    refresh_shell(page)
    snap(page, "admin_01_dashboard", shots)

    summary = page.locator("#health-dispatch-summary").inner_text()
    dash_cards = page.locator("#health-dashboard-cards").inner_text() if page.locator("#health-dashboard-cards").count() else ""
    if not panel_ok(summary):
        issues.append("dashboard summary stuck loading")
    if dash_cards and not panel_ok(dash_cards):
        issues.append("dashboard KPI cards failed")

    dash_api = api_probe(
        page,
        [
            ("dashboard", "/api/health-isf/dashboard", "completed_rides"),
            ("activity_feed", "/api/health-isf/activity-feed", "activities"),
        ],
    )
    for row in dash_api:
        if not row.get("ok"):
            issues.append(f"API {row.get('label')} failed")
    if ride_id:
        feed = next((a for a in dash_api if a["label"] == "activity_feed"), {})
        if ride_id[:8].lower() not in (feed.get("sample") or "").lower():
            issues.append(f"proof ride {ride_id[:8]} not in activity feed sample")

    open_health_route(page, "billing")
    refresh_shell(page)
    snap(page, "admin_02_billing", shots)

    billing_kpis = page.locator("#health-billing-kpis").inner_text()
    billing_claims = page.locator("#health-billing-claims").inner_text()
    billing_aging = page.locator("#health-billing-aging").inner_text()
    if not panel_ok(billing_kpis):
        issues.append("billing KPIs stuck loading")
    if not panel_ok(billing_claims, forbid=("loading claims", "failed", "error")):
        issues.append("billing claims queue failed")
    if not panel_ok(billing_aging, forbid=("loading reconciliation", "failed")):
        issues.append("billing aging panel failed")

    billing_apis = api_probe(
        page,
        [
            ("rides_for_billing", "/api/health-isf/rides", "status"),
        ],
    )
    for row in billing_apis:
        if not row.get("ok"):
            issues.append(f"API {row.get('label')} failed status={row.get('status')}")

    open_health_route(page, "admin")
    refresh_shell(page)
    snap(page, "admin_03_admin", shots)

    admin_summary = page.locator("#health-admin-summary").inner_text()
    admin_audit = page.locator("#health-admin-lifecycle-audit").inner_text()
    if not panel_ok(admin_summary):
        issues.append("admin summary stuck loading")
    if not panel_ok(admin_audit, forbid=("awaiting", "failed", "error")):
        issues.append("admin lifecycle audit not hydrated")

    admin_apis = api_probe(
        page,
        [
            ("admin_summary", "/api/health-isf/admin/command-center/summary", "200"),
            ("admin_live_ops", "/api/health-isf/admin/live-operations", "200"),
        ],
    )
    for row in admin_apis:
        if not row.get("ok"):
            issues.append(f"API {row.get('label')} failed status={row.get('status')}")

    dash_completed = None
    for row in dash_api:
        if row.get("label") == "dashboard" and row.get("ok"):
            m = re.search(r'"completed_rides"\s*:\s*(\d+)', row.get("sample") or "")
            if m:
                dash_completed = int(m.group(1))

    return result(
        name,
        len(issues) == 0,
        routes={
            "dashboard": f"{BASE}/#/health-isf/dashboard",
            "billing": f"{BASE}/#/health-isf/billing",
            "admin": f"{BASE}/#/health-isf/admin",
        },
        dashboard_completed_rides=dash_completed,
        api_checks=dash_api + billing_apis + admin_apis,
        panels={"billing_kpis": billing_kpis[:120], "admin_summary": admin_summary[:120]},
        issues=issues,
        blocker="; ".join(issues) if issues else None,
    )


def main() -> int:
    try:
        httpx.get(f"{BASE}/health", timeout=5).raise_for_status()
    except Exception as exc:
        log(f"Preview not reachable at {BASE}: {exc}")
        return 1

    ctx = load_proof_context()
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "preview_base": BASE,
        "proof_ride_context": {
            "ride_id": ctx.get("ride_id"),
            "driver_id": ctx.get("driver_id"),
            "driver_name": ctx.get("driver_name"),
            "passenger_name": ctx.get("passenger_name"),
            "final_ride_status": ctx.get("final_ride_status"),
        },
        "apps": [],
        "all_pass": False,
        "screenshots": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        context.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")
        page = context.new_page()
        shots: list[str] = []
        try:
            checks = [
                ("driver_app", check_driver_app),
                ("rider_customer_app", check_rider_app),
                ("provider_app", check_provider_app),
                ("dispatch_app", check_dispatch_app),
                ("dashboard_admin_billing", check_dashboard_admin_billing),
            ]
            for label, fn in checks:
                try:
                    report["apps"].append(fn(page, ctx, shots))
                except Exception as exc:
                    log(f"[FAIL] {label} unexpected: {exc}")
                    snap(page, f"{label}_unexpected_failure", shots)
                    report["apps"].append(
                        {
                            "app": label,
                            "pass": False,
                            "issues": [str(exc)],
                            "blocker": str(exc),
                        }
                    )
        finally:
            browser.close()

    report["screenshots"] = shots
    report["all_pass"] = all(a.get("pass") for a in report["apps"])
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    log(f"Wrote {REPORT_JSON}")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
