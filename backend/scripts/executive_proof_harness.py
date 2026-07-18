"""Shared executive proof harness helpers (auth retry, restart isolation, financial verification)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

BACKEND = Path(__file__).resolve().parent.parent
BASE = os.environ.get("AMICOR_BASE_URL", "http://127.0.0.1:8000")
APP = BASE + "/app"
PASSWORD = "Amicor123!"
DISPATCHER_EMAIL = "dispatcher@amicor.local"
RIDER_EMAIL = "rider@amicor.local"
DRIVER_ID = "b012cd5e-b034-429d-9537-1cd3b047abab"
DRIVER_PHONE = "917-555-1004"
ORG = "ca8d0c7c-1fff-4465-99d7-75a1fc51543e"

TERMINAL_LIFECYCLES = {"completed", "cancelled", "failed", "no_show", "declined"}
TRANSIENT_NAV_ERRORS = (
    "ERR_NETWORK_IO_SUSPENDED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_RESET",
    "ERR_INTERNET_DISCONNECTED",
    "net::ERR_",
)
IN_TRIP_ASSIGNMENT_STATES = {
    "assigned",
    "accepted",
    "en_route_pickup",
    "arrived_pickup",
    "pickup_complete",
    "transporting",
    "dropoff_complete",
}


@dataclass
class AuthSession:
    email: str = DISPATCHER_EMAIL
    token: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def login(self) -> str:
        r = requests.post(
            f"{BASE}/api/auth/login",
            json={"email": self.email, "password": PASSWORD},
            timeout=30,
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]
        return self.token

    def refresh(self) -> str:
        return self.login()


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _is_token_expired(status: int, body: Any) -> bool:
    if status != 401:
        return False
    text = json.dumps(body, default=str).lower()
    return "token expired" in text or "expired" in text or status == 401


def ensure_fresh_token(session: AuthSession) -> str:
    if not session.token:
        return session.login()
    r = requests.get(
        f"{BASE}/api/health-isf/drivers/{DRIVER_ID}?organization_id={ORG}",
        headers=_hdr(session.token),
        timeout=30,
    )
    if r.status_code == 401:
        return session.refresh()
    return session.token


def api_get_with_retry(session: AuthSession, path: str) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for attempt_idx in range(2):
        token = ensure_fresh_token(session) if attempt_idx == 0 else session.refresh()
        r = requests.get(f"{BASE}{path}", headers=_hdr(token), timeout=90)
        body: Any = {}
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:800]}
        attempts.append({"attempt": attempt_idx + 1, "status": r.status_code, "path": path})
        if r.status_code == 401 and _is_token_expired(r.status_code, body) and attempt_idx == 0:
            continue
        session.token = token
        session.attempts.extend(attempts)
        return {"status": r.status_code, "body": body, "auth_attempts": attempts}
    session.attempts.extend(attempts)
    return {"status": 401, "body": {"detail": "auth_retry_exhausted"}, "auth_attempts": attempts}


def api_post_with_retry(session: AuthSession, path: str, payload: dict | None = None) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for attempt_idx in range(2):
        token = ensure_fresh_token(session) if attempt_idx == 0 else session.refresh()
        r = requests.post(
            f"{BASE}{path}",
            headers={**_hdr(token), "Content-Type": "application/json"},
            json=payload or {},
            timeout=120,
        )
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:800]}
        attempts.append({"attempt": attempt_idx + 1, "status": r.status_code, "path": path})
        if r.status_code == 401 and _is_token_expired(r.status_code, body) and attempt_idx == 0:
            continue
        session.token = token
        session.attempts.extend(attempts)
        return {"status": r.status_code, "body": body, "auth_attempts": attempts}
    session.attempts.extend(attempts)
    return {"status": 401, "body": {"detail": "auth_retry_exhausted"}, "auth_attempts": attempts}


def wait_backend_healthy(*, consecutive: int = 3, timeout_s: int = 120) -> dict[str, Any]:
    ok_streak = 0
    started = time.time()
    samples: list[dict[str, Any]] = []
    while time.time() - started < timeout_s:
        try:
            r = requests.get(f"{BASE}/api/health", timeout=5)
            sample = {"status": r.status_code, "at": datetime.now(timezone.utc).isoformat()}
            samples.append(sample)
            if r.status_code == 200:
                ok_streak += 1
                if ok_streak >= consecutive:
                    return {"ok": True, "consecutive": consecutive, "samples": samples[-consecutive:]}
            else:
                ok_streak = 0
        except Exception as exc:
            samples.append({"error": str(exc), "at": datetime.now(timezone.utc).isoformat()})
            ok_streak = 0
        time.sleep(2)
    return {"ok": False, "consecutive_required": consecutive, "samples": samples[-8:]}


def port_8000_pids() -> list[int]:
    if sys.platform != "win32":
        return []
    proc = subprocess.run(
        [
            "powershell",
            "-Command",
            "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty OwningProcess -Unique",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: list[int] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit() and int(line) > 0:
            pids.append(int(line))
    return sorted(set(pids))


def restart_backend_single_instance() -> dict[str, Any]:
    report: dict[str, Any] = {"actions": []}

    def _stop_listeners() -> None:
        if sys.platform == "win32":
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | "
                    "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }",
                ],
                check=False,
                capture_output=True,
            )
        else:
            subprocess.run(["pkill", "-f", "uvicorn app.main:app"], check=False)

    def _start_listener() -> None:
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(BACKEND),
            env={**os.environ, "PYTHONPATH": str(BACKEND)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    _stop_listeners()
    report["actions"].append("stopped_listeners")
    time.sleep(4)
    _start_listener()
    report["actions"].append("started_uvicorn")
    health = wait_backend_healthy(consecutive=3, timeout_s=180)
    if not health.get("ok"):
        report["actions"].append("retry_start")
        _stop_listeners()
        time.sleep(4)
        _start_listener()
        health = wait_backend_healthy(consecutive=3, timeout_s=180)
    report["health"] = health
    pids = port_8000_pids()
    report["listening_pids"] = pids
    report["single_listener"] = len(pids) == 1
    if not health.get("ok"):
        raise RuntimeError(f"backend health gate failed: {health}")
    if len(pids) != 1:
        raise RuntimeError(f"expected one listener on 8000, found {pids}")
    return report


def db_financial_counts(ride_id: str) -> dict[str, int]:
    from app.db.session import SessionLocal
    from app.modules.health_isf.models import (
        HealthISFBillingHandoff,
        HealthISFPaymentTransaction,
        HealthISFPayout,
        HealthISFTrip,
    )

    with SessionLocal() as db:
        handoffs = (
            db.query(HealthISFBillingHandoff)
            .filter(HealthISFBillingHandoff.ride_id == ride_id)
            .count()
        )
        payments = (
            db.query(HealthISFPaymentTransaction)
            .filter(HealthISFPaymentTransaction.ride_id == ride_id)
            .count()
        )
        trip = db.query(HealthISFTrip).filter(HealthISFTrip.ride_id == ride_id).first()
        payouts = 0
        if trip:
            payouts = (
                db.query(HealthISFPayout)
                .filter(HealthISFPayout.trip_id == str(trip.id))
                .count()
            )
        completion_events = (
            db.query(HealthISFBillingHandoff)
            .filter(
                HealthISFBillingHandoff.ride_id == ride_id,
                HealthISFBillingHandoff.handoff_status.isnot(None),
            )
            .count()
        )
    return {
        "handoffs": handoffs,
        "payments": payments,
        "payouts": payouts,
        "completion_handoff_rows": completion_events,
    }


def fin_snapshot(ride_id: str, session: AuthSession, global_before: dict[str, Any] | None = None) -> dict[str, Any]:
    counts = db_financial_counts(ride_id)
    earn = api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}/earnings?organization_id={ORG}")
    handoff_detail = api_get_with_retry(session, f"/api/health-isf/rides/{ride_id}/completion-handoff")
    fin_summary = api_get_with_retry(session, f"/api/health-isf/rides/{ride_id}/financial-summary")
    drv = api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}?organization_id={ORG}")
    rev = api_get_with_retry(session, "/api/health-isf/operations/admin-revenue")
    ebody = earn.get("body") or {}
    rbody = rev.get("body") or {}
    dbody = drv.get("body") or {}
    handoff_body = handoff_detail.get("body") or {}
    return {
        **counts,
        "earnings_today_usd": float(ebody.get("earnings_today_usd") or 0),
        "earnings_lifetime_usd": float(ebody.get("earnings_lifetime_usd") or 0),
        "completed_trips": int(ebody.get("completed_trips") or 0),
        "platform_revenue_total_usd": float(rbody.get("platform_revenue_total_usd") or 0),
        "availability_state": str(dbody.get("availability_state") or ""),
        "driver_status": str(dbody.get("status") or ""),
        "completion_handoff": handoff_detail,
        "financial_summary": fin_summary,
        "completion_event": bool(handoff_body.get("completed")),
        "driver_pay_usd": float(handoff_body.get("driver_pay_usd") or 0),
        "platform_revenue_usd": float(handoff_body.get("platform_revenue_usd") or 0),
    }


def verify_ride_financial_authoritative(
    ride_id: str,
    session: AuthSession,
    *,
    global_before: dict[str, Any] | None = None,
    require_delta: bool = False,
) -> dict[str, Any]:
    ensure_fresh_token(session)
    snap = fin_snapshot(ride_id, session, global_before)
    handoff = snap.get("completion_handoff") or {}
    handoff_status = int(handoff.get("status") or 0)
    handoff_body = handoff.get("body") or {}
    duplicate_check = db_financial_counts(ride_id)

    exactly_one = (
        duplicate_check["handoffs"] == 1
        and duplicate_check["payments"] == 1
        and duplicate_check["payouts"] == 1
        and snap.get("completion_event") is True
        and handoff_status == 200
    )
    delta_ok = True
    delta: dict[str, Any] = {}
    if global_before:
        delta = {
            "earnings_lifetime_delta": snap["earnings_lifetime_usd"] - float(global_before.get("earnings_lifetime_usd") or 0),
            "platform_revenue_delta": snap["platform_revenue_total_usd"] - float(global_before.get("platform_revenue_total_usd") or 0),
        }
        if require_delta:
            delta_ok = delta["earnings_lifetime_delta"] > 0 and delta["platform_revenue_delta"] > 0

    driver_pay = float(handoff_body.get("driver_pay_usd") or snap.get("driver_pay_usd") or 0)
    platform_rev = float(handoff_body.get("platform_revenue_usd") or snap.get("platform_revenue_usd") or 0)
    amounts_ok = driver_pay > 0 and platform_rev > 0

    return {
        "ok": exactly_one and amounts_ok and delta_ok and handoff_status == 200,
        "ride_id": ride_id,
        "counts": duplicate_check,
        "snapshot": snap,
        "delta": delta,
        "handoff_status": handoff_status,
        "failure_layer": "application" if not exactly_one else ("proof_harness" if handoff_status == 401 else None),
    }


def global_financial_baseline(session: AuthSession) -> dict[str, Any]:
    ensure_fresh_token(session)
    earn = api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}/earnings?organization_id={ORG}")
    rev = api_get_with_retry(session, "/api/health-isf/operations/admin-revenue")
    ebody = earn.get("body") or {}
    rbody = rev.get("body") or {}
    return {
        "earnings_today_usd": float(ebody.get("earnings_today_usd") or 0),
        "earnings_lifetime_usd": float(ebody.get("earnings_lifetime_usd") or 0),
        "completed_trips": int(ebody.get("completed_trips") or 0),
        "platform_revenue_total_usd": float(rbody.get("platform_revenue_total_usd") or 0),
    }


def cross_surface(session: AuthSession, ride_id: str) -> dict[str, Any]:
    snap = {
        "driver_active_offer": api_get_with_retry(
            session, f"/api/health-isf/drivers/{DRIVER_ID}/active-offer?organization_id={ORG}"
        ),
        "driver_active_ride": api_get_with_retry(
            session, f"/api/health-isf/drivers/{DRIVER_ID}/active-ride?organization_id={ORG}"
        ),
        "driver_assigned": api_get_with_retry(
            session, f"/api/health-isf/drivers/{DRIVER_ID}/assigned-rides?organization_id={ORG}"
        ),
        "dispatch_queue": api_get_with_retry(
            session, f"/api/health-isf/dispatch/queue?limit=40&organization_id={ORG}"
        ),
        "trips": api_get_with_retry(session, f"/api/health-isf/rides?limit=40&organization_id={ORG}"),
        "ai_snapshot": api_get_with_retry(
            session, f"/api/health-isf/ai-dispatch/snapshot?publish=false&organization_id={ORG}"
        ),
        "billing_handoffs": api_get_with_retry(
            session, f"/api/health-isf/operations/billing-handoffs?limit=40&organization_id={ORG}"
        ),
    }
    if ride_id:
        snap["ride_present"] = surface_contains_ride(snap, ride_id)
    return snap


def surface_contains_ride(snap: dict[str, Any], ride_id: str) -> dict[str, bool]:
    rid = str(ride_id)
    present: dict[str, bool] = {}

    def _scan_rows(rows: Any) -> bool:
        if not isinstance(rows, list):
            return False
        return any(rid in json.dumps(row, default=str) for row in rows)

    offer_body = (snap.get("driver_active_offer") or {}).get("body") or {}
    offer = offer_body.get("offer") or {}
    present["driver_mobile_offer"] = str(offer.get("ride_id") or "") == rid

    active_body = (snap.get("driver_active_ride") or {}).get("body") or {}
    ride = active_body.get("ride") or {}
    present["driver_mobile_active"] = str(ride.get("id") or "") == rid

    assigned_rows = (snap.get("driver_assigned") or {}).get("body") or []
    present["driver_assigned_queue"] = any(
        str(r.get("id") or r.get("ride_id") or "") == rid for r in assigned_rows if isinstance(assigned_rows, list)
    )
    present["driver_assigned"] = present["driver_assigned_queue"]

    dispatch_rows = (snap.get("dispatch_queue") or {}).get("body") or []
    present["dispatch_active_queue"] = _scan_rows(dispatch_rows) and any(
        str(row.get("ride_id") or row.get("id") or "") == rid
        and str(row.get("lifecycle_state") or row.get("status") or "").lower() not in TERMINAL_LIFECYCLES
        for row in dispatch_rows
        if isinstance(dispatch_rows, list)
    )
    present["dispatch_queue"] = present["dispatch_active_queue"]
    present["trips"] = _scan_rows((snap.get("trips") or {}).get("body"))

    ai_body = (snap.get("ai_snapshot") or {}).get("body") or {}
    focused = ((ai_body.get("live_dispatch") or {}).get("focused_ride") or {})
    present["ai_focus"] = str(focused.get("ride_id") or "") == rid

    billing = (snap.get("billing_handoffs") or {}).get("body") or []
    present["billing_active"] = any(
        str(row.get("ride_id") or "") == rid
        and str(row.get("handoff_status") or row.get("status") or "").lower()
        not in {"completed", "settled", "closed"}
        for row in (billing if isinstance(billing, list) else [])
    )
    return present


def ride_in_active_surfaces(session: AuthSession, ride_id: str) -> dict[str, Any]:
    ensure_fresh_token(session)
    snap = cross_surface(session, ride_id)
    present = snap.get("ride_present") or {}
    active_keys = (
        "driver_mobile_offer",
        "driver_mobile_active",
        "driver_assigned_queue",
        "dispatch_active_queue",
    )
    active_hits = {k: present.get(k) for k in active_keys if present.get(k)}
    return {"active": bool(active_hits), "surfaces": active_hits, "snap": snap}


def locate_completed_ride_1(repo_root: Path) -> dict[str, Any] | None:
    env_id = os.environ.get("EXECUTIVE_RIDE_1_ID", "").strip()
    if env_id:
        return {"ride_id": env_id, "source": "env"}

    candidates: list[tuple[str, str, bool]] = []
    for path in sorted(repo_root.glob("EXECUTIVE_EVIDENCE_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        ride1 = (data.get("rides") or {}).get("ride_1") or {}
        rid = str(ride1.get("ride_id") or "")
        if rid and ride1.get("lifecycle_ok"):
            candidates.append((path.name, rid, bool(ride1.get("financial_ok"))))

    from app.db.session import SessionLocal
    from app.modules.health_isf import service as hs
    from app.modules.health_isf.models import HealthISFRide

    with SessionLocal() as db:
        for _, rid, _ in candidates:
            ride = hs.get_ride_by_id(db, rid)
            if ride and hs._ride_is_terminal(ride) and str(ride.lifecycle_state or ride.status).lower() == "completed":
                fin = db_financial_counts(rid)
                if fin["handoffs"] >= 1 and fin["payments"] >= 1:
                    return {"ride_id": rid, "source": "evidence+db", "financial_counts": fin}

        row = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.organization_id == ORG,
                HealthISFRide.driver_id == DRIVER_ID,
                HealthISFRide.passenger_name.ilike("Executive Revenue R1%"),
            )
            .order_by(HealthISFRide.completed_at.desc())
            .first()
        )
        if row and hs._ride_is_terminal(row):
            rid = str(row.id)
            fin = db_financial_counts(rid)
            if fin["handoffs"] >= 1:
                return {"ride_id": rid, "source": "db", "passenger_name": row.passenger_name, "financial_counts": fin}

    if candidates:
        _, rid, _ = candidates[0]
        return {"ride_id": rid, "source": "evidence_only"}
    return None


@dataclass
class BrowserStack:
    playwright: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None

    def launch(self, pw: Playwright) -> Page:
        self.playwright = pw
        self.browser = pw.chromium.launch(headless=True)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        return self.page

    def close_all(self) -> None:
        for target in (self.page, self.context, self.browser):
            if target is None:
                continue
            try:
                target.close()
            except Exception:
                pass
        self.page = self.context = self.browser = None


def goto_with_retry(page: Page, url: str, *, timeout_ms: int = 45000, attempts: int = 6) -> dict[str, Any]:
    log: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return {"ok": True, "url": url, "attempts": log + [{"attempt": attempt, "ok": True}]}
        except Exception as exc:
            msg = str(exc)
            log.append({"attempt": attempt, "error": msg})
            transient = any(marker in msg for marker in TRANSIENT_NAV_ERRORS)
            if transient:
                wait_backend_healthy(consecutive=2, timeout_s=60)
                time.sleep(2)
                continue
            if attempt >= attempts:
                return {"ok": False, "url": url, "attempts": log, "failure_layer": "proof_harness"}
            time.sleep(2)
    return {"ok": False, "url": url, "attempts": log, "failure_layer": "proof_harness"}


def isolated_backend_restart(stack: BrowserStack, saved: dict[str, Any]) -> tuple[BrowserStack, AuthSession, dict[str, Any]]:
    stack.close_all()
    restart_report = restart_backend_single_instance()
    session = AuthSession()
    session.login()
    if stack.playwright is None:
        raise RuntimeError("playwright instance missing for relaunch")
    stack.launch(stack.playwright)
    assert stack.page is not None
    nav = goto_with_retry(stack.page, f"{APP}/mobile?v={saved.get('run_ts', 'resume')}")
    restart_report["navigation"] = nav
    restart_report["saved_ride_1_id"] = saved.get("ride_1_id")
    restart_report["saved_financial_snapshot"] = saved.get("financial_snapshot")
    return stack, session, restart_report


def driver_reset_proof(session: AuthSession) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.modules.health_isf import service as hs

    attempts: list[dict[str, Any]] = []
    for attempt in range(6):
        with SessionLocal() as db:
            hs._prepare_driver_mobile_workspace_read(db, organization_id=ORG, driver_id=DRIVER_ID)
            db.commit()
        ensure_fresh_token(session)
        drv = api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}?organization_id={ORG}")
        offer = api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}/active-offer?organization_id={ORG}")
        active = api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}/active-ride?organization_id={ORG}")
        assigned = api_get_with_retry(session, f"/api/health-isf/drivers/{DRIVER_ID}/assigned-rides?organization_id={ORG}")

        dbody = drv.get("body") or {}
        obody = offer.get("body") or {}
        offer_row = obody.get("offer") or {}
        abody = active.get("body") or {}
        assigned_rows = assigned.get("body") or []

        eligible_offers = 0
        if offer_row.get("ride_id"):
            lc = str(offer_row.get("ride_status") or offer_row.get("lifecycle_state") or "").lower()
            if lc not in TERMINAL_LIFECYCLES:
                eligible_offers += 1

        terminal_in_assigned = [
            str(r.get("id") or "")
            for r in assigned_rows
            if isinstance(assigned_rows, list)
            and str(r.get("lifecycle_state") or r.get("status") or "").lower() in TERMINAL_LIFECYCLES
        ]

        active_ride = abody.get("ride") or {}
        active_ride_id = str(active_ride.get("id") or "")
        active_lc = str(active_ride.get("lifecycle_state") or active_ride.get("status") or "").lower()
        active_assignment = abody.get("active_assignment") or {}
        assignment_state = str(
            active_assignment.get("assignment_state") or abody.get("assignment_state") or ""
        ).lower()
        has_current_trip = (
            bool(abody.get("has_active_ride"))
            and assignment_state in IN_TRIP_ASSIGNMENT_STATES
            and active_lc not in TERMINAL_LIFECYCLES
        )

        ok = (
            str(dbody.get("availability_state") or "").lower() == "available"
            and not has_current_trip
            and eligible_offers <= 1
            and not terminal_in_assigned
        )
        attempts.append(
            {
                "attempt": attempt + 1,
                "availability_state": dbody.get("availability_state"),
                "has_current_trip": has_current_trip,
                "assignment_state": assignment_state or None,
                "active_ride_id": active_ride_id or None,
                "eligible_offer_count": eligible_offers,
                "terminal_in_assigned": terminal_in_assigned,
            }
        )
        if ok:
            return {
                "ok": True,
                "availability_state": dbody.get("availability_state"),
                "has_current_trip": has_current_trip,
                "eligible_offer_count": eligible_offers,
                "terminal_in_assigned": terminal_in_assigned,
                "attempts": attempts,
            }
        time.sleep(3)

    last = attempts[-1] if attempts else {}
    return {
        "ok": False,
        "availability_state": last.get("availability_state"),
        "has_current_trip": last.get("has_current_trip"),
        "eligible_offer_count": last.get("eligible_offer_count"),
        "terminal_in_assigned": last.get("terminal_in_assigned"),
        "attempts": attempts,
        "failure_layer": "application",
    }
