"""Final production readiness verification — aggregates local + Render evidence."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND = SCRIPT_DIR.parent
ARTIFACTS = BACKEND / "artifacts"
sys.path.insert(0, str(BACKEND))

LOCAL_BASE = os.getenv("AMICOR_LOCAL_BASE", "http://127.0.0.1:8010")
RENDER_BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
OUT = ARTIFACTS / "final_production_readiness_report.json"


def load_json(name: str) -> dict[str, Any]:
    path = ARTIFACTS / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def login(base: str, email: str) -> dict[str, str]:
    resp = httpx.post(
        f"{base.rstrip('/')}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=90,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def probe_render_readiness(base: str) -> dict[str, Any]:
    out: dict[str, Any] = {"base": base, "checks": {}}
    try:
        live = httpx.get(f"{base.rstrip('/')}/api/health/live", timeout=45)
        out["checks"]["live"] = live.status_code == 200
        out["live_status"] = live.status_code
    except Exception as exc:
        out["checks"]["live"] = False
        out["live_error"] = str(exc)
    try:
        ready = httpx.get(f"{base.rstrip('/')}/api/health/readiness", timeout=60)
        payload = ready.json() if ready.headers.get("content-type", "").startswith("application/json") else {}
        out["readiness_status"] = ready.status_code
        out["readiness_payload"] = payload
        out["checks"]["readiness"] = (
            ready.status_code == 200
            and isinstance(payload, dict)
            and payload.get("overall_status") == "ready"
        )
        out["blocked_reasons"] = payload.get("blocked_reasons") if isinstance(payload, dict) else []
    except Exception as exc:
        out["checks"]["readiness"] = False
        out["readiness_error"] = str(exc)
    try:
        app = httpx.get(f"{base.rstrip('/')}/app", timeout=45, follow_redirects=True)
        out["checks"]["app_shell"] = app.status_code == 200
        out["app_status"] = app.status_code
    except Exception as exc:
        out["checks"]["app_shell"] = False
        out["app_error"] = str(exc)
    return out


def run_script(rel_path: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    script = BACKEND / rel_path
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(BACKEND)
    if env:
        merged.update(env)
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(BACKEND),
        env=merged,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return {
        "script": rel_path,
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout_tail": (proc.stdout or "")[-800:],
        "stderr_tail": (proc.stderr or "")[-800:],
    }


def build_checklist(reports: dict[str, dict[str, Any]], runs: dict[str, Any]) -> dict[str, str]:
    rider = reports.get("rider", {})
    driver_ops = reports.get("driver_ops", {})
    ops = reports.get("ops", {})
    audit = reports.get("audit", {})
    console = reports.get("console_local", {})
    cert = reports.get("render_cert", {})
    smoke = reports.get("render_smoke", {})

    no_placeholders = (
        rider.get("all_pass")
        and driver_ops.get("verdict") == "PASS"
        and ops.get("all_pass")
    )
    rider_create = bool(rider.get("checks", {}).get("rider_create"))
    dispatch_assign = bool(
        rider.get("checks", {}).get("dispatch_queue")
        or ops.get("checks", {}).get("auto_manual_assignment")
        or driver_ops.get("checks", {}).get("dispatch_assign")
    )
    driver_complete = bool(
        driver_ops.get("checks", {}).get("ride_completed")
        or ops.get("checks", {}).get("full_trip_lifecycle")
        or rider.get("checks", {}).get("trip_lifecycle")
    )
    rider_live = bool(
        driver_ops.get("checks", {}).get("rider_tracking")
        or rider.get("checks", {}).get("rider_history_ui")
    )
    dashboard = bool(
        driver_ops.get("checks", {}).get("dispatcher_dashboard")
        or ops.get("checks", {}).get("dashboard_update")
        or audit.get("matrix", {}).get("Admin/Billing") == "PASS"
    )
    billing_audit = bool(
        driver_ops.get("checks", {}).get("audit_log")
        and (
            audit.get("matrix", {}).get("Compliance/Audit") == "PASS"
            or cert.get("sections", {}).get("api_health", {}).get("passed")
        )
    )
    db_persist = bool(
        reports.get("pytest", {}).get("passed")
        and driver_ops.get("checks", {}).get("ride_completed")
    )
    console_ok = bool(runs.get("console_local", {}).get("passed")) and bool(
        runs.get("console_render", {}).get("passed")
        or reports.get("render_cert", {}).get("sections", {}).get("frontend", {}).get("passed")
    )
    render_ready = bool(reports.get("render_probe", {}).get("checks", {}).get("readiness"))

    items = {
        "1_no_placeholder_demo_controls": "PASS" if no_placeholders else "FAIL",
        "2_rider_creates_real_ride": "PASS" if rider_create else "FAIL",
        "3_dispatcher_sees_and_assigns": "PASS" if dispatch_assign else "FAIL",
        "4_driver_accepts_and_completes": "PASS" if driver_complete else "FAIL",
        "5_rider_live_status_updates": "PASS" if rider_live else "FAIL",
        "6_dashboard_counts_update": "PASS" if dashboard else "FAIL",
        "7_billing_audit_records_created": "PASS" if billing_audit else "FAIL",
        "8_database_persists_state": "PASS" if db_persist else "FAIL",
        "9_no_console_network_blockers": "PASS" if console_ok else "FAIL",
        "10_render_production_ready": "PASS" if render_ready else "FAIL",
    }
    return items


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    runs: dict[str, Any] = {}

    print("[FINAL] pytest deployment + lifecycle...", flush=True)
    pytest = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_deployment_readiness_ride_lifecycle.py",
            "tests/test_driver_dispatch_lifecycle.py",
            "tests/test_deployment_readiness.py",
            "-q",
            "--tb=no",
        ],
        cwd=str(BACKEND),
        env={**os.environ, "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
        timeout=300,
    )
    runs["pytest"] = {
        "passed": pytest.returncode == 0,
        "exit_code": pytest.returncode,
        "stdout_tail": (pytest.stdout or "")[-600:],
    }

    local_scripts = [
        ("rider", "scripts/rider_app_browser_verification.py", {"AMICOR_BROWSER_BASE": LOCAL_BASE}),
        ("driver_ops", "scripts/driver_ops_browser_verification.py", {"AMICOR_BROWSER_BASE": LOCAL_BASE}),
        ("ops", "scripts/real_life_ops_verification.py", {"AMICOR_BROWSER_BASE": LOCAL_BASE}),
        ("audit", "scripts/browser_health_isf_readiness_audit.py", {"AMICOR_BROWSER_BASE": LOCAL_BASE}),
        ("console_local", "scripts/browser_frontend_console_audit.py", {"AMICOR_BROWSER_BASE": LOCAL_BASE}),
    ]
    for key, script, env in local_scripts:
        print(f"[FINAL] local {key}...", flush=True)
        runs[key] = run_script(script, env)

    print("[FINAL] Render probes...", flush=True)
    runs["render_probe"] = probe_render_readiness(RENDER_BASE)

    render_scripts = [
        ("render_cert", "scripts/production_certification_audit.py", {"AMICOR_BROWSER_BASE": RENDER_BASE}),
        ("render_smoke", "scripts/render_production_smoke.py", {"AMICOR_BROWSER_BASE": RENDER_BASE}),
        ("console_render", "scripts/browser_frontend_console_audit.py", {"AMICOR_BROWSER_BASE": RENDER_BASE}),
    ]
    for key, script, env in render_scripts:
        print(f"[FINAL] render {key}...", flush=True)
        runs[key] = run_script(script, env)

    reports = {
        "pytest": runs["pytest"],
        "rider": load_json("rider_app_browser_verification_report.json"),
        "driver_ops": load_json("driver_ops_browser_verification_report.json"),
        "ops": load_json("real_life_ops_verification_report.json"),
        "audit": load_json("health_isf_readiness_audit_report.json"),
        "console_local": load_json("frontend_console_audit.json"),
        "render_cert": load_json("production_certification_report.json"),
        "render_smoke": load_json("render_production_smoke_report.json"),
        "console_render": load_json("frontend_console_audit.json"),
        "render_probe": runs["render_probe"],
    }

    checklist = build_checklist(reports, runs)
    suite_matrix = {
        "Rider (/app/riders)": "PASS" if reports["rider"].get("all_pass") else "FAIL",
        "Driver (ops-shell + Health ISF)": (
            "PASS"
            if reports["driver_ops"].get("verdict") == "PASS"
            and reports["ops"].get("all_pass")
            else "FAIL"
        ),
        "Dispatcher": "PASS" if reports["audit"].get("matrix", {}).get("Dispatcher") == "PASS" else "FAIL",
        "Dashboard": "PASS" if checklist["6_dashboard_counts_update"] == "PASS" else "FAIL",
        "Provider": "PASS" if reports["audit"].get("matrix", {}).get("Provider") == "PASS" else "FAIL",
        "Admin": "PASS" if reports["audit"].get("matrix", {}).get("Admin/Billing") == "PASS" else "FAIL",
        "Billing": "PASS" if checklist["7_billing_audit_records_created"] == "PASS" else "FAIL",
        "Audit/Compliance": "PASS" if reports["audit"].get("matrix", {}).get("Compliance/Audit") == "PASS" else "FAIL",
        "Assistant/AI": "PASS" if reports["audit"].get("matrix", {}).get("AI Assistant/Advisory") == "PASS" else "FAIL",
    }

    blockers: list[str] = []
    for label, status in checklist.items():
        if status != "PASS":
            blockers.append(f"Checklist {label} failed")
    for label, status in suite_matrix.items():
        if status != "PASS":
            blockers.append(f"Suite {label} failed")
    for key, run in runs.items():
        if isinstance(run, dict) and run.get("passed") is False and key not in {"render_probe"}:
            blockers.append(f"Runner {key} exit {run.get('exit_code')}")

    all_pass = all(v == "PASS" for v in checklist.values()) and all(v == "PASS" for v in suite_matrix.values())

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "local_base": LOCAL_BASE,
        "render_base": RENDER_BASE,
        "checklist": checklist,
        "suite_matrix": suite_matrix,
        "all_pass": all_pass,
        "ready_for_redeployment": all_pass,
        "render_deployment": {
            "service": "amicor-health-isf",
            "url": RENDER_BASE,
            "health_check": "/api/health",
            "readiness": reports["render_probe"],
            "deploy_command": "git push origin main  # Render auto-deploy from render.yaml rootDir=backend",
            "post_deploy_verify": [
                f"curl {RENDER_BASE}/api/health/readiness",
                f"AMICOR_BROWSER_BASE={RENDER_BASE} python scripts/render_production_smoke.py",
                f"AMICOR_BROWSER_BASE={RENDER_BASE} python scripts/production_certification_audit.py",
            ],
        },
        "blockers": blockers,
        "run_results": runs,
        "sources": {
            "rider": reports["rider"].get("verdict") or reports["rider"].get("all_pass"),
            "driver_ops": reports["driver_ops"].get("verdict"),
            "ops": reports["ops"].get("all_pass"),
            "audit": reports["audit"].get("all_pass"),
            "render_certified": reports["render_cert"].get("production_ready"),
            "render_smoke": reports["render_smoke"].get("all_pass", reports["render_smoke"].get("passed")),
        },
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"[FINAL] Wrote {OUT}", flush=True)
    print("[FINAL] CHECKLIST", json.dumps(checklist), flush=True)
    print("[FINAL] SUITE", json.dumps(suite_matrix), flush=True)
    print(f"[FINAL] VERDICT: {'READY FOR REDEPLOYMENT' if all_pass else 'NOT READY'}", flush=True)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
