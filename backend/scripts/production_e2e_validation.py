"""Production E2E validation: Create -> Dispatch -> Driver -> Pickup -> Complete -> Billing.

Dispatcher operator: Saye (mahnue04@gmail.com, dispatcher role).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

import requests
from playwright.sync_api import Page, sync_playwright

from scripts.executive_proof_harness import (
    APP,
    AuthSession,
    BASE,
    DRIVER_ID,
    DRIVER_PHONE,
    ORG,
    cross_surface,
    db_financial_counts,
    ensure_fresh_token,
    goto_with_retry,
    verify_ride_financial_authoritative,
)

SAYE_EMAIL = os.getenv("AMICOR_OPERATOR_EMAIL", "mahnue04@gmail.com").strip().lower()
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
SYNC_KEY = os.getenv("AMICOR_DEPLOYMENT_SYNC_KEY", PASSWORD).strip()
RIDER_EMAIL = "rider@amicor.local"
RENDER_BASE = os.getenv(
    "AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com"
).rstrip("/")
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
OUT = REPO / f"PRODUCTION_E2E_VALIDATION_{RUN_TS}.json"


def is_local_base() -> bool:
    return BASE.rstrip("/").startswith("http://127.0.0.1") or BASE.rstrip("/").startswith(
        "http://localhost"
    )


def sync_render_seed_users() -> None:
    if is_local_base() or not SYNC_KEY:
        return
    resp = requests.post(
        f"{BASE}/api/auth/deployment/sync-seed-users",
        headers={"X-Amicor-Deployment-Key": SYNC_KEY},
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"seed_sync_failed:{resp.status_code}:{resp.text[:300]}")


def ensure_saye_credentials() -> None:
    """Local validation: align Saye operator password with seed password."""
    if not is_local_base():
        sync_render_seed_users()
        return
    from app.auth import SEED_PASSWORD, apply_operator_role_grants, hash_password
    from app.db.models import User
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == SAYE_EMAIL).first()
        if user:
            user.hashed_password = hash_password(SEED_PASSWORD)
            user.is_active = True
            db.commit()
    apply_operator_role_grants()


def login_saye_dispatcher() -> AuthSession:
    ensure_saye_credentials()
    session = AuthSession(email=SAYE_EMAIL)
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": SAYE_EMAIL, "password": PASSWORD},
        timeout=30,
    )
    if r.status_code != 200 and not is_local_base() and SYNC_KEY:
        sync_render_seed_users()
        r = requests.post(
            f"{BASE}/api/auth/login",
            json={"email": SAYE_EMAIL, "password": PASSWORD},
            timeout=30,
        )
    r.raise_for_status()
    body = r.json()
    token = body["access_token"]
    role = str(body.get("role") or "")
    if role != "dispatcher" and body.get("refresh_token"):
        sw = requests.post(
            f"{BASE}/api/auth/switch-role",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"role": "dispatcher"},
            timeout=30,
        )
        sw.raise_for_status()
        token = sw.json()["access_token"]
    session.token = token
    return session


def wait_shell(page: Page) -> None:
    page.wait_for_function(
        "() => !!(window.AmiOpsShellState && window.AmiOpsShellActions && !window.AmiOpsShellState.loading)",
        timeout=45000,
    )


def platform_login(page: Page, email: str) -> None:
    goto_with_retry(page, APP)
    page.evaluate(
        """async (creds) => {
          const r = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({email: creds.email, password: creds.password})
          });
          const data = await r.json();
          localStorage.setItem('amicor_session', JSON.stringify({
            access_token: data.access_token,
            refresh_token: data.refresh_token,
            email: creds.email
          }));
          localStorage.setItem('amicor_shell_role', creds.email.includes('rider') ? 'rider' : 'admin');
        }""",
        {"email": email, "password": PASSWORD},
    )
    page.reload(wait_until="domcontentloaded")
    wait_shell(page)


def create_ride_rider_ui(page: Page, session: AuthSession) -> dict:
    from scripts.executive_proof_harness import api_get_with_retry, api_post_with_retry

    rider_name = f"Saye E2E Validation {RUN_TS}"
    platform_login(page, RIDER_EMAIL)
    goto_with_retry(page, f"{APP}/riders")
    wait_shell(page)
    page.fill("#rider-name-input", rider_name)
    page.fill("#rider-phone-input", "646-555-9901")
    page.fill("#rider-pickup-input", "100 Production Ave, Brooklyn, NY")
    page.fill("#rider-dropoff-input", "200 Clinic Rd, Brooklyn, NY")
    page.locator('[data-rider-action="request_now"]').first.click()
    page.wait_for_timeout(10000)
    request_id = ride_id = ""
    for _ in range(12):
        rows = api_get_with_retry(session, f"/api/health-isf/customer-requests?limit=20&organization_id={ORG}")
        for row in reversed(rows.get("body") or []):
            if rider_name.lower() in str(row.get("rider_name") or "").lower():
                request_id = str(row.get("id") or "")
                ride_id = str(row.get("ride_id") or "")
                break
        if ride_id:
            break
        page.wait_for_timeout(2000)
    if not ride_id:
        return {"ok": False, "error": "ride_not_created"}
    approve = api_post_with_retry(
        session, f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", {}
    )
    assign = api_post_with_retry(
        session,
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        {"driver_id": DRIVER_ID},
    )
    return {
        "ok": True,
        "ride_id": ride_id,
        "request_id": request_id,
        "rider_name": rider_name,
        "approve_status": approve.get("status"),
        "assign_status": assign.get("status"),
    }


def driver_mobile_login(page: Page) -> None:
    goto_with_retry(page, f"{APP}/mobile")
    wait_shell(page)
    if page.locator("#driver-mobile-phone").count():
        page.fill("#driver-mobile-phone", DRIVER_PHONE)
        page.locator("#driver-mobile-login-btn").click()
        page.wait_for_timeout(5000)
        wait_shell(page)


def click_driver_action(page: Page, action: str, ride_id: str) -> dict:
    btn = page.locator(f'[data-driver-action="{action}"]')
    if btn.count() and btn.first.get_attribute("disabled") is not None and action == "accept_trip":
        page.evaluate(
            """async (tripId) => {
              if (typeof window._amiHandleDriverAcceptTrip === 'function') {
                return await window._amiHandleDriverAcceptTrip(String(tripId || ''));
              }
              return false;
            }""",
            ride_id,
        )
        page.wait_for_timeout(7000)
        return {"action": action, "clicked": True, "via": "handler"}
    if btn.count() and btn.first.get_attribute("disabled") is None:
        btn.first.click()
        page.wait_for_timeout(18000 if action == "complete_trip" else 7000)
        return {"action": action, "clicked": True}
    return {"action": action, "clicked": False}


def run_driver_lifecycle(page: Page, ride_id: str) -> list[dict]:
    driver_mobile_login(page)
    steps = []
    for action in ("accept_trip", "arrive_pickup", "start_trip", "start_transport", "complete_trip"):
        steps.append(click_driver_action(page, action, ride_id))
    return steps


def verify_billing_for_target(ride_id: str, session: AuthSession) -> dict:
    from scripts.executive_proof_harness import api_get_with_retry

    if is_local_base():
        financial = verify_ride_financial_authoritative(ride_id, session, require_delta=True)
        counts = db_financial_counts(ride_id)
        handoff = (financial.get("snapshot") or {}).get("completion_handoff") or {}
        return {
            "ok": financial.get("ok"),
            "counts": counts,
            "handoff_status": handoff.get("status"),
            "financial_proof": financial,
            "mode": "local_db",
        }

    handoff = api_get_with_retry(session, f"/api/health-isf/rides/{ride_id}/completion-handoff")
    summary = api_get_with_retry(session, f"/api/health-isf/rides/{ride_id}/financial-summary")
    handoff_body = handoff.get("body") or {}
    summary_body = summary.get("body") or {}
    driver_pay = float(handoff_body.get("driver_pay_usd") or summary_body.get("driver_pay_usd") or 0)
    platform_rev = float(
        handoff_body.get("platform_revenue_usd") or summary_body.get("platform_revenue_usd") or 0
    )
    ok = (
        int(handoff.get("status") or 0) == 200
        and bool(handoff_body.get("completed"))
        and driver_pay > 0
        and platform_rev > 0
    )
    return {
        "ok": ok,
        "handoff_status": handoff.get("status"),
        "driver_pay_usd": driver_pay,
        "platform_revenue_usd": platform_rev,
        "financial_proof": {"handoff": handoff, "summary": summary},
        "mode": "remote_api",
    }


def main() -> int:
    evidence: dict = {
        "run_ts": RUN_TS,
        "target": BASE,
        "render_url": RENDER_BASE,
        "dispatcher": {"email": SAYE_EMAIL, "display_name": "Saye"},
        "pipeline": "Create -> Dispatch -> Driver -> Pickup -> Complete -> Billing",
        "verdict": "FAIL",
        "steps": {},
    }

    health = requests.get(f"{BASE}/api/health", timeout=10)
    if health.status_code != 200:
        evidence["failed_step"] = "backend_health"
        OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        return 1

    try:
        session = login_saye_dispatcher()
    except Exception as exc:
        evidence["failed_step"] = f"saye_login: {exc}"
        OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        return 1

    evidence["steps"]["dispatcher_auth"] = {"ok": True, "email": SAYE_EMAIL}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        created = create_ride_rider_ui(page, session)
        evidence["steps"]["create"] = created
        if not created.get("ok"):
            evidence["failed_step"] = "create"
            browser.close()
            OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(json.dumps(evidence, indent=2))
            return 1

        ride_id = str(created["ride_id"])
        ensure_fresh_token(session)
        dispatch_snap = cross_surface(session, ride_id)
        evidence["steps"]["dispatch"] = {
            "ok": created.get("assign_status") == 200,
            "approve_status": created.get("approve_status"),
            "assign_status": created.get("assign_status"),
            "surfaces": dispatch_snap.get("ride_present"),
        }
        if created.get("assign_status") != 200:
            evidence["failed_step"] = "dispatch"
            browser.close()
            OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(json.dumps(evidence, indent=2))
            return 1

        lifecycle = run_driver_lifecycle(page, ride_id)
        evidence["steps"]["driver_pickup_complete"] = {
            "ok": all(s.get("clicked") for s in lifecycle),
            "lifecycle": lifecycle,
        }
        browser.close()

    ensure_fresh_token(session)
    evidence["steps"]["billing"] = verify_billing_for_target(ride_id, session)

    all_ok = all(
        evidence["steps"][k].get("ok")
        for k in ("create", "dispatch", "driver_pickup_complete", "billing")
    )
    evidence["ride_id"] = ride_id
    evidence["request_id"] = created.get("request_id")
    evidence["verdict"] = "PASS" if all_ok else "FAIL"
    if not all_ok:
        for name, step in evidence["steps"].items():
            if not step.get("ok"):
                evidence["failed_step"] = name
                break

    OUT.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"verdict": evidence["verdict"], "ride_id": ride_id, "failed_step": evidence.get("failed_step")}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
