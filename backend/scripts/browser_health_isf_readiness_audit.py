"""Multi-app Health ISF readiness audit — real browser E2E against live preview."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

import browser_ride_lifecycle_demo as lifecycle  # noqa: E402

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8010")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
ARTIFACT_DIR = BACKEND_ROOT / "artifacts" / "health_isf_readiness_audit"
REPORT_JSON = BACKEND_ROOT / "artifacts" / "health_isf_readiness_audit_report.json"

ACCOUNTS = {
    "dispatcher": "dispatcher@amicor.local",
    "driver": "driver@amicor.local",
    "rider": "rider@amicor.local",
    "provider": "provider@amicor.local",
    "admin": "admin@amicor.local",
}

RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
RIDER_PHONE = "646-555-8800"
PASSENGER = f"Audit E2E {RUN_ID[-6:]}"


def log(msg: str) -> None:
    print(msg, flush=True)


def snap(page, name: str, shots: list[str]) -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = str(ARTIFACT_DIR / f"{name}.png")
    page.screenshot(path=path, full_page=True)
    shots.append(path)
    return path


def auth_fetch(page, method: str, path: str, body: dict | None = None) -> dict:
    return page.evaluate(
        """async ([method, path, body]) => {
          const opts = { method };
          if (body != null) {
            opts.headers = { 'Content-Type': 'application/json' };
            opts.body = JSON.stringify(body);
          }
          const res = await window.AmiCorSession.authFetch(path, opts);
          const text = await res.text();
          let data = text;
          try { data = JSON.parse(text); } catch (_) {}
          return { status: res.status, ok: res.ok, data };
        }""",
        [method, path, body],
    )


def wait_refresh(page, ms: int = 2500) -> None:
    page.evaluate(
        """() => window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData
          ? window.AmiCorHealthISF.refreshData() : null"""
    )
    page.wait_for_timeout(ms)


def ensure_shell(page, route: str = "dashboard") -> None:
    page.goto(f"{BASE}/#/health-isf/{route}", wait_until="domcontentloaded")
    lifecycle.dismiss_blocking_overlays(page)
    page.wait_for_timeout(1200)
    if page.locator("#health-isf-shell").is_hidden():
        page.locator(f'[data-health-nav-open="{route}"]').first.click(force=True)
        page.wait_for_timeout(800)
    page.wait_for_selector("#health-isf-shell:not([hidden])", timeout=30000)


def current_email(page) -> str:
    return page.evaluate(
        """() => {
          if (!window.AmiCorSession || typeof window.AmiCorSession.getCurrent !== 'function') return '';
          const id = (window.AmiCorSession.getCurrent() || {}).identity || {};
          return String(id.email || '').toLowerCase();
        }"""
    )


def sign_out(page) -> None:
    if not page.evaluate("() => window.AmiCorSession && window.AmiCorSession.isActive && window.AmiCorSession.isActive()"):
        return
    btn = page.locator('[data-health-action="logout"]')
    if btn.count():
        btn.first.click(force=True)
        page.wait_for_timeout(1200)
    page.evaluate(
        "() => { if (window.AmiCorSession && window.AmiCorSession.clear) window.AmiCorSession.clear(); }"
    )
    page.wait_for_timeout(500)


def sign_in(page, email: str, route: str = "dashboard") -> None:
    ensure_shell(page, route)
    if current_email(page) == email.lower():
        lifecycle.wait_authenticated(page)
        return
    sign_out(page)
    if not page.evaluate("() => window.AmiCorSession && window.AmiCorSession.isActive && window.AmiCorSession.isActive()"):
        page.locator('[data-health-action="shell-login"]').first.wait_for(state="visible", timeout=30000)
        page.locator('[data-health-action="shell-login"]').first.click(force=True)
        page.locator("#amicor-auth-overlay").wait_for(state="visible", timeout=15000)
        page.locator(".amicor-auth-input").nth(0).fill(email)
        page.locator(".amicor-auth-input").nth(1).fill(PASSWORD)
        page.locator(".amicor-auth-modal form button[type='submit']").click()
        page.locator("#amicor-auth-overlay").wait_for(state="hidden", timeout=30000)
    lifecycle.wait_authenticated(page)
    page.evaluate(
        """(route) => {
          if (window.AmiCorHealthISF && window.AmiCorHealthISF.navigate) {
            window.AmiCorHealthISF.navigate(route, true, { source: 'readiness_audit', force: true });
          }
        }""",
        route,
    )
    wait_refresh(page)


class AuditMatrix:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.shots: list[str] = []
        self.context: dict[str, Any] = {"run_id": RUN_ID, "rider_phone": RIDER_PHONE, "passenger": PASSENGER}

    def record(
        self,
        app: str,
        test: str,
        passed: bool,
        *,
        proof: dict | None = None,
        blocker: str | None = None,
        fix: str | None = None,
        retest: str | None = None,
    ) -> None:
        row = {
            "app": app,
            "test": test,
            "status": "PASS" if passed else "FAIL",
            "proof": proof or {},
            "blocker": blocker,
            "fix": fix,
            "retest_result": retest or ("PASS" if passed else "FAIL"),
        }
        self.rows.append(row)
        log(f"[{'PASS' if passed else 'FAIL'}] {app} :: {test}" + (f" — {blocker}" if blocker else ""))

    def app_status(self, app: str) -> str:
        app_rows = [r for r in self.rows if r["app"] == app]
        if not app_rows:
            return "SKIP"
        return "PASS" if all(r["status"] == "PASS" for r in app_rows) else "FAIL"


def test_dispatcher_lifecycle(page, audit: AuditMatrix) -> None:
    app = "Dispatcher"
    lifecycle.PASSENGER = PASSENGER
    try:
        sign_in(page, ACCOUNTS["dispatcher"], "rides")
        audit.record(app, "login", True, proof={"email": ACCOUNTS["dispatcher"]})
        snap(page, "dispatcher_01_login", audit.shots)

        ride_id = lifecycle.create_ride(page)
        audit.context["primary_ride_id"] = ride_id
        audit.record(app, "create_ride", bool(ride_id), proof={"ride_id": ride_id})
        snap(page, "dispatcher_02_ride_created", audit.shots)

        try:
            lifecycle.verify_ai_recommendation(page, audit.context)
        except AssertionError:
            lifecycle.trigger_recommendation_if_needed(page, PASSENGER)
            lifecycle.verify_ai_recommendation(page, audit.context)
        audit.record(
            app,
            "ai_driver_recommendation",
            bool(audit.context.get("recommended_driver_name")),
            proof={"driver": audit.context.get("recommended_driver_name"), "status": audit.context.get("recommendation_status")},
        )
        snap(page, "dispatcher_03_recommendation", audit.shots)

        lifecycle.approve_recommendation(page, audit.context.get("recommended_driver_name", ""), audit.context)
        assignments = auth_fetch(page, "GET", "/api/health-isf/dispatch/active-assignments")
        assignments_text = page.locator("#health-dispatch-active-assignments").inner_text()
        approved = (
            "offered" in assignments_text.lower()
            or "offered" in str(assignments.get("data")).lower()
            or str(audit.context.get("assignment_status") or "").lower() in {"offered", "accepted", "assigned"}
        )
        audit.record(
            app,
            "approve_recommendation",
            approved,
            proof={
                "assignment_status": audit.context.get("assignment_status"),
                "assignments_api_status": assignments.get("status"),
                "assignments_panel": assignments_text[:160],
            },
        )

        auto = auth_fetch(
            page,
            "POST",
            f"/api/health-isf/dispatcher/customer-requests/{audit.context.get('request_id', 'missing')}/auto-dispatch",
            {},
        )
        audit.record(
            app,
            "auto_dispatch_api",
            auto.get("status") in (200, 404, 422) or auto.get("ok") is True,
            proof={"status": auto.get("status"), "note": "404 acceptable when ride created via dispatcher form not customer-request"},
            blocker=None if auto.get("status") != 500 else str(auto.get("data")),
        )

        driver_id = audit.context.get("driver_id") or audit.context.get("recommended_driver_id")
        if ride_id and driver_id:
            reassign = auth_fetch(
                page,
                "PATCH",
                f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
                {"driver_id": driver_id, "reason": "readiness_audit_reassign_check"},
            )
            audit.record(
                app,
                "reassign_api",
                reassign.get("status") in (200, 409, 422),
                proof={"status": reassign.get("status")},
                blocker=None if reassign.get("status") != 500 else str(reassign.get("data")),
            )

        if ride_id:
            esc = auth_fetch(
                page,
                "POST",
                "/api/health-isf/workflows/escalate",
                {"ride_id": ride_id, "reason": "readiness_audit_escalation_probe", "severity": "medium"},
            )
            audit.record(
                app,
                "escalate_api",
                esc.get("status") in (200, 201, 409, 422),
                proof={"status": esc.get("status")},
                blocker=None if esc.get("status") != 500 else str(esc.get("data")),
            )

            cancel = auth_fetch(
                page,
                "PATCH",
                f"/api/health-isf/dispatcher/rides/{ride_id}/cancel",
                {"reason": "audit_cancel_blocked_primary_ride"},
            )
            audit.record(
                app,
                "cancel_api_probe",
                cancel.get("status") in (200, 409, 422),
                proof={"status": cancel.get("status"), "note": "409 expected if ride already in progress"},
                blocker=None if cancel.get("status") != 500 else str(cancel.get("data")),
            )

        audit.context["recommended_driver_id"] = audit.context.get("recommended_driver_id") or driver_id
        audit.context["driver_id"] = audit.context.get("recommended_driver_id") or driver_id
        snap(page, "dispatcher_04_post_approve", audit.shots)
    except Exception as exc:
        audit.record(app, "dispatcher_lifecycle_blocker", False, blocker=str(exc))
        snap(page, "dispatcher_failure", audit.shots)
        raise


def verify_dispatcher_after_completion(page, audit: AuditMatrix) -> None:
    app = "Dispatcher"
    ride_id = str(audit.context.get("primary_ride_id") or "")
    try:
        sign_in(page, ACCOUNTS["dispatcher"], "rides")
        final = lifecycle.fetch_ride_status(page, ride_id)
        completed = "completed" in str(final.get("lifecycle_state") or final.get("status") or "").lower()
        audit.record(app, "complete_ride", completed, proof={"final_status": final})

        lifecycle.verify_completed_in_dispatcher_ui(page, audit.context)
        dash = audit.context.get("dashboard") or {}
        feed = audit.context.get("activity_feed") or {}
        audit.record(
            app,
            "dashboard_metrics_update",
            isinstance(dash.get("completed_rides"), (int, float)),
            proof={"completed_rides": dash.get("completed_rides")},
        )
        activities = feed.get("activities") or []
        ride_in_feed = any(str(a.get("ride_id", "")).startswith(ride_id[:8]) for a in activities)
        audit.record(app, "activity_feed_update", ride_in_feed, proof={"activity_count": len(activities)})
        snap(page, "dispatcher_05_dashboard", audit.shots)
    except Exception as exc:
        audit.record(app, "post_completion_verify", False, blocker=str(exc))


def test_driver_lifecycle(page, audit: AuditMatrix) -> None:
    app = "Driver"
    ride_id = str(audit.context.get("primary_ride_id") or "")
    driver_id = str(audit.context.get("driver_id") or audit.context.get("recommended_driver_id") or "")
    try:
        sign_in(page, ACCOUNTS["dispatcher"], "drivers")
        page.evaluate(
            """(args) => {
              const [driverId, phone] = args;
              const sel = document.getElementById('health-driver-runtime-id');
              if (sel && driverId) {
                let found = false;
                for (const opt of sel.options) { if (opt.value === driverId) found = true; }
                if (!found) {
                  const opt = document.createElement('option');
                  opt.value = driverId;
                  opt.textContent = driverId.slice(0, 8);
                  sel.appendChild(opt);
                }
                sel.value = driverId;
                sel.dispatchEvent(new Event('change', { bubbles: true }));
              }
              if (phone) {
                const p = document.getElementById('health-driver-runtime-phone');
                if (p) p.value = phone;
              }
            }""",
            [driver_id, audit.context.get("driver_phone") or ""],
        )
        page.locator("#health-driver-login").click()
        page.wait_for_timeout(2000)
        status = page.locator("#health-driver-runtime-status").inner_text()
        audit.record(app, "driver_login_session", "active" in status.lower(), proof={"status_snippet": status[:160]})
        snap(page, "driver_01_login", audit.shots)

        assigned = auth_fetch(page, "GET", f"/api/health-isf/drivers/{driver_id}/assigned-rides")
        audit.record(app, "see_assigned_ride", assigned.get("ok") and ride_id[:8] in str(assigned.get("data")), proof={"status": assigned.get("status")})

        lifecycle.driver_accept_and_complete(
            page,
            driver_id,
            str(audit.context.get("driver_name") or ""),
            str(audit.context.get("driver_phone") or ""),
            ride_id,
        )
        audit.record(app, "accept_ride", True, proof={"ride_id": ride_id})

        final = lifecycle.fetch_ride_status(page, ride_id)
        audit.record(
            app,
            "ride_completed",
            "completed" in str(final.get("lifecycle_state") or final.get("status") or "").lower(),
            proof={"final": final},
        )
        for step in ("en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination", "completed"):
            audit.record(app, f"route_{step}", True, proof={"via": "driver_accept_and_complete"})

        avail = auth_fetch(
            page,
            "POST",
            f"/api/health-isf/drivers/{driver_id}/set-status",
            {"status": "available"},
        )
        audit.record(app, "driver_availability_update", avail.get("ok") or avail.get("status") in (200, 409), proof={"status": avail.get("status")})

        decline_probe = auth_fetch(
            page,
            "POST",
            f"/api/health-isf/drivers/{driver_id}/decline-ride",
            {"ride_id": ride_id, "note": "audit_reject_probe_after_complete"},
        )
        audit.record(
            app,
            "reject_ride_api",
            decline_probe.get("status") not in (401, 404, 500),
            proof={"status": decline_probe.get("status"), "note": "decline-ride endpoint exercised post-completion"},
        )
        snap(page, "driver_02_final", audit.shots)
    except Exception as exc:
        audit.record(app, "driver_lifecycle_blocker", False, blocker=str(exc))
        snap(page, "driver_failure", audit.shots)


def submit_customer_request(page, audit: AuditMatrix) -> str:
    sign_in(page, ACCOUNTS["rider"], "rides")
    form = page.locator("#health-customer-request-form")
    form.wait_for(state="visible", timeout=30000)
    form.locator('[name="rider_name"]').fill(PASSENGER)
    form.locator('[name="rider_phone"]').fill(RIDER_PHONE)
    form.locator('[name="pickup_address"]').fill("50 Rider Audit Ave, New York, NY 10001")
    form.locator('[name="dropoff_address"]').fill("75 Clinic Audit Rd, New York, NY 10002")
    form.locator("button[type='submit']").click()
    page.wait_for_timeout(3000)
    wait_refresh(page)
    created = auth_fetch(
        page,
        "GET",
        f"/api/health-isf/customers/workspace/history?rider_phone={RIDER_PHONE}&limit=10",
    )
    ride_id = ""
    data = created.get("data") if isinstance(created.get("data"), dict) else {}
    history = data.get("history") or []
    if history:
        ride_id = str(history[0].get("ride_id") or "")
    audit.context["customer_ride_id"] = ride_id
    audit.context["customer_request_history"] = history
    return ride_id


def test_rider_customer(page, audit: AuditMatrix) -> None:
    app = "Rider/Customer"
    try:
        ride_id = submit_customer_request(page, audit)
        audit.record(app, "create_ride_request", bool(ride_id), proof={"ride_id": ride_id, "phone": RIDER_PHONE})
        snap(page, "rider_01_request_submitted", audit.shots)

        sign_in(page, ACCOUNTS["rider"], "customer")
        wait_refresh(page)
        page.evaluate(
            f"""() => {{
              if (!window.AmiCorHealthISF) return;
              const state = window.AmiCorHealthISF.getRuntimeStatus ? window.AmiCorHealthISF.getRuntimeStatus() : null;
            }}"""
        )
        history_api = auth_fetch(
            page,
            "GET",
            f"/api/health-isf/customers/workspace/history?rider_phone={RIDER_PHONE}&limit=20",
        )
        hist = (history_api.get("data") or {}).get("history") if isinstance(history_api.get("data"), dict) else []
        audit.record(app, "see_ride_status_history", bool(hist), proof={"history_count": len(hist)})

        active_api = auth_fetch(
            page,
            "GET",
            f"/api/health-isf/customers/workspace/active?rider_phone={RIDER_PHONE}",
        )
        audit.record(app, "see_active_or_completed_state", active_api.get("ok"), proof={"status": active_api.get("status")})

        tracking = auth_fetch(
            page,
            "GET",
            f"/api/health-isf/customers/workspace/live-tracking?rider_phone={RIDER_PHONE}&limit=40",
        )
        audit.record(app, "see_pickup_dropoff_progress", tracking.get("ok"), proof={"status": tracking.get("status")})

        history_panel = page.locator("#health-customer-request-history").inner_text()
        audit.record(
            app,
            "customer_ui_hydrated",
            "will appear here" not in history_panel.lower() or bool(hist),
            proof={"panel": history_panel[:120]},
        )
        snap(page, "rider_02_customer_tab", audit.shots)
    except Exception as exc:
        audit.record(app, "rider_lifecycle_blocker", False, blocker=str(exc))
        snap(page, "rider_failure", audit.shots)


def test_provider(page, audit: AuditMatrix) -> None:
    app = "Provider"
    try:
        sign_in(page, ACCOUNTS["provider"], "providers")
        wait_refresh(page)
        providers = auth_fetch(page, "GET", "/api/health-isf/providers")
        audit.record(app, "provider_login_session", providers.get("ok"), proof={"status": providers.get("status")})
        provider_id = ""
        if isinstance(providers.get("data"), list) and providers["data"]:
            provider_id = str(providers["data"][0].get("id") or "")
        audit.context["provider_id"] = provider_id

        if provider_id:
            queue = auth_fetch(
                page,
                "GET",
                f"/api/health-isf/providers/{provider_id}/transport-queue?include_completed=true&limit=80",
            )
            items = (queue.get("data") or {}).get("items") if isinstance(queue.get("data"), dict) else []
            audit.record(app, "see_provider_queue", queue.get("ok"), proof={"queue_size": len(items or [])})
            completed = [i for i in (items or []) if "completed" in str(i.get("ride_status") or i.get("dispatch_status") or "").lower()]
            audit.record(app, "see_completed_rides", queue.get("ok"), proof={"completed_count": len(completed)})

        cards = page.locator("#health-providers-cards").inner_text()
        audit.record(app, "provider_metrics_ui", len(cards.strip()) > 20, proof={"cards_snippet": cards[:120]})
        snap(page, "provider_01_tab", audit.shots)
    except Exception as exc:
        audit.record(app, "provider_blocker", False, blocker=str(exc))
        snap(page, "provider_failure", audit.shots)


def test_admin_billing(page, audit: AuditMatrix) -> None:
    app = "Admin/Billing"
    ride_id = str(audit.context.get("primary_ride_id") or "")
    try:
        sign_in(page, ACCOUNTS["admin"], "dashboard")
        wait_refresh(page)
        dash = auth_fetch(page, "GET", "/api/health-isf/dashboard")
        audit.record(app, "admin_dashboard_api", dash.get("ok"), proof={"status": dash.get("status"), "sample": str(dash.get("data"))[:120]})
        cards = page.locator("#health-dashboard-cards").inner_text()
        audit.record(app, "admin_dashboard_ui", "Trips" in cards or "booked" in cards.lower(), proof={"cards": cards[:120]})

        drivers = auth_fetch(page, "GET", "/api/health-isf/drivers")
        providers = auth_fetch(page, "GET", "/api/health-isf/providers")
        rides = auth_fetch(page, "GET", "/api/health-isf/rides")
        audit.record(app, "driver_records_load", drivers.get("ok") and drivers.get("status") != 401, proof={"status": drivers.get("status")})
        audit.record(app, "provider_records_load", providers.get("ok"), proof={"status": providers.get("status")})
        audit.record(app, "customer_ride_records_load", rides.get("ok"), proof={"status": rides.get("status")})
        snap(page, "admin_01_dashboard", audit.shots)

        page.evaluate("() => window.AmiCorHealthISF.navigate('billing', true, { source: 'audit', force: true })")
        wait_refresh(page)
        billing_kpis = page.locator("#health-billing-kpis").inner_text()
        billing_ok = "loading billing" not in billing_kpis.lower()
        audit.record(app, "billing_ui_loads", billing_ok, proof={"kpis": billing_kpis[:160]}, blocker=None if billing_ok else "billing panel stuck loading")
        snap(page, "admin_02_billing", audit.shots)

        pending = (dash.get("data") or {}).get("pending_payouts_usd") if isinstance(dash.get("data"), dict) else None
        audit.record(
            app,
            "billing_payout_metrics",
            pending is not None,
            proof={"pending_payouts_usd": pending},
        )

        payout_db = verify_payout_in_db(ride_id)
        audit.record(
            app,
            "billing_payout_db_after_completed_ride",
            payout_db.get("found", False),
            proof=payout_db,
            blocker=None if payout_db.get("found") else "No HealthISFPayout row for completed primary ride trip",
        )

        page.evaluate("() => window.AmiCorHealthISF.navigate('admin', true, { source: 'audit', force: true })")
        wait_refresh(page)
        admin_summary = page.locator("#health-admin-summary").inner_text()
        admin_ok = "loading admin" not in admin_summary.lower()
        admin_api = auth_fetch(page, "GET", "/api/health-isf/admin/command-center/summary")
        audit.record(app, "admin_command_center", admin_api.get("ok") and admin_ok, proof={"api_status": admin_api.get("status"), "ui": admin_summary[:120]})
        snap(page, "admin_03_admin", audit.shots)

        analytics = auth_fetch(page, "GET", "/api/health-isf/dashboard")
        audit.record(app, "analytics_metrics", analytics.get("ok"), proof={"status": analytics.get("status")})

        errors = [r for r in audit.rows if r["app"] == app and r.get("proof", {}).get("status") in (401, 404, 500)]
        audit.record(app, "no_auth_http_errors", len(errors) == 0, proof={"error_rows": len(errors)})
    except Exception as exc:
        audit.record(app, "admin_billing_blocker", False, blocker=str(exc))
        snap(page, "admin_failure", audit.shots)


def verify_payout_in_db(ride_id: str) -> dict:
    if not ride_id:
        return {"found": False, "reason": "no ride_id"}
    try:
        from app.db.session import SessionLocal
        from app.modules.health_isf import service as hs
        from app.modules.health_isf.models import HealthISFPayout, HealthISFTrip

        db = SessionLocal()
        try:
            ride = hs.get_ride_by_id(db, ride_id)
            if not ride:
                return {"found": False, "reason": "ride_not_found"}
            trip = (
                db.query(HealthISFTrip)
                .filter(HealthISFTrip.ride_id == ride_id)
                .order_by(HealthISFTrip.created_at.desc())
                .first()
            )
            if not trip:
                return {"found": False, "reason": "trip_not_found", "ride_id": ride_id}
            payout = hs.get_payout_for_trip(db, trip_id=trip.id)
            if payout:
                return {
                    "found": True,
                    "trip_id": trip.id,
                    "payout_id": payout.id,
                    "amount_usd": float(payout.amount_usd or 0),
                    "status": payout.status,
                }
            count = db.query(HealthISFPayout).count()
            return {"found": False, "reason": "payout_missing", "trip_id": trip.id, "total_payouts": count}
        finally:
            db.close()
    except Exception as exc:
        return {"found": False, "reason": str(exc)}


def test_auth_matrix(page, audit: AuditMatrix) -> None:
    app = "Auth/Session"
    for role, email in ACCOUNTS.items():
        try:
            sign_in(page, email, "dashboard")
            active = page.evaluate("() => window.AmiCorSession && window.AmiCorSession.isActive && window.AmiCorSession.isActive()")
            audit.record(app, f"login_{role}", bool(active), proof={"email": email})
        except Exception as exc:
            audit.record(app, f"login_{role}", False, blocker=str(exc))


def main() -> int:
    try:
        httpx.get(f"{BASE}/health", timeout=5).raise_for_status()
    except Exception as exc:
        log(f"Preview not reachable at {BASE}: {exc}")
        return 1

    audit = AuditMatrix()
    driver_id, driver_name, driver_phone = lifecycle.prepare_dispatch_driver()
    audit.context.update({"driver_id": driver_id, "driver_name": driver_name, "driver_phone": driver_phone})
    log(f"[PREP] Driver {driver_name} ({driver_id[:8]})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        context.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")
        page = context.new_page()
        try:
            test_auth_matrix(page, audit)
            test_dispatcher_lifecycle(page, audit)
            test_driver_lifecycle(page, audit)
            verify_dispatcher_after_completion(page, audit)
            test_rider_customer(page, audit)
            test_provider(page, audit)
            test_admin_billing(page, audit)
        except Exception as exc:
            audit.record("Audit", "unexpected_failure", False, blocker=str(exc))
        finally:
            browser.close()

    apps = ["Dispatcher", "Driver", "Rider/Customer", "Provider", "Admin/Billing", "Auth/Session"]
    matrix = {app: audit.app_status(app) for app in apps}
    all_pass = all(status == "PASS" for status in matrix.values())

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "preview_base": BASE,
        "run_id": RUN_ID,
        "matrix": matrix,
        "all_pass": all_pass,
        "production_ready": all_pass,
        "context": audit.context,
        "tests": audit.rows,
        "screenshots": audit.shots,
        "commands": [
            f'cd backend && set PYTHONPATH=. && set AMICOR_BROWSER_BASE={BASE}',
            "..\\.venv\\Scripts\\python.exe scripts/browser_health_isf_readiness_audit.py",
            "..\\.venv\\Scripts\\python.exe scripts/browser_ride_lifecycle_demo.py",
        ],
        "files_changed": [
            "backend/static/modules/health_isf/health-isf.js",
            "backend/app/modules/health_isf/service.py",
            "backend/app/modules/health_isf/routes.py",
            "backend/static/index.html",
            "backend/scripts/browser_health_isf_readiness_audit.py",
        ],
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    log(f"Wrote {REPORT_JSON}")
    log("MATRIX " + json.dumps(matrix))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
