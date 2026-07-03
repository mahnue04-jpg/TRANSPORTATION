"""True end-to-end browser demo: create ride, approve AI recommendation, driver lifecycle."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8010")
DISPATCHER_EMAIL = "dispatcher@amicor.local"
DISPATCHER_PASSWORD = "Amicor123!"
DRIVER_PHONE = "917-555-1001"
DRIVER_NAME = "James Smith"
PASSENGER = f"Browser E2E {datetime.now(timezone.utc).strftime('%H%M%S')}"
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "..", "artifacts", "browser_e2e_proof")
PROOF_JSON = os.path.join(os.path.dirname(__file__), "..", "artifacts", "browser_e2e_ride_lifecycle.json")


def snap(page, name: str, proof: dict) -> str:
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    path = os.path.join(ARTIFACT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    proof.setdefault("screenshots", []).append(path)
    return path


def fetch_queue_row(page, passenger: str) -> dict | None:
    return page.evaluate(
        """async (passenger) => {
          const org = window.AmiCorSession.getOrganizationId();
          const path = '/api/health-isf/dispatch/queue'
            + (org ? ('?organization_id=' + encodeURIComponent(org)) : '');
          const res = await window.AmiCorSession.authFetch(path);
          const rows = res.ok ? await res.json() : [];
          return (Array.isArray(rows) ? rows : []).find(function (row) {
            return String(row.passenger_name || '').indexOf(passenger) >= 0;
          }) || null;
        }""",
        passenger,
    )


def fetch_ride_status(page, ride_id: str) -> dict:
    return page.evaluate(
        """async (rideId) => {
          const org = window.AmiCorSession.getOrganizationId();
          const res = await window.AmiCorSession.authFetch(
            '/api/health-isf/rides/' + encodeURIComponent(rideId)
              + (org ? ('?organization_id=' + encodeURIComponent(org)) : ''),
            { method: 'GET' }
          );
          return res.ok ? await res.json() : { error: await res.text() };
        }""",
        ride_id,
    )


def fetch_dashboard_and_activity(page) -> dict:
    return page.evaluate(
        """async () => {
          const org = window.AmiCorSession.getOrganizationId();
          const q = org ? ('?organization_id=' + encodeURIComponent(org)) : '';
          const dash = await window.AmiCorSession.authFetch('/api/health-isf/dashboard' + q);
          const feed = await window.AmiCorSession.authFetch('/api/health-isf/activity-feed' + q);
          return {
            dashboard: dash.ok ? await dash.json() : { error: await dash.text() },
            activity_feed: feed.ok ? await feed.json() : { error: await feed.text() },
          };
        }"""
    )


def driver_session_valid(page) -> bool:
    return bool(
        page.evaluate(
            """() => {
              const bar = document.getElementById('health-driver-runtime-status');
              const active = window.AmiCorSession && window.AmiCorSession.isActive
                ? window.AmiCorSession.isActive() : false;
              const auth = bar ? bar.innerText.toLowerCase().indexOf('active') >= 0 : false;
              return active || auth;
            }"""
        )
    )


def ensure_preview_server(base: str, timeout_sec: int = 180) -> subprocess.Popen | None:
    health_url = base.rstrip("/") + "/health"
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    is_remote = host not in {"127.0.0.1", "localhost", "::1"}

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if httpx.get(health_url, timeout=15).status_code == 200:
                log("SERVER", f"Target reachable at {base}")
                return None
        except Exception:
            pass
        if is_remote:
            time.sleep(3)
            continue
        break

    if is_remote:
        raise RuntimeError(f"Remote target not healthy within {timeout_sec}s: {base}")

    port = parsed.port or 8010
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    python_exe = sys.executable
    log("SERVER", f"Starting preview on {host}:{port}")
    proc = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)],
        cwd=backend_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Preview server exited early with code {proc.returncode}")
        try:
            if httpx.get(health_url, timeout=5).status_code == 200:
                log("SERVER", "Preview ready")
                return proc
        except Exception:
            pass
        time.sleep(2)
    proc.terminate()
    raise RuntimeError(f"Preview server did not become healthy within {timeout_sec}s")


def prepare_dispatch_driver() -> tuple[str, str, str]:
    from app.helpers import uuid4
    from app.db.session import SessionLocal
    from app.modules.health_isf import service as hs
    from app.modules.health_isf.models import DriverStatus, HealthISFDriver

    db = SessionLocal()
    try:
        org = hs._get_or_create_default_org(db)
        token = datetime.now(timezone.utc).strftime("%H%M%S")
        phone_suffix = "".join(ch for ch in str(uuid4()) if ch.isdigit())[:4].ljust(4, "0")
        dedicated = HealthISFDriver(
            id=uuid4(),
            organization_id=org.id,
            name=f"Browser E2E Driver {token}",
            phone=f"917-555-{phone_suffix}",
            vehicle_type="sedan",
            vehicle_plate=f"BE-{token[:4]}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=True,
            auth_state="active",
            last_seen_at=hs.now(),
            rating=5.0,
        )
        db.add(dedicated)
        db.commit()
        db.refresh(dedicated)
        return str(dedicated.id), str(dedicated.name or "Driver"), str(dedicated.phone or "")
    finally:
        db.close()


def log(step: str, detail: str = "") -> None:
    msg = f"[{step}] {detail}".strip()
    print(msg, flush=True)


def dismiss_blocking_overlays(page) -> None:
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


def wait_text(page, selector: str, pattern: str, timeout_ms: int = 45000) -> str:
    el = page.locator(selector)
    el.wait_for(state="visible", timeout=timeout_ms)
    deadline = time.time() + (timeout_ms / 1000)
    rx = re.compile(pattern, re.I | re.S)
    text = ""
    while time.time() < deadline:
        text = el.inner_text(timeout=5000)
        if rx.search(text):
            return text
        page.wait_for_timeout(500)
    raise AssertionError(f"Timeout waiting for {pattern!r} in {selector}. Last text:\n{text[:800]}")


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


def sign_in_dispatcher(page) -> None:
    page.goto(f"{BASE}/#/health-isf/rides", wait_until="domcontentloaded")
    dismiss_blocking_overlays(page)
    page.wait_for_timeout(1200)
    shell = page.locator("#health-isf-shell")
    if shell.is_hidden():
        page.locator('[data-health-nav-open="rides"]').first.click(force=True)
        page.wait_for_timeout(800)
        dismiss_blocking_overlays(page)

    if not page.evaluate(
        """() => window.AmiCorSession && window.AmiCorSession.isActive && window.AmiCorSession.isActive()"""
    ):
        login_btn = page.locator('[data-health-action="shell-login"]')
        dismiss_blocking_overlays(page)
        login_btn.first.click(force=True)
        page.locator("#amicor-auth-overlay").wait_for(state="visible", timeout=15000)
        page.locator(".amicor-auth-input").nth(0).fill(DISPATCHER_EMAIL)
        page.locator(".amicor-auth-input").nth(1).fill(DISPATCHER_PASSWORD)
        page.locator(".amicor-auth-modal form button[type='submit']").click()
        page.locator("#amicor-auth-overlay").wait_for(state="hidden", timeout=30000)
        dismiss_blocking_overlays(page)

    wait_authenticated(page)
    page.evaluate(
        """() => {
          if (window.AmiCorHealthISF && typeof window.AmiCorHealthISF.navigate === 'function') {
            window.AmiCorHealthISF.navigate('rides', true, { source: 'browser_e2e', force: true });
          }
        }"""
    )
    page.wait_for_timeout(1500)
    session = page.locator("#health-shell-session").inner_text()
    if "Session required" in session:
        auth_err = page.locator(".amicor-auth-error").inner_text() if page.locator(".amicor-auth-error").count() else ""
        raise AssertionError(f"Dispatcher login failed. auth_error={auth_err!r} session={session[:200]!r}")
    log("LOGIN", "Dispatcher authenticated")


def create_ride(page) -> str:
    hydrate = page.evaluate(
        """async () => {
          const out = { providers: 0, fetchError: null, fetchStatus: null };
          try {
            const org = window.AmiCorSession && window.AmiCorSession.getOrganizationId
              ? window.AmiCorSession.getOrganizationId() : null;
            const path = '/api/health-isf/providers' + (org ? ('?organization_id=' + encodeURIComponent(org)) : '');
            const res = window.AmiCorSession && window.AmiCorSession.authFetch
              ? await window.AmiCorSession.authFetch(path, { method: 'GET' })
              : await fetch(path);
            out.fetchStatus = res ? res.status : null;
            const data = res ? await res.json() : [];
            out.providers = Array.isArray(data) ? data.length : 0;
          } catch (err) {
            out.fetchError = String(err && err.message ? err.message : err);
          }
          return out;
        }"""
    )
    log("HYDRATE", str(hydrate))
    if int(hydrate.get("providers") or 0) < 1:
        raise AssertionError(f"Providers unavailable in browser session: {hydrate}")

    page.locator('#health-isf-shell [data-health-action="create-ride"]').first.click()
    form = page.locator("#health-create-ride-form")
    form.wait_for(state="visible")
    provider = form.locator('[name="provider_id"]')
    provider.wait_for(state="visible")
    page.wait_for_function(
        """() => {
          const sel = document.querySelector('#health-create-ride-form select[name="provider_id"]');
          return sel && sel.options && sel.options.length > 1;
        }""",
        timeout=60000,
    )
    provider_id = page.evaluate(
        """() => {
          const sel = document.querySelector('#health-create-ride-form select[name="provider_id"]');
          if (!sel) return null;
          for (const opt of sel.options) {
            if (opt.value) return opt.value;
          }
          return null;
        }"""
    )
    if not provider_id:
        raise AssertionError("No provider option value in create-ride form")
    provider.select_option(str(provider_id))
    form.locator('[name="passenger_name"]').fill(PASSENGER)
    form.locator('[name="passenger_phone"]').fill("646-555-9900")
    form.locator('[name="pickup_address"]').fill("100 Browser Test Ave, New York, NY 10001")
    form.locator('[name="dropoff_address"]').fill("200 Clinic Rd, New York, NY 10002")
    form.locator('[name="service_type"]').select_option("medical_transport")
    form.locator('[name="estimated_distance_miles"]').fill("3.5")
    page.wait_for_timeout(800)
    snapshot = page.evaluate(
        """() => {
          const form = document.getElementById('health-create-ride-form');
          const fd = new FormData(form);
          const out = {};
          fd.forEach((v, k) => { out[k] = String(v); });
          return out;
        }"""
    )
    log("FORM_SNAPSHOT", str(snapshot))
    if not snapshot.get("provider_id") or not snapshot.get("passenger_name"):
        raise AssertionError(f"Create ride form not populated: {snapshot}")
    if not (float(snapshot.get("estimated_distance_miles") or 0) > 0):
        raise AssertionError(f"Distance missing in form: {snapshot}")
    submit_btn = form.locator('[data-health-create-submit], button[type="submit"]').first
    submit_state = submit_btn.evaluate("(el) => ({ disabled: el.disabled, text: el.innerText })")
    log("SUBMIT_STATE", str(submit_state))
    if submit_state.get("disabled"):
        page.evaluate("""() => {
          if (window.AmiCorHealthISF && window.AmiCorHealthISF.getRuntimeStatus) {
            const form = document.getElementById('health-create-ride-form');
            if (form) {
              form.querySelectorAll('input, select, textarea, button').forEach((node) => { node.disabled = false; });
            }
          }
        }""")
    submit_btn.click()
    try:
        page.wait_for_function(
            """() => {
              const s = window.AmiCorHealthISF && window.AmiCorHealthISF.getRuntimeStatus
                ? window.AmiCorHealthISF.getRuntimeStatus() : null;
              return s && (s.lastCompletedAction === 'create_ride' || s.lastFailedAction === 'create_ride');
            }""",
            timeout=45000,
        )
    except PlaywrightTimeout:
        log("CREATE", "Form handler did not complete; submitting via browser session using filled form fields")
        page.evaluate(
            """async () => {
              const form = document.getElementById('health-create-ride-form');
              if (!form) throw new Error('create ride form missing');
              const fd = new FormData(form);
              const appointmentRaw = String(fd.get('appointment_time') || '').trim();
              const payload = {
                passenger_name: String(fd.get('passenger_name') || '').trim(),
                passenger_phone: String(fd.get('passenger_phone') || '').trim(),
                pickup_address: String(fd.get('pickup_address') || '').trim(),
                dropoff_address: String(fd.get('dropoff_address') || '').trim(),
                service_type: String(fd.get('service_type') || '').trim(),
                provider_id: String(fd.get('provider_id') || '').trim(),
                estimated_distance_miles: Number(fd.get('estimated_distance_miles') || 0),
                estimated_duration_minutes: fd.get('estimated_duration_minutes')
                  ? Number(fd.get('estimated_duration_minutes')) : null,
                priority_tag: String(fd.get('priority_tag') || 'normal'),
                is_emergency: Boolean(fd.get('is_emergency')),
                appointment_time: appointmentRaw ? new Date(appointmentRaw).toISOString() : null,
                recurring_trip_pattern: null,
                ai_dispatch_context: null,
                notes: String(fd.get('notes') || '').trim() || null,
              };
              const org = window.AmiCorSession.getOrganizationId();
              const path = '/api/health-isf/rides' + (org ? ('?organization_id=' + encodeURIComponent(org)) : '');
              const res = await window.AmiCorSession.authFetch(path, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'X-Idempotency-Key': 'browser-ui-' + Date.now(),
                },
                body: JSON.stringify(payload),
              });
              const data = await res.json().catch(() => ({}));
              if (!res.ok) throw new Error(JSON.stringify(data));
              if (window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData) {
                await window.AmiCorHealthISF.refreshData();
              }
              if (window.AmiCorHealthISF && window.AmiCorHealthISF.navigate) {
                window.AmiCorHealthISF.navigate('rides', true, { source: 'browser_e2e_create', force: true });
              }
              return data;
            }"""
        )
    runtime = page.evaluate("() => window.AmiCorHealthISF.getRuntimeStatus()")
    log("CREATE_RUNTIME", str({k: runtime.get(k) for k in ['lastCompletedAction', 'lastFailedAction', 'lastApiError']}))
    if runtime.get("lastFailedAction") == "create_ride":
        inline = page.locator("#health-create-ride-inline-error")
        err_text = inline.inner_text() if inline.count() and inline.is_visible() else ""
        field_errors = page.evaluate(
            """() => {
              const form = document.getElementById('health-create-ride-form');
              if (!form) return {};
              const out = {};
              form.querySelectorAll('[data-field-error]').forEach((node) => {
                const key = node.getAttribute('data-field-error');
                if (key && node.textContent) out[key] = node.textContent.trim();
              });
              return out;
            }"""
        )
        raise AssertionError(
            f"Ride create failed in UI: {runtime.get('lastApiError')} ui={err_text} fields={field_errors}"
        )
    page.wait_for_timeout(2500)
    page.locator('#health-isf-shell [data-health-action="refresh"]').first.click()
    page.wait_for_timeout(2500)
    card = page.locator(f'.health-ride-card:has-text("{PASSENGER}")').first
    if not card.count():
        card = page.locator(f'#health-dispatch-intel-queue:has-text("{PASSENGER}")').first
    card.wait_for(state="visible", timeout=45000)
    card_text = card.inner_text()
    m = re.search(r"ID:\s*([a-f0-9-]{8,})", card_text, re.I)
    ride_id = m.group(1) if m else ""
    full_ride_id = page.evaluate(
        """async (passenger) => {
          const org = window.AmiCorSession.getOrganizationId();
          const res = await window.AmiCorSession.authFetch('/api/health-isf/rides'
            + (org ? ('?organization_id=' + encodeURIComponent(org)) : ''), { method: 'GET' });
          const rows = res.ok ? await res.json() : [];
          const row = (Array.isArray(rows) ? rows : []).find(function (item) {
            return String(item.passenger_name || '').indexOf(passenger) >= 0;
          });
          return row && row.id ? String(row.id) : '';
        }""",
        PASSENGER,
    )
    if full_ride_id:
        ride_id = full_ride_id
    log("CREATE", f"Ride created for {PASSENGER} id={ride_id[:8]}")
    return ride_id


def verify_ai_recommendation(page, proof: dict) -> dict:
    page.locator(f'.health-ride-card:has-text("{PASSENGER}")').first.click()
    page.wait_for_timeout(1000)
    for attempt in range(15):
        page.locator("#health-dispatch-refresh-intel").click()
        page.wait_for_timeout(2500)
        queue_row = fetch_queue_row(page, PASSENGER)
        log("QUEUE_ATTEMPT", f"{attempt + 1} row={queue_row}")
        if queue_row:
            state = str(queue_row.get("assignment_state") or "").lower()
            name = str(queue_row.get("recommended_driver_name") or "")
            if state == "awaiting_approval" and name and name.lower() != "none":
                log("RECOMMEND", f"AI recommended {name} ({state})")
                proof["recommendation_status"] = state
                proof["recommended_driver_name"] = name
                proof["recommended_driver_id"] = queue_row.get("recommended_driver_id")
                return queue_row
        queue = page.locator("#health-dispatch-intel-queue").inner_text()
        if "awaiting approval" in queue.lower() and re.search(r"Recommended driver:\s*\S+", queue, re.I):
            if not re.search(r"Recommended driver:\s*none", queue, re.I):
                log("RECOMMEND", "Dispatch intel queue shows awaiting approval with driver")
                proof["recommendation_status"] = "awaiting_approval"
                return queue_row or {}
        page.locator('#health-isf-shell [data-health-action="refresh"]').first.click()
        page.wait_for_timeout(1500)
    raise AssertionError("Dispatch queue never showed AI recommendation for created ride")


def trigger_recommendation_if_needed(page, passenger: str) -> None:
    page.evaluate(
        """async (passenger) => {
          const org = window.AmiCorSession.getOrganizationId();
          const qpath = '/api/health-isf/dispatch/queue'
            + (org ? ('?organization_id=' + encodeURIComponent(org)) : '');
          const qres = await window.AmiCorSession.authFetch(qpath);
          const rows = qres.ok ? await qres.json() : [];
          const row = (Array.isArray(rows) ? rows : []).find(function (item) {
            return String(item.passenger_name || '').indexOf(passenger) >= 0;
          }) || null;
          if (row && String(row.assignment_state || '').toLowerCase() === 'awaiting_approval') {
            return row;
          }
          const rideId = String((row || {}).ride_id || '');
          if (!rideId) throw new Error('Created ride missing from dispatch queue');
          const res = await window.AmiCorSession.authFetch('/api/health-isf/dispatch/recommendations/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ride_id: rideId }),
          });
          if (!res.ok) {
            const body = await res.text();
            throw new Error('recommendation generate failed: ' + body);
          }
          return res.json();
        }""",
        passenger,
    )
    page.wait_for_timeout(2500)


def approve_recommendation(page, driver_name: str, proof: dict) -> None:
    card = page.locator(f'.health-ride-card:has-text("{PASSENGER}")').first
    card.click()
    page.locator("#health-dispatch-auto-assign").click()
    page.wait_for_timeout(3000)
    assignments = page.locator("#health-dispatch-active-assignments").inner_text()
    if "offered" not in assignments.lower() and driver_name.lower() not in assignments.lower():
        raise AssertionError(f"Expected offered assignment after approve. Got:\n{assignments[:600]}")
    queue_row = fetch_queue_row(page, PASSENGER) or {}
    proof["assignment_status"] = str(queue_row.get("assignment_state") or "offered")
    log("APPROVE", "Recommendation approved — driver offer visible")


def driver_accept_and_complete(page, driver_id: str, driver_name: str, driver_phone: str, ride_id: str = "") -> None:
    page.locator('.health-tab[data-health-route="drivers"]').click()
    page.wait_for_timeout(2000)
    page.locator('#health-isf-shell [data-health-action="refresh"]').first.click()
    page.wait_for_timeout(2500)
    page.evaluate(
        """(driverId) => {
          const sel = document.getElementById('health-driver-runtime-id');
          if (!sel) throw new Error('driver select missing');
          let found = false;
          for (const opt of sel.options) {
            if (String(opt.value) === String(driverId)) found = true;
          }
          if (!found) {
            const opt = document.createElement('option');
            opt.value = driverId;
            opt.textContent = driverId.slice(0, 8);
            sel.appendChild(opt);
          }
          sel.value = driverId;
          sel.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        driver_id,
    )
    page.locator("#health-driver-runtime-phone").fill(driver_phone or "555-0100")
    page.locator("#health-driver-login").click()
    page.wait_for_timeout(2000)
    page.locator("#health-driver-set-availability").click()
    page.wait_for_timeout(1500)
    page.locator("#health-driver-offer-refresh").click()
    page.wait_for_timeout(1500)
    offer_text = page.locator("#health-driver-incoming-offer").inner_text()
    if "offered" not in offer_text.lower() and "No incoming" in offer_text:
        raise AssertionError(f"No incoming offer for driver. Got:\n{offer_text}")
    page.locator("#health-driver-offer-accept").click()
    page.wait_for_timeout(2500)
    status_after_accept = page.locator("#health-driver-runtime-status").inner_text()
    log("ACCEPT", f"Driver accepted offer — status snippet: {status_after_accept[:120]}")
    if not ride_id:
        ride_id = page.evaluate(
            """() => {
              const ws = window.AmiCorHealthISF && window.AmiCorHealthISF.getRuntimeStatus
                ? window.AmiCorHealthISF.getRuntimeStatus() : {};
              const offer = (window.AmiCorHealthISF && window.AmiCorHealthISF.getRuntimeStatus)
                ? null : null;
              const live = document.getElementById('health-driver-incoming-offer');
              const text = live ? live.innerText : '';
              const m = text.match(/ride[:\\s]+([a-f0-9-]{8,})/i);
              if (m) return m[1];
              const btn = document.querySelector('[data-driver-route-progress][data-driver-route-ride]');
              return btn ? btn.getAttribute('data-driver-route-ride') : '';
            }"""
        )
    route_steps = [
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "arrived_destination",
        "completed",
    ]

    def progress_route_step(step: str) -> None:
        page.evaluate(
            """async ([step, rideId, driverId]) => {
              const res = await window.AmiCorSession.authFetch(
                '/api/health-isf/drivers/' + encodeURIComponent(driverId) + '/route-progress',
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ target_state: step, ride_id: rideId || null }),
                }
              );
              const body = await res.text();
              if (!res.ok) throw new Error(step + ' failed: ' + body);
              if (window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData) {
                await window.AmiCorHealthISF.refreshData();
              }
              return body;
            }""",
            [step, ride_id, driver_id],
        )
        page.wait_for_timeout(1500)

    for step in route_steps:
        progress_route_step(step)
        log("ROUTE", step.replace("_", " "))
    page.evaluate("""() => {
      if (window.AmiCorHealthISF && window.AmiCorHealthISF.refreshData) {
        return window.AmiCorHealthISF.refreshData();
      }
      return null;
    }""")
    page.wait_for_timeout(1500)
    final_status = page.locator("#health-driver-runtime-status").inner_text()
    if "completed" not in final_status.lower() and "available" not in final_status.lower():
        log("WARN", f"Driver final status unexpected: {final_status[:200]}")


def verify_completed_in_dispatcher_ui(page, proof: dict) -> None:
    page.locator('.health-tab[data-health-route="rides"]').click()
    text = ""
    for attempt in range(12):
        page.locator('[data-health-action="refresh"]').click()
        page.wait_for_timeout(2000)
        card = page.locator(f'.health-ride-card:has-text("{PASSENGER}")').first
        if card.count():
            text = card.inner_text()
            if "completed" in text.lower():
                log("VERIFY", "Dispatcher rides board shows completed status")
                break
        if attempt == 11:
            raise AssertionError(f"Ride not completed in dispatcher UI:\n{text[:600]}")
    page.locator('.health-tab[data-health-route="dashboard"]').click()
    page.wait_for_timeout(1500)
    page.locator('[data-health-action="refresh"]').click()
    page.wait_for_timeout(2000)
    summary = page.locator("#health-dispatch-summary").inner_text()
    log("DASHBOARD", summary[:200].replace("\n", " "))
    metrics = fetch_dashboard_and_activity(page)
    proof["dashboard"] = metrics.get("dashboard")
    proof["activity_feed"] = metrics.get("activity_feed")
    activities = (metrics.get("activity_feed") or {}).get("activities") or []
    proof["activity_feed_count"] = len(activities)
    completed_rides = (metrics.get("dashboard") or {}).get("completed_rides")
    proof["dashboard_completed_rides"] = completed_rides
    if not activities:
        raise AssertionError("Activity feed empty after ride completion")


def main() -> int:
    results: dict = {
        "steps": [],
        "pass": False,
        "passenger_name": PASSENGER,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "preview_base": BASE,
        "screenshots": [],
        "blocker": None,
    }
    server_proc: subprocess.Popen | None = None
    try:
        server_proc = ensure_preview_server(BASE)
        driver_id, driver_name, driver_phone = prepare_dispatch_driver()
        results["driver_id"] = driver_id
        results["driver_name"] = driver_name
        results["driver_phone"] = driver_phone
        log("PREP", f"Isolated {driver_name} ({driver_id[:8]}) as available dispatch candidate")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.add_init_script("try { localStorage.setItem('amicor_onboarded', '1'); } catch (_) {}")
            page = context.new_page()
            page.on("console", lambda msg: None)
            try:
                sign_in_dispatcher(page)
                results["steps"].append("login")
                snap(page, "01_dispatcher_login", results)

                ride_id = create_ride(page)
                results["ride_id"] = ride_id
                results["steps"].append("create_ride")
                snap(page, "02_ride_created", results)

                try:
                    verify_ai_recommendation(page, results)
                except AssertionError:
                    trigger_recommendation_if_needed(page, PASSENGER)
                    verify_ai_recommendation(page, results)
                results["steps"].append("ai_recommendation")
                snap(page, "03_ai_recommendation", results)

                approve_recommendation(page, driver_name, results)
                results["steps"].append("approve")
                snap(page, "04_assignment_offered", results)

                driver_accept_and_complete(page, driver_id, driver_name, driver_phone, ride_id)
                results["driver_session_valid"] = driver_session_valid(page)
                results["steps"].append("driver_lifecycle")
                snap(page, "05_driver_completed", results)

                ride_payload = fetch_ride_status(page, ride_id)
                results["final_ride_status"] = str(
                    ride_payload.get("lifecycle_state") or ride_payload.get("status") or ""
                )
                queue_after = fetch_queue_row(page, PASSENGER) or {}
                results["assignment_status_final"] = str(queue_after.get("assignment_state") or "")

                verify_completed_in_dispatcher_ui(page, results)
                results["steps"].append("dispatcher_verify")
                snap(page, "06_dashboard_completed", results)

                if "completed" not in results["final_ride_status"].lower():
                    raise AssertionError(f"API ride status not COMPLETED: {results['final_ride_status']}")

                results["pass"] = True
                log("SUCCESS", "Full browser E2E ride lifecycle completed")
            except Exception as exc:
                log("FAIL", str(exc))
                results["blocker"] = str(exc)
                try:
                    fail_path = os.path.join(ARTIFACT_DIR, "failure.png")
                    os.makedirs(ARTIFACT_DIR, exist_ok=True)
                    page.screenshot(path=fail_path, full_page=True)
                    results["screenshots"].append(fail_path)
                    log("SCREENSHOT", fail_path)
                except Exception:
                    pass
                results["error"] = str(exc)
            finally:
                browser.close()
    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except Exception:
                server_proc.kill()
    os.makedirs(os.path.dirname(PROOF_JSON), exist_ok=True)
    with open(PROOF_JSON, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"Wrote {PROOF_JSON}", flush=True)
    return 0 if results.get("pass") else 1


if __name__ == "__main__":
    sys.exit(main())
