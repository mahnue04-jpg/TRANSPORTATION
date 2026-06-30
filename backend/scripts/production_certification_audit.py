"""Production certification audit — objective evidence collection."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))

BASE = os.getenv("AMICOR_BROWSER_BASE", "https://amicor-health-isf-py.onrender.com")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
REPORT_PATH = BACKEND_ROOT / "artifacts" / "production_certification_report.json"

ACCOUNTS = {
    "dispatcher": "dispatcher@amicor.local",
    "driver": "driver@amicor.local",
    "rider": "rider@amicor.local",
    "provider": "provider@amicor.local",
    "admin": "admin@amicor.local",
}

API_ENDPOINTS = [
    ("GET", "/api/health/live", None, False),
    ("GET", "/api/health/readiness", None, False),
    ("GET", "/health", None, False),
    ("POST", "/api/auth/login", {"email": "admin@amicor.local", "password": PASSWORD}, False),
    ("GET", "/api/health-isf/dashboard", None, True),
    ("GET", "/api/health-isf/rides", None, True),
    ("GET", "/api/health-isf/drivers", None, True),
    ("GET", "/api/health-isf/providers", None, True),
    ("GET", "/api/health-isf/dispatch/queue", None, True),
    ("GET", "/api/health-isf/dispatch/active-assignments", None, True),
    ("GET", "/api/health-isf/admin/command-center/summary", None, True),
    ("GET", "/api/health-isf/customers/workspace/history?rider_phone=646-555-8800&limit=5", None, True),
]


def login(client: httpx.Client, email: str) -> str:
    res = client.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD}, timeout=30)
    res.raise_for_status()
    return res.json()["access_token"]


def probe_api_health() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    token = ""
    with httpx.Client(base_url=BASE, timeout=30) as client:
        for method, path, body, needs_auth in API_ENDPOINTS:
            headers = {}
            if needs_auth:
                if not token:
                    token = login(client, ACCOUNTS["admin"])
                headers["Authorization"] = f"Bearer {token}"
            started = time.perf_counter()
            try:
                if method == "GET":
                    res = client.get(path, headers=headers)
                else:
                    res = client.post(path, json=body, headers=headers)
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                rows.append({
                    "method": method,
                    "path": path,
                    "status": res.status_code,
                    "ok": res.status_code < 400,
                    "latency_ms": elapsed_ms,
                    "auth": needs_auth,
                })
            except Exception as exc:
                rows.append({
                    "method": method,
                    "path": path,
                    "status": None,
                    "ok": False,
                    "latency_ms": None,
                    "error": str(exc),
                    "auth": needs_auth,
                })
    unexpected = [
        r for r in rows
        if r.get("status") in (401, 403, 404, 500, 502) or r.get("status") is None
        or (r.get("path") == "/api/health/readiness" and r.get("status") not in (200, 503))
    ]
    readiness = next((r for r in rows if r.get("path") == "/api/health/readiness"), None)
    return {
        "passed": len(unexpected) == 0,
        "endpoints": rows,
        "unexpected_errors": unexpected,
        "readiness_status": readiness.get("status") if readiness else None,
        "p50_ms": statistics.median([r["latency_ms"] for r in rows if r.get("latency_ms") is not None]) if rows else None,
        "max_ms": max([r["latency_ms"] for r in rows if r.get("latency_ms") is not None], default=None),
    }


def load_test(concurrency: int = 8, requests_per_worker: int = 5) -> dict[str, Any]:
    token = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": ACCOUNTS["admin"], "password": PASSWORD},
        timeout=30,
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    latencies: list[float] = []
    errors = 0

    def worker(_: int) -> list[float]:
        local: list[float] = []
        with httpx.Client(base_url=BASE, timeout=30) as client:
            for _ in range(requests_per_worker):
                start = time.perf_counter()
                res = client.get("/api/health-isf/dashboard", headers=headers)
                elapsed = (time.perf_counter() - start) * 1000
                local.append(elapsed)
                if res.status_code >= 400:
                    nonlocal_errors.append(res.status_code)
        return local

    nonlocal_errors: list[int] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, i) for i in range(concurrency)]
        for fut in as_completed(futures):
            try:
                latencies.extend(fut.result())
            except Exception as exc:
                errors += 1
                nonlocal_errors.append(str(exc))

    errors = len(nonlocal_errors)
    total = len(latencies)
    latencies_sorted = sorted(latencies)
    p95 = latencies_sorted[int(total * 0.95) - 1] if total else None
    return {
        "passed": errors == 0 and total > 0,
        "concurrency": concurrency,
        "total_requests": total,
        "errors": errors,
        "p50_ms": round(statistics.median(latencies), 2) if latencies else None,
        "p95_ms": round(p95, 2) if p95 else None,
        "max_ms": round(max(latencies), 2) if latencies else None,
        "rps": round(total / max(sum(latencies) / 1000, 0.001), 2),
    }


def verify_db_integrity() -> dict[str, Any]:
    from app.auth import ensure_auth_schema, seed_default_users
    from app.db.session import SessionLocal
    from app.modules.health_isf.models import (
        HealthISFDispatchAssignment,
        HealthISFPayout,
        HealthISFRide,
        HealthISFTrip,
        RideStatus,
    )

    ensure_auth_schema()
    seed_default_users()
    db = SessionLocal()
    try:
        completed = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.status == RideStatus.COMPLETED)
            .count()
        )
        trips = db.query(HealthISFTrip).count()
        payouts = db.query(HealthISFPayout).count()
        assignments = db.query(HealthISFDispatchAssignment).count()
        completed_with_trip = (
            db.query(HealthISFRide)
            .join(HealthISFTrip, HealthISFTrip.ride_id == HealthISFRide.id)
            .filter(HealthISFRide.status == RideStatus.COMPLETED)
            .count()
        )
        completed_with_payout = (
            db.query(HealthISFTrip)
            .join(HealthISFPayout, HealthISFPayout.trip_id == HealthISFTrip.id)
            .count()
        )
        orphan_trips = trips - completed_with_trip if trips >= completed_with_trip else 0
        return {
            "passed": completed == 0 or completed_with_trip > 0,
            "completed_rides": completed,
            "trips_total": trips,
            "payouts_total": payouts,
            "assignments_total": assignments,
            "completed_rides_with_trip": completed_with_trip,
            "trips_with_payout": completed_with_payout,
            "trip_coverage_pct": round((completed_with_trip / completed * 100), 2) if completed else 100.0,
            "payout_coverage_pct": round((completed_with_payout / trips * 100), 2) if trips else 100.0,
        }
    finally:
        db.close()


def verify_rbac_matrix() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with httpx.Client(base_url=BASE, timeout=30) as client:
        for role, email in ACCOUNTS.items():
            token = login(client, email)
            headers = {"Authorization": f"Bearer {token}"}
            admin_res = client.get("/api/health-isf/admin/command-center/summary", headers=headers)
            rides_res = client.get("/api/health-isf/rides", headers=headers)
            rows.append({
                "role": role,
                "email": email,
                "rides_status": rides_res.status_code,
                "admin_status": admin_res.status_code,
                "admin_allowed": admin_res.status_code == 200,
                "rides_allowed": rides_res.status_code == 200,
            })
    admin_only_ok = all(r["admin_status"] in (200,) for r in rows if r["role"] == "admin")
    non_admin_blocked = all(r["admin_status"] in (403, 401) for r in rows if r["role"] != "admin")
    return {
        "passed": admin_only_ok and non_admin_blocked,
        "matrix": rows,
    }


def verify_frontend_placeholders() -> dict[str, Any]:
    res = httpx.get(f"{BASE}/", timeout=30)
    html = res.text
    static_loading = [
        "Loading billing KPIs",
        "Loading admin operational summary",
        "Loading dispatch worklist",
    ]
    found_static = [s for s in static_loading if s in html]
    return {
        "passed": True,
        "note": "Static HTML contains bootstrap placeholders; runtime hydration verified separately via browser E2E audit.",
        "static_placeholders_in_html": found_static,
        "index_status": res.status_code,
    }


def verify_deployment_config() -> dict[str, Any]:
    from app.deployment.readiness import DeploymentReadinessChecker

    checklist = BACKEND_ROOT / "docs" / "STAGING_PRODUCTION_ENV_CHECKLIST.md"
    backup_doc = BACKEND_ROOT / "docs" / "POSTGRES_BACKUP_RESTORE_STAGING.md"
    try:
        live = httpx.get(f"{BASE}/api/health/readiness", timeout=30)
        readiness_payload = live.json()
        readiness_status = live.status_code
    except Exception as exc:
        readiness_payload = {"error": str(exc)}
        readiness_status = None

    blocked = readiness_payload.get("blocked_reasons") if isinstance(readiness_payload, dict) else None
    live_ready = (
        readiness_status == 200
        and isinstance(readiness_payload, dict)
        and readiness_payload.get("overall_status") == "ready"
    )
    docs_present = checklist.exists() and backup_doc.exists()
    structural_ok = isinstance(blocked, list) and "production_environment" in (readiness_payload or {})

    return {
        "passed": live_ready and docs_present,
        "live_ready": live_ready,
        "docs_present": docs_present,
        "structural_ok": structural_ok,
        "blocked_reasons": blocked or [],
        "live_readiness_status": readiness_status,
        "live_readiness": readiness_payload,
        "checklist_path": str(checklist),
        "backup_doc_path": str(backup_doc),
        "note": (
            "Local dev returns not_ready until staging env vars are applied — see STAGING_PRODUCTION_ENV_CHECKLIST.md"
            if not live_ready
            else "Live readiness reports ready"
        ),
    }


def run_frontend_runtime_audit() -> dict[str, Any]:
    import subprocess

    script = BACKEND_ROOT / "scripts" / "browser_frontend_console_audit.py"
    if not script.exists():
        return {"passed": False, "error": "browser_frontend_console_audit.py missing"}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    env["AMICOR_BROWSER_BASE"] = BASE
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out_path = BACKEND_ROOT / "artifacts" / "frontend_console_audit.json"
    payload: dict[str, Any] = {"passed": result.returncode == 0}
    if out_path.exists():
        with open(out_path, encoding="utf-8") as fh:
            payload = json.load(fh)
    payload["exit_code"] = result.returncode
    if result.stderr:
        payload["stderr_tail"] = result.stderr[-500:]
    return payload


def run_persistence_budget_test() -> dict[str, Any]:
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_health_isf_persistence.py::HealthISFPersistenceIntegrationTests::test_dashboard_query_budget_avoids_n_plus_one",
            "-q",
            "--tb=no",
        ],
        cwd=str(BACKEND_ROOT),
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout_tail": (result.stdout or "")[-400:],
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    print("[CERT] Production certification audit starting...", flush=True)

    sections: dict[str, Any] = {}
    sections["performance"] = run_persistence_budget_test()
    print(f"[CERT] Performance: {'PASS' if sections['performance']['passed'] else 'FAIL'}", flush=True)

    sections["api_health"] = probe_api_health()
    print(f"[CERT] API health: {'PASS' if sections['api_health']['passed'] else 'FAIL'}", flush=True)

    sections["load_test"] = load_test()
    print(f"[CERT] Load test: {'PASS' if sections['load_test']['passed'] else 'FAIL'}", flush=True)

    sections["database"] = verify_db_integrity()
    print(f"[CERT] Database: {'PASS' if sections['database']['passed'] else 'FAIL'}", flush=True)

    sections["security_rbac"] = verify_rbac_matrix()
    print(f"[CERT] RBAC: {'PASS' if sections['security_rbac']['passed'] else 'FAIL'}", flush=True)

    sections["frontend"] = run_frontend_runtime_audit()
    print(f"[CERT] Frontend: {'PASS' if sections['frontend'].get('passed') else 'FAIL'}", flush=True)

    sections["deployment"] = verify_deployment_config()
    print(f"[CERT] Deployment: {'PASS' if sections['deployment']['passed'] else 'FAIL'}", flush=True)

    # Load latest browser E2E report if present
    e2e_report = BACKEND_ROOT / "artifacts" / "health_isf_readiness_audit_report.json"
    if e2e_report.exists():
        with open(e2e_report, encoding="utf-8") as fh:
            sections["regression_e2e"] = json.load(fh)
    else:
        sections["regression_e2e"] = {"passed": False, "error": "No E2E report found — run browser_health_isf_readiness_audit.py"}

    all_section_keys = [
        "regression_e2e",
        "performance",
        "database",
        "api_health",
        "frontend",
        "security_rbac",
        "load_test",
        "deployment",
    ]

    def section_passed(key: str) -> bool:
        data = sections.get(key) or {}
        if key == "regression_e2e":
            return bool(data.get("all_pass"))
        return bool(data.get("passed"))

    overall = all(section_passed(k) for k in all_section_keys)

    report = {
        "timestamp_utc": started,
        "preview_base": BASE,
        "overall_certified": overall,
        "production_ready": overall,
        "sections": sections,
        "section_status": {k: "PASS" if section_passed(k) else "FAIL" for k in all_section_keys},
        "evidence_gaps": [
            item for item in [
                None if sections.get("deployment", {}).get("live_ready") else "Apply staging env vars per backend/docs/STAGING_PRODUCTION_ENV_CHECKLIST.md",
                None if sections.get("deployment", {}).get("docs_present") else "Deployment checklist docs missing",
                "Memory leak detection — not instrumented",
                "PostgreSQL backup drill — documented in POSTGRES_BACKUP_RESTORE_STAGING.md; execute on staging before prod",
            ] if item
        ],
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"[CERT] Wrote {REPORT_PATH}", flush=True)
    print(f"[CERT] Overall: {'CERTIFIED' if overall else 'NOT CERTIFIED'}", flush=True)
    print(json.dumps(report["section_status"]), flush=True)
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
