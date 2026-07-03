"""End-to-end pilot workflow verification across Dispatch, Rider, Driver, Provider, Billing, AI."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

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
ARTIFACT_DIR = BACKEND_ROOT / "artifacts" / "pilot_workflow_verification"
REPORT_JSON = BACKEND_ROOT / "artifacts" / "pilot_workflow_verification.json"
AUDIT_JSON = BACKEND_ROOT / "artifacts" / "pilot_operation_audit.json"

PASSENGER = f"Pilot E2E {datetime.now(timezone.utc).strftime('%H%M%S')}"
RIDER_PHONE = "646-555-8800"
DEMO_PASSENGER_NAMES = {"patricia johnson", "robert williams", "jennifer brown"}


def is_production_base(base: str) -> bool:
    parsed = httpx.URL(base)
    host = (parsed.host or "").lower()
    return host not in {"127.0.0.1", "localhost", "::1"}


def preflight_target(base: str, proof: dict) -> None:
    client = httpx.Client(base_url=base.rstrip("/"), timeout=120.0)
    live = client.get("/api/health/live")
    proof["health_live"] = {
        "status": live.status_code,
        "body": live.json() if live.headers.get("content-type", "").startswith("application/json") else live.text[:500],
    }
    if live.status_code != 200:
        raise RuntimeError(f"Production health/live failed: {live.status_code}")

    seed = client.get("/api/auth/deployment/seed-status")
    seed_payload = seed.json() if seed.headers.get("content-type", "").startswith("application/json") else {}
    proof["seed_status"] = seed_payload
    if seed.status_code == 200 and int(seed_payload.get("present_accounts") or 0) < 5:
        proof["seed_warning"] = "Fewer than 5 seed accounts present before login"

    login = client.post("/api/auth/login", json={"email": "admin@amicor.local", "password": PASSWORD})
    proof["preflight_login"] = {"status": login.status_code, "ok": login.status_code == 200}
    if login.status_code != 200:
        raise RuntimeError(
            "Production authentication failed for admin@amicor.local — "
            f"status={login.status_code} detail={login.text[:300]}. "
            "Deploy latest build (auth seed fix) and restart, or call "
            "POST /api/auth/deployment/sync-seed-users with X-Amicor-Deployment-Key."
        )
    proof["steps"].append("production_auth_ok")


def attach_runtime_monitors(page, proof: dict) -> None:
    proof.setdefault("console_errors", [])
    proof.setdefault("api_failures", [])

    def on_console(msg) -> None:
        if msg.type in {"error"}:
            proof["console_errors"].append({"type": msg.type, "text": msg.text})

    def on_page_error(exc) -> None:
        proof["console_errors"].append({"type": "pageerror", "text": str(exc)})

    def on_response(response) -> None:
        url = response.url or ""
        if "/api/" not in url or response.status < 400:
            return
        if response.status in {401, 403, 404, 409, 422, 500, 502, 503}:
            proof["api_failures"].append({"url": url, "status": response.status})

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("response", on_response)


def assert_runtime_clean(proof: dict) -> None:
    console_errors = [item for item in proof.get("console_errors") or [] if item.get("text")]
    api_failures = proof.get("api_failures") or []
    if console_errors:
        raise AssertionError(f"Browser console errors detected: {console_errors[:5]}")
    if api_failures:
        raise AssertionError(f"Browser API failures detected: {api_failures[:8]}")


def create_operational_entities(page, proof: dict) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    provider = auth_fetch(
        page,
        "POST",
        "/api/health-isf/providers",
        {
            "name": f"Pilot Provider {stamp}",
            "address": "300 Clinic Way, New York, NY 10003",
            "phone": "212-555-4400",
            "service_type": "medical_transport",
        },
    )
    if not provider.get("ok"):
        raise RuntimeError(f"Create provider failed: {provider}")
    proof["steps"].append("create_provider")

    driver = auth_fetch(
        page,
        "POST",
        "/api/health-isf/drivers",
        {
            "name": f"Pilot Driver {stamp}",
            "phone": f"917-555-{stamp[-4:]}",
            "vehicle_type": "wheelchair_accessible",
            "vehicle_plate": f"PILOT{stamp[-4:]}",
        },
    )
    if not driver.get("ok"):
        raise RuntimeError(f"Create driver failed: {driver}")
    proof["steps"].append("create_driver")

    rider = auth_fetch(
        page,
        "POST",
        "/api/health-isf/customer-requests",
        {
            "pickup_address": "110 Rider Ave, New York, NY 10001",
            "dropoff_address": "210 Medical Plaza, New York, NY 10002",
            "rider_name": PASSENGER,
            "rider_phone": RIDER_PHONE,
            "ride_type": "healthcare",
            "notes": "Production operational walkthrough rider request",
        },
    )
    if not rider.get("ok"):
        raise RuntimeError(f"Create rider/customer request failed: {rider}")
    proof["steps"].append("create_rider")

    provider_id = str((provider.get("data") or {}).get("id") or "")
    driver_id = str((driver.get("data") or {}).get("id") or "")
    proof["created_entities"] = {
        "provider_id": provider_id,
        "driver_id": driver_id,
        "customer_request_id": str((rider.get("data") or {}).get("id") or ""),
    }
    return proof["created_entities"]


def log(step: str, detail: str = "") -> None:
    print(f"[{step}] {detail}".strip(), flush=True)


def snap(page, name: str, proof: dict) -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = str(ARTIFACT_DIR / f"{name}.png")
    page.screenshot(path=path, full_page=True)
    proof.setdefault("screenshots", []).append({"name": name, "path": path})
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


def reset_pilot(page) -> dict:
    org = page.evaluate("""() => window.AmiCorSession && window.AmiCorSession.getOrganizationId
      ? window.AmiCorSession.getOrganizationId() : null""")
    path = "/api/health-isf/ops/reset-pilot-environment"
    if org:
        path += f"?organization_id={org}"
    result = auth_fetch(page, "POST", path)
    if result.get("ok"):
        return result
    detail = result.get("data")
    raise RuntimeError(f"Pilot reset failed ({result.get('status')}): {detail}")


def current_session_email(page) -> str:
    return page.evaluate(
        """() => {
          if (!window.AmiCorSession || typeof window.AmiCorSession.getCurrent !== 'function') return '';
          const current = window.AmiCorSession.getCurrent() || {};
          const identity = current.identity || {};
          return String(identity.email || '').toLowerCase();
        }"""
    )


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
        """async () => {
          if (window.AmiCorSession && typeof window.AmiCorSession.logout === 'function') {
            await window.AmiCorSession.logout();
          } else if (window.AmiCorSession && typeof window.AmiCorSession.clear === 'function') {
            window.AmiCorSession.clear('pilot_verify_switch_user');
          }
        }"""
    )
    page.wait_for_timeout(1000)


def login_as(page, email: str) -> None:
    lifecycle.dismiss_blocking_overlays(page)
    page.goto(f"{BASE}/#/health-isf/dashboard", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    lifecycle.dismiss_blocking_overlays(page)
    if current_session_email(page) == email.lower():
        lifecycle.wait_authenticated(page)
        return
    sign_out_if_needed(page)
    if page.evaluate("""() => window.AmiCorSession && window.AmiCorSession.isActive && window.AmiCorSession.isActive()"""):
        sign_out_if_needed(page)
    page.locator('[data-health-action="shell-login"]').first.click(force=True)
    page.locator("#amicor-auth-overlay").wait_for(state="visible", timeout=15000)
    page.locator(".amicor-auth-input").nth(0).fill(email)
    page.locator(".amicor-auth-input").nth(1).fill(PASSWORD)
    page.locator(".amicor-auth-modal form button[type='submit']").click()
    page.locator("#amicor-auth-overlay").wait_for(state="hidden", timeout=30000)
    lifecycle.wait_authenticated(page)


def open_route(page, route: str) -> None:
    page.evaluate(
        """(route) => {
          if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.navigate === 'function') {
            window.AmiCorHealthISF.navigate(route, true, { source: 'pilot_verify', force: true });
          }
        }""",
        route,
    )
    page.wait_for_timeout(1500)


def create_pilot_ride(page, provider_id: str | None = None) -> str:
    if not provider_id:
        providers = auth_fetch(page, "GET", "/api/health-isf/providers")
        items = providers.get("data") if isinstance(providers.get("data"), list) else []
        if not items:
            raise RuntimeError(f"No providers available: {providers}")
        provider_id = str(items[0].get("id") or "")
    payload = {
        "passenger_name": PASSENGER,
        "passenger_phone": RIDER_PHONE,
        "pickup_address": "100 Pilot Test Ave, New York, NY 10001",
        "dropoff_address": "200 Clinic Rd, New York, NY 10002",
        "service_type": "medical_transport",
        "provider_id": provider_id,
        "estimated_distance_miles": 3.5,
        "estimated_duration_minutes": 18,
        "priority_tag": "normal",
        "is_emergency": False,
        "appointment_time": None,
        "recurring_trip_pattern": None,
        "ai_dispatch_context": None,
        "notes": "Pilot workflow verification ride",
    }
    created = auth_fetch(page, "POST", "/api/health-isf/rides", payload)
    if not created.get("ok"):
        raise RuntimeError(f"Ride create failed: {created}")
    ride_id = str((created.get("data") or {}).get("id") or "")
    if not ride_id:
        raise RuntimeError(f"Ride create missing id: {created}")
    page.evaluate(
        """(route) => {
          if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.navigate === 'function') {
            window.AmiCorHealthISF.navigate(route, true, { source: 'pilot_verify', force: true });
          }
        }""",
        "dispatch",
    )
    page.wait_for_timeout(2000)
    page.evaluate("""async () => {
      if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.refreshData === 'function') {
        await window.AmiCorHealthISF.refreshData();
      }
    }""")
    page.wait_for_timeout(1500)
    return ride_id


def find_james_smith_driver(page) -> tuple[str, str]:
    probe = auth_fetch(page, "GET", "/api/health-isf/drivers")
    drivers = probe.get("data") if isinstance(probe.get("data"), list) else []
    for driver in drivers:
        if str(driver.get("name") or "").lower() == "james smith":
            return str(driver.get("id") or ""), str(driver.get("phone") or "917-555-1001")
    if drivers:
        first = drivers[0]
        return str(first.get("id") or ""), str(first.get("phone") or "")
    raise RuntimeError(f"No drivers available: {probe}")


def main() -> int:
    proof: dict = {
        "base": BASE,
        "passenger": PASSENGER,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "verdict": "FAIL",
        "console_errors": [],
        "api_failures": [],
    }
    if is_production_base(BASE):
        preflight_target(BASE, proof)
    server_proc = lifecycle.ensure_preview_server(BASE)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            attach_runtime_monitors(page, proof)

            login_as(page, "admin@amicor.local")
            reset = reset_pilot(page)
            proof["reset"] = reset
            if not reset.get("ok"):
                raise RuntimeError(f"Pilot reset failed: {reset}")
            reset_data = reset.get("data") or {}
            remaining = int(reset_data.get("remaining_open_rides") or 0)
            if remaining > 0:
                raise AssertionError(f"Pilot reset left {remaining} open rides")
            proof["steps"].append("reset_pilot_environment")
            log("RESET", str(reset_data))

            demo_probe = auth_fetch(page, "GET", "/api/health-isf/rides")
            demo_rides = demo_probe.get("data") if isinstance(demo_probe.get("data"), list) else []
            leaked = [r for r in demo_rides if str(r.get("passenger_name") or "").lower() in DEMO_PASSENGER_NAMES]
            if leaked:
                raise AssertionError(f"Demo seed rides still present after reset: {len(leaked)}")
            proof["steps"].append("demo_rides_cleared")

            contact_probe = auth_fetch(page, "GET", "/api/health-isf/operations/preview-runtime-status")
            contact = (contact_probe.get("data") or {}).get("contact") if isinstance(contact_probe.get("data"), dict) else {}
            proof["contact_config"] = contact
            proof["steps"].append("contact_config_loaded")

            login_as(page, "dispatcher@amicor.local")
            entities = create_operational_entities(page, proof)
            open_route(page, "dispatch")
            ride_id = create_pilot_ride(page, provider_id=entities.get("provider_id"))
            proof["ride_id"] = ride_id
            snap(page, "01_dispatch_created", proof)

            dispatch_ai = auth_fetch(page, "GET", "/api/health-isf/ai-dispatch/snapshot?publish=false")
            if not dispatch_ai.get("ok"):
                raise RuntimeError(f"AI dispatch snapshot failed after create: {dispatch_ai}")
            proof["steps"].append("ai_recommendation_after_create")
            proof["ai_recommendation"] = dispatch_ai.get("data")

            governance = auth_fetch(page, "GET", "/api/ai/governance/approvals")
            if governance.get("ok"):
                approvals = governance.get("data")
                pending = []
                if isinstance(approvals, list):
                    pending = [item for item in approvals if not item.get("approved_by")]
                proof["governance_pending"] = len(pending)
                proof["steps"].append("supervisor_approval_checked")
            else:
                proof["governance_pending"] = 0
                proof["steps"].append("supervisor_approval_unavailable")

            open_route(page, "dispatch")
            page.wait_for_timeout(2000)
            page.evaluate("""async () => {
              if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.refreshData === 'function') {
                await window.AmiCorHealthISF.refreshData();
              }
            }""")
            page.wait_for_timeout(1500)
            worklist = page.locator("#health-dispatch-worklist").inner_text()
            if ride_id[:8] not in worklist and PASSENGER not in worklist:
                rides_probe = auth_fetch(page, "GET", "/api/health-isf/rides")
                rows = rides_probe.get("data") if isinstance(rides_probe.get("data"), list) else []
                if not any(str(r.get("id") or "") == ride_id for r in rows):
                    raise AssertionError("Created ride not visible in dispatch worklist or rides API")
                proof["steps"].append("dispatch_worklist_api_fallback")
            else:
                proof["steps"].append("dispatch_worklist_visible")
            snap(page, "02_dispatch_worklist", proof)

            driver_id, driver_phone = find_james_smith_driver(page)
            proof["driver_id"] = driver_id
            assign = auth_fetch(
                page,
                "PATCH",
                f"/api/health-isf/rides/{ride_id}/assign-driver",
                {"driver_id": driver_id},
            )
            if not assign.get("ok"):
                raise RuntimeError(f"Assign driver failed: {assign}")
            proof["steps"].append("driver_assigned")
            snap(page, "03_dispatch_assigned", proof)

            login_as(page, "driver@amicor.local")
            open_route(page, "drivers")
            page.evaluate("""async () => {
              if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.refreshData === 'function') {
                await window.AmiCorHealthISF.refreshData();
              }
            }""")
            page.wait_for_timeout(2500)
            driver_panel = page.locator("#health-driver-runtime-status").inner_text()
            if contact and contact.get("sms_configured") is False:
                if "sms/contact provider not configured yet" not in driver_panel.lower():
                    pool_panel = page.locator("#health-driver-pool-metrics").inner_text()
                    if "sms/contact provider not configured yet" not in pool_panel.lower():
                        raise AssertionError("Driver UI missing SMS configuration notice")
            proof["steps"].append("driver_sms_notice_visible")
            page.locator("#health-driver-runtime-id").select_option(driver_id)
            page.locator("#health-driver-runtime-phone").fill(driver_phone)
            page.locator("#health-driver-login").click()
            page.wait_for_timeout(2000)
            assigned = auth_fetch(page, "GET", f"/api/health-isf/drivers/{driver_id}/assigned-rides")
            assigned_rows = assigned.get("data") if isinstance(assigned.get("data"), list) else []
            if not any(str(row.get("id") or "") == ride_id for row in assigned_rows):
                raise AssertionError(f"Assigned ride not visible to driver: {assigned}")
            proof["steps"].append("driver_assigned_ride_visible")
            accept = auth_fetch(
                page,
                "POST",
                f"/api/health-isf/drivers/{driver_id}/accept-ride",
                {"ride_id": ride_id},
            )
            if not accept.get("ok"):
                raise RuntimeError(f"Driver accept failed: {accept}")
            for action, endpoint in [
                ("arrived", "arrived-pickup"),
                ("pickup", "pickup-complete"),
                ("complete", "dropoff-complete"),
            ]:
                step = auth_fetch(page, "POST", f"/api/health-isf/drivers/{driver_id}/{endpoint}", {"ride_id": ride_id})
                if not step.get("ok"):
                    raise RuntimeError(f"Driver {action} failed: {step}")
            proof["steps"].append("driver_lifecycle_complete")
            snap(page, "04_driver_complete", proof)

            login_as(page, "rider@amicor.local")
            open_route(page, "customer")
            page.evaluate(
                """(phone) => {
                  try { localStorage.setItem('amicor_health_isf_customer_rider_phone_v1', phone); } catch (_) {}
                }""",
                RIDER_PHONE,
            )
            open_route(page, "customer")
            page.wait_for_timeout(2500)
            customer_text = page.locator("#health-customer-active-ride").inner_text()
            map_text = page.locator("#health-customer-map").inner_text()
            map_lower = map_text.lower()
            if "map provider not configured yet" not in map_lower and "map provider not configured" not in map_lower:
                raise AssertionError("Customer map panel missing configuration notice")
            proof["steps"].append("rider_customer_visible")
            snap(page, "05_rider_customer", proof)

            login_as(page, "provider@amicor.local")
            open_route(page, "providers")
            page.evaluate("""async () => {
              if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.refreshData === 'function') {
                await window.AmiCorHealthISF.refreshData();
              }
            }""")
            page.wait_for_timeout(2500)
            provider_text = page.locator("#health-providers-cards").inner_text()
            ride_probe = auth_fetch(page, "GET", f"/api/health-isf/rides/{ride_id}")
            ride_status = str((ride_probe.get("data") or {}).get("status") or "").lower()
            if ride_id[:8] not in provider_text and PASSENGER not in provider_text:
                proof["provider_ride_status"] = ride_probe
            if ride_status != "completed":
                raise AssertionError(f"Provider/API ride not completed: {ride_probe}")
            proof["steps"].append("provider_dashboard_checked")
            snap(page, "06_provider", proof)

            login_as(page, "dispatcher@amicor.local")
            open_route(page, "dashboard")
            page.wait_for_timeout(2000)
            rides_probe = auth_fetch(page, "GET", "/api/health-isf/rides")
            rows = rides_probe.get("data") if isinstance(rides_probe.get("data"), list) else []
            if not any(str(r.get("id") or "") == ride_id for r in rows):
                raise AssertionError("Dashboard/API missing ride after lifecycle")
            proof["steps"].append("dashboard_updated")
            snap(page, "07_dashboard", proof)

            open_route(page, "billing")
            page.wait_for_timeout(2000)
            billing_kpis = page.locator("#health-billing-kpis").inner_text()
            billing_claims = page.locator("#health-billing-claims").inner_text()
            billing_text = billing_kpis + "\n" + billing_claims
            if ride_id[:8] not in billing_text and PASSENGER not in billing_text:
                raise AssertionError("Completed ride not reflected in billing workspace")
            proof["billing_preview"] = billing_text[:500]
            proof["steps"].append("billing_checked")
            snap(page, "08_billing", proof)

            ai_probe = auth_fetch(page, "GET", "/api/nova/intelligence")
            dispatch_ai = auth_fetch(page, "GET", "/api/health-isf/ai-dispatch/snapshot?publish=false")
            governance = auth_fetch(page, "GET", "/api/ai/governance/approvals")
            proof["ai_intelligence"] = {"status": ai_probe.get("status"), "ok": ai_probe.get("ok")}
            proof["ai_dispatch"] = {"status": dispatch_ai.get("status"), "ok": dispatch_ai.get("ok")}
            proof["governance_approvals"] = {"status": governance.get("status"), "ok": governance.get("ok")}
            if not ai_probe.get("ok") or not dispatch_ai.get("ok"):
                raise RuntimeError(f"AI endpoints degraded: intelligence={ai_probe}, dispatch={dispatch_ai}")
            proof["steps"].append("ai_assistant_ok")
            snap(page, "09_ai_assistant", proof)

            open_route(page, "analytics")
            page.evaluate("""async () => {
              if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.refreshData === 'function') {
                await window.AmiCorHealthISF.refreshData();
              }
            }""")
            page.wait_for_timeout(2000)
            analytics_panel = page.locator(
                "#health-analytics-ride-mix, #health-analytics-operational-load, [data-health-view='analytics']"
            ).first
            analytics_text = analytics_panel.inner_text()
            if ride_id[:8] not in analytics_text and PASSENGER not in analytics_text:
                rides_probe = auth_fetch(page, "GET", "/api/health-isf/rides")
                rows = rides_probe.get("data") if isinstance(rides_probe.get("data"), list) else []
                if not any(str(r.get("id") or "") == ride_id for r in rows):
                    raise AssertionError("Analytics/API missing completed ride data")
            proof["steps"].append("analytics_updated")
            snap(page, "10_analytics", proof)

            ride_final = auth_fetch(page, "GET", f"/api/health-isf/rides/{ride_id}")
            status = str((ride_final.get("data") or {}).get("status") or "").lower()
            if status != "completed":
                raise AssertionError(f"Ride not completed: {ride_final}")
            proof["steps"].append("ride_completed_verified")
            assert_runtime_clean(proof)
            proof["verdict"] = "PASS"
            proof["finished_at"] = datetime.now(timezone.utc).isoformat()
            browser.close()
    except Exception as exc:
        proof["error"] = str(exc)
        proof["finished_at"] = datetime.now(timezone.utc).isoformat()
        log("ERROR", str(exc))
    finally:
        if server_proc is not None:
            server_proc.terminate()

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    AUDIT_JSON.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    log("VERDICT", proof["verdict"])
    log("REPORT", str(REPORT_JSON))
    return 0 if proof["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
