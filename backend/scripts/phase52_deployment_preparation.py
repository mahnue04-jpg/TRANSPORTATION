"""Phase 52: Production deployment preparation audit (no deploy).

Validates environment prerequisites, Alembic migration readiness, document storage,
module endpoints, and Render production probes. Does not modify transportation logic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
REPORT_DIR = REPO_ROOT
DATA_DIR = BACKEND_ROOT / "data"

PRODUCTION_REQUIRED_ENV = [
    "DATABASE_URL",
    "SECRET_KEY",
    "JWT_SECRET",
    "ALLOWED_ORIGINS",
    "AMICOR_PUBLIC_URL",
    "APP_VERSION",
]

RENDER_RECOMMENDED_ENV = [
    "AMICOR_ENVIRONMENT",
    "AMICOR_SEED_PASSWORD",
    "LOG_LEVEL",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "HEALTH_ISF_WS_MAX_ORG_CONNECTIONS",
    "HEALTH_ISF_WS_MAX_USER_CONNECTIONS",
    "HEALTH_ISF_AUTO_DISPATCH_ENABLED",
]

OPTIONAL_INTEGRATIONS = [
    "OPENAI_API_KEY",
    "HEALTH_ISF_STRIPE_ENABLED",
    "STRIPE_SECRET_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "SENTRY_DSN",
    "ASSISTANT_REDIS_URL",
]

DURABLE_STORAGE_VALUES = {"azure_blob", "s3", "gcs", "render_disk", "blob", "object_storage"}

MODULE_QUERY_PARAMS = {
    "/api/health-isf/customers/workspace/history": {"rider_phone": "9175550100"},
}

MODULE_ENDPOINTS = {
    "rider": [
        ("GET", "/api/health-isf/customer-requests", "dispatcher"),
        ("GET", "/api/health-isf/rides", "dispatcher"),
        ("GET", "/api/health-isf/customer-requests/metrics", "dispatcher"),
    ],
    "driver": [
        ("GET", "/api/health-isf/drivers", "dispatcher"),
        ("GET", "/api/health-isf/drivers/{driver_id}/earnings", "dispatcher"),
        ("GET", "/api/health-isf/drivers/{driver_id}/active-ride", "driver"),
    ],
    "dispatch": [
        ("GET", "/api/health-isf/dispatch/queue", "dispatcher"),
        ("GET", "/api/health-isf/dispatch/active-assignments", "dispatcher"),
        ("GET", "/api/health-isf/intelligence/recommendations", "dispatcher"),
    ],
    "admin": [
        ("GET", "/api/health-isf/dashboard", "dispatcher"),
        ("GET", "/api/health-isf/operations/admin-revenue", "admin"),
        ("GET", "/api/health-isf/operations/runtime-state", "dispatcher"),
    ],
    "billing": [
        ("GET", "/api/health-isf/operations/billing-handoffs", "dispatcher"),
        ("GET", "/api/health-isf/operations/admin-revenue", "admin"),
        ("GET", "/api/health-isf/operations/timeline", "dispatcher"),
    ],
}

PUBLIC_ENDPOINTS = [
    ("GET", "/api/health/live"),
    ("GET", "/api/health/readiness"),
    ("GET", "/api/runtime/topology"),
    ("GET", "/docs"),
]

RENDER_BASE = os.getenv("AMICOR_PUBLIC_URL", "https://amicor-health-isf-py.onrender.com").rstrip("/")
SEED_PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def check_env_template() -> dict[str, Any]:
    template_path = REPO_ROOT / ".env.template"
    documented: set[str] = set()
    if template_path.exists():
        for line in template_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            documented.add(line.split("=", 1)[0].strip())

    missing_from_template = [v for v in PRODUCTION_REQUIRED_ENV if v not in documented]
    return {
        "template_path": str(template_path),
        "documented_var_count": len(documented),
        "production_required_documented": len(missing_from_template) == 0,
        "missing_from_template": missing_from_template,
    }


def check_local_production_env_simulation() -> dict[str, Any]:
    """Simulate production env validation using DeploymentReadinessChecker patterns."""
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.deployment.readiness import DeploymentReadinessChecker

    # Snapshot and restore env
    snapshot = dict(os.environ)
    try:
        # Use production-like values for structural validation only
        os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@host:5432/amicor")
        os.environ.setdefault("SECRET_KEY", "phase52-check-secret-key-not-for-production-use")
        os.environ.setdefault("JWT_SECRET", "phase52-check-jwt-secret-not-for-production-use")
        os.environ.setdefault("ALLOWED_ORIGINS", RENDER_BASE)
        os.environ.setdefault("AMICOR_PUBLIC_URL", RENDER_BASE)
        os.environ.setdefault("APP_VERSION", "phase52.validation.1")
        report = DeploymentReadinessChecker.build_readiness_report(db_ok=True)
        return {
            "checker_overall_status": report.get("overall_status"),
            "checker_score": report.get("score"),
            "blocked_reasons": report.get("blocked_reasons", []),
            "config_checks": report.get("config_checks", {}),
        }
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def check_document_storage() -> dict[str, Any]:
    backend = os.getenv("PLATFORM_OPS_DOCUMENT_STORAGE", "local_dev").strip().lower()
    durable = backend in DURABLE_STORAGE_VALUES
    return {
        "PLATFORM_OPS_DOCUMENT_STORAGE": backend,
        "durable_configured": durable,
        "production_ready": durable,
        "detail": (
            "Durable object storage backend configured"
            if durable
            else (
                "Only local_dev / pending_production adapters exist — "
                "Render ephemeral disk is not durable for driver onboarding documents"
            )
        ),
        "blocker": not durable,
    }


def check_alembic_heads() -> dict[str, Any]:
    result = subprocess.run(
        ["alembic", "heads"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    heads = [line.strip() for line in result.stdout.splitlines() if "(head)" in line]
    single_head = len(heads) == 1
    return {
        "exit_code": result.returncode,
        "heads": heads,
        "single_head": single_head,
        "ready": result.returncode == 0 and single_head,
        "detail": "Single Alembic head" if single_head else "Multiple or missing Alembic heads",
    }


def check_alembic_clean_upgrade() -> dict[str, Any]:
    """Attempt alembic upgrade head on empty SQLite — detects migration graph gaps."""
    stamp = _utc_stamp()
    db_path = DATA_DIR / f"phase52_alembic_{stamp}.db"
    if db_path.exists():
        db_path.unlink()
    db_url = f"sqlite:///{db_path.as_posix()}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    success = result.returncode == 0
    error_tail = (result.stderr or result.stdout or "").strip().splitlines()
    error_summary = error_tail[-1] if error_tail else ""
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass
    return {
        "attempted": True,
        "success": success,
        "ready": success,
        "error_summary": error_summary if not success else "",
        "detail": (
            "Clean-database alembic upgrade head succeeded"
            if success
            else (
                "Clean-database alembic upgrade head FAILED — "
                "migration chain may assume tables created outside Alembic (ensure_health_isf_schema)"
            )
        ),
        "blocker": not success,
    }


def check_local_modules() -> dict[str, Any]:
    stamp = _utc_stamp()
    db_path = DATA_DIR / f"phase52_modules_{stamp}.db"
    if db_path.exists():
        db_path.unlink()

    os.environ["TESTING"] = "true"
    os.environ["DB_FILENAME"] = str(db_path)
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    sys.path.insert(0, str(BACKEND_ROOT))

    from fastapi.testclient import TestClient  # noqa: E402

    from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users  # noqa: E402
    from app.db.models import User as PlatformUser  # noqa: E402
    from app.db.session import SessionLocal  # noqa: E402
    from app.main import app  # noqa: E402
    from app.modules.health_isf.models import HealthISFDriver  # noqa: E402

    ensure_auth_schema()
    seed_default_users()

    client = TestClient(app)
    tokens: dict[str, str] = {}
    for role, email in (
        ("dispatcher", "dispatcher@amicor.local"),
        ("admin", "admin@amicor.local"),
        ("driver", "driver@amicor.local"),
        ("rider", "rider@amicor.local"),
    ):
        resp = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
        tokens[role] = resp.json().get("access_token", "") if resp.status_code == 200 else ""

    with SessionLocal() as db:
        driver = db.query(HealthISFDriver).first()
        driver_id = str(driver.id) if driver else ""

    modules: dict[str, Any] = {}
    for module_name, endpoints in MODULE_ENDPOINTS.items():
        module_checks = []
        for method, path, role in endpoints:
            resolved = path.replace("{driver_id}", driver_id) if "{driver_id}" in path else path
            headers = {"Authorization": f"Bearer {tokens.get(role, '')}"}
            params = MODULE_QUERY_PARAMS.get(path, {})
            if method == "GET":
                resp = client.get(resolved, headers=headers, params=params)
            else:
                resp = client.request(method, resolved, headers=headers, params=params)
            module_checks.append(
                {
                    "method": method,
                    "path": resolved,
                    "role": role,
                    "status": resp.status_code,
                    "pass": resp.status_code in {200, 201},
                }
            )
        modules[module_name] = {
            "enabled": all(c["pass"] for c in module_checks),
            "endpoints": module_checks,
        }

    # Platform ops router registered
    po_resp = client.get("/api/platform-ops/driver-onboarding/document-categories")
    platform_ops = {
        "router_mounted": po_resp.status_code in {200, 401, 403},
        "document_categories_status": po_resp.status_code,
        "enabled": po_resp.status_code == 200 or po_resp.status_code == 401,
    }

    public_checks = []
    for method, path in PUBLIC_ENDPOINTS:
        resp = client.get(path) if method == "GET" else client.request(method, path)
        public_checks.append({"path": path, "status": resp.status_code, "pass": resp.status_code == 200})

    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass

    all_modules = all(m["enabled"] for m in modules.values())
    return {
        "modules": modules,
        "platform_ops": platform_ops,
        "public_endpoints": public_checks,
        "all_transport_modules_enabled": all_modules,
        "ready": all_modules and all(p["pass"] for p in public_checks),
    }


def probe_render() -> dict[str, Any]:
    import httpx

    report: dict[str, Any] = {"base_url": RENDER_BASE, "reachable": False, "checks": {}}
    try:
        live = httpx.get(f"{RENDER_BASE}/api/health/live", timeout=120)
        ready = httpx.get(f"{RENDER_BASE}/api/health/readiness", timeout=120)
        po = httpx.get(f"{RENDER_BASE}/api/platform-ops/driver-onboarding/document-categories", timeout=120)
        report["platform_ops"] = {
            "status": po.status_code,
            "enabled": po.status_code in {200, 401, 403},
            "migration_likely_applied": po.status_code != 404,
            "detail": (
                "Platform Ops routes mounted"
                if po.status_code != 404
                else "Platform Ops routes not found — apply migration 20260731_driver_onboarding_s1"
            ),
        }
        report["reachable"] = live.status_code == 200
        ready_body = ready.json() if ready.headers.get("content-type", "").startswith("application/json") else {}
        report["checks"]["live"] = live.status_code == 200
        report["checks"]["readiness"] = ready.status_code == 200 and ready_body.get("overall_status") == "ready"
        report["readiness_body"] = {
            "overall_status": ready_body.get("overall_status"),
            "score": ready_body.get("score"),
            "blocked_reasons": ready_body.get("blocked_reasons", []),
            "database_connected": (ready_body.get("database") or {}).get("connected"),
        }

        login_resp = httpx.post(
            f"{RENDER_BASE}/api/auth/login",
            json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
            timeout=120,
        )
        if login_resp.status_code != 200:
            report["checks"]["auth"] = False
            report["auth_detail"] = (
                "Render seed login failed (401) — AMICOR_SEED_PASSWORD likely rotated; "
                "set AMICOR_SEED_PASSWORD env locally to probe authenticated endpoints"
            )
            report["module_probes"] = {}
            report["checks"]["all_modules_responding"] = None
            return report

        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        report["checks"]["auth"] = True

        admin_login = httpx.post(
            f"{RENDER_BASE}/api/auth/login",
            json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
            timeout=120,
        )
        admin_token = admin_login.json().get("access_token", "") if admin_login.status_code == 200 else ""
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        with httpx.Client(timeout=120) as http:
            drivers = http.get(f"{RENDER_BASE}/api/health-isf/drivers", headers=headers)
            driver_id = ""
            if drivers.status_code == 200:
                items = drivers.json()
                if isinstance(items, list) and items:
                    driver_id = str(items[0].get("id") or "")

            module_probes: dict[str, Any] = {}
            for module_name, endpoints in MODULE_ENDPOINTS.items():
                rows = []
                for method, path, role in endpoints:
                    resolved = path.replace("{driver_id}", driver_id) if "{driver_id}" in path else path
                    hdrs = admin_headers if role == "admin" else headers
                    params = MODULE_QUERY_PARAMS.get(path, {})
                    resp = http.get(f"{RENDER_BASE}{resolved}", headers=hdrs, params=params)
                    rows.append({"path": resolved, "status": resp.status_code, "pass": resp.status_code == 200})
                module_probes[module_name] = {
                    "enabled": all(r["pass"] for r in rows),
                    "endpoints": rows,
                }
            report["module_probes"] = module_probes
            report["checks"]["all_modules_responding"] = all(
                m["enabled"] for m in module_probes.values()
            )

    except Exception as exc:
        report["error"] = str(exc)
    return report


def build_render_checklist() -> list[str]:
    return [
        "Phase A — Infrastructure",
        "[ ] Render PostgreSQL provisioned (amicor-health-isf-db or equivalent)",
        "[ ] Generate unique SECRET_KEY and JWT_SECRET (distinct values)",
        "[ ] Confirm render.yaml rootDir=backend, healthCheckPath=/api/health/readiness",
        "",
        "Phase B — Environment (Render dashboard)",
        "[ ] DATABASE_URL → PostgreSQL internal connection string",
        "[ ] SECRET_KEY, JWT_SECRET → cryptographically random",
        "[ ] ALLOWED_ORIGINS → https://amicor-health-isf-py.onrender.com (no wildcard)",
        "[ ] AMICOR_PUBLIC_URL → https URL, no trailing slash",
        "[ ] APP_VERSION → release tag (e.g. 2026.08.01-phase52.1)",
        "[ ] AMICOR_ENVIRONMENT=production",
        "[ ] AMICOR_SEED_PASSWORD → rotated from dev default",
        "[ ] LOG_LEVEL=INFO",
        "[ ] DB_POOL_SIZE=10, DB_MAX_OVERFLOW=20",
        "[ ] HEALTH_ISF_AUTO_DISPATCH_ENABLED=true",
        "",
        "Phase C — Document storage (driver onboarding)",
        "[ ] Provision durable object storage (Azure Blob / S3 / Render persistent disk)",
        "[ ] Set PLATFORM_OPS_DOCUMENT_STORAGE to production backend (not local_dev)",
        "[ ] Verify upload + retention policy for onboarding documents",
        "",
        "Phase D — Database migrations",
        "[ ] Snapshot PostgreSQL before deploy",
        "[ ] releaseCommand: alembic upgrade heads (verify on staging first)",
        "[ ] Confirm alembic current matches head: 20260731_driver_onboarding_s1",
        "[ ] If fresh DB: ensure health_isf base schema exists before rider_scheduling migration",
        "",
        "Phase E — Deploy",
        "[ ] Deploy web service; wait for /api/health/live → 200",
        "[ ] Confirm /api/health/readiness → overall_status=ready",
        "[ ] Confirm /api/runtime/topology → production HTTPS/WSS URLs",
        "",
        "Phase F — Post-deploy verification",
        "[ ] python scripts/render_production_smoke.py → verdict GO",
        "[ ] Rider / Driver / Dispatch / Admin / Billing API probes → 200",
        "[ ] WebSocket connects after dispatcher login",
        "[ ] Phase 51 E2E validation on staging clone (optional gate)",
        "",
        "Phase G — Sign-off",
        "[ ] No blocked_reasons on readiness endpoint",
        "[ ] Seed passwords rotated",
        "[ ] Production promoted",
    ]


def decide_go_no_go(report: dict[str, Any]) -> tuple[str, list[str]]:
    blockers: list[str] = []

    alembic_clean = report.get("alembic_clean_upgrade", {})
    if alembic_clean.get("blocker"):
        blockers.append(
            f"Alembic clean DB migration failed: {alembic_clean.get('error_summary', 'unknown')}"
        )

    storage = report.get("document_storage", {})
    if storage.get("blocker"):
        blockers.append(f"Durable document storage not configured: {storage.get('detail')}")

    render = report.get("render_probe", {})
    if not render.get("reachable"):
        blockers.append(f"Render production URL unreachable: {RENDER_BASE}")
    elif not (render.get("checks") or {}).get("readiness"):
        blockers.append("Render /api/health/readiness is not overall_status=ready")

    render_modules = (render.get("checks") or {}).get("all_modules_responding")
    if render_modules is False:
        blockers.append("One or more production module API probes failed on Render")

    local_modules = report.get("local_modules", {})
    if not local_modules.get("all_transport_modules_enabled"):
        blockers.append("Local module endpoint verification failed — router or auth regression")

    po = render.get("platform_ops") or {}
    if po.get("status") == 404:
        blockers.append(
            "Platform Ops driver onboarding routes return 404 on Render — "
            "migration 20260731_driver_onboarding_s1 may not be applied"
        )

    if blockers:
        return "NO-GO", blockers
    return "GO", []


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    stamp = _utc_stamp()
    json_path = REPORT_DIR / f"PHASE_52_DEPLOYMENT_PREPARATION_{stamp}.json"
    md_path = REPORT_DIR / f"PHASE_52_DEPLOYMENT_PREPARATION_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    verdict = report.get("verdict", "NO-GO")
    lines = [
        "# Phase 52 — Production Deployment Preparation Report",
        "",
        f"**Verdict:** {verdict}",
        f"**Timestamp:** {report.get('timestamp')}",
        f"**Render target:** {RENDER_BASE}",
        "",
    ]
    if report.get("blockers"):
        lines.extend(["## Blockers (deployment stopped)", ""])
        for b in report["blockers"]:
            lines.append(f"- {b}")
        lines.append("")

    lines.extend(["## Checks", ""])
    for name, check in report.get("checks_summary", {}).items():
        status = "PASS" if check.get("pass") else "FAIL"
        lines.append(f"- [{status}] **{name}**: {check.get('detail', '')}")

    lines.extend(["", "## Render Deployment Checklist", ""])
    lines.extend(report.get("render_checklist", []))

    lines.extend(["", "## Evidence", "", "```json"])
    lines.append(json.dumps(report.get("evidence", {}), indent=2))
    lines.append("```")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    timestamp = datetime.now(timezone.utc).isoformat()

    env_template = check_env_template()
    env_checker = check_local_production_env_simulation()
    document_storage = check_document_storage()
    alembic_heads = check_alembic_heads()
    alembic_clean = check_alembic_clean_upgrade()
    local_modules = check_local_modules()
    render_probe = probe_render()
    render_checklist = build_render_checklist()

    report_core = {
        "phase": 52,
        "timestamp": timestamp,
        "render_target": RENDER_BASE,
        "env_template": env_template,
        "env_checker_simulation": env_checker,
        "document_storage": document_storage,
        "alembic_heads": alembic_heads,
        "alembic_clean_upgrade": alembic_clean,
        "local_modules": local_modules,
        "render_probe": render_probe,
        "render_checklist": render_checklist,
    }

    verdict, blockers = decide_go_no_go(report_core)
    report_core["verdict"] = verdict
    report_core["blockers"] = blockers
    report_core["checks_summary"] = {
        "env_template_documents_production_vars": {
            "pass": env_template.get("production_required_documented"),
            "detail": "All production-required vars documented in .env.template",
        },
        "alembic_single_head": {
            "pass": alembic_heads.get("single_head"),
            "detail": alembic_heads.get("detail", ""),
        },
        "alembic_clean_db_upgrade": {
            "pass": alembic_clean.get("success"),
            "detail": alembic_clean.get("detail", ""),
        },
        "durable_document_storage": {
            "pass": document_storage.get("durable_configured"),
            "detail": document_storage.get("detail", ""),
        },
        "local_transport_modules": {
            "pass": local_modules.get("all_transport_modules_enabled"),
            "detail": "Rider, Driver, Dispatch, Admin, Billing respond locally",
        },
        "render_readiness": {
            "pass": (render_probe.get("checks") or {}).get("readiness"),
            "detail": f"Render readiness: {(render_probe.get('readiness_body') or {}).get('overall_status')}",
        },
        "render_module_apis": {
            "pass": (render_probe.get("checks") or {}).get("all_modules_responding"),
            "detail": "Production module API probes on Render",
        },
    }
    report_core["evidence"] = {
        "alembic_heads": alembic_heads.get("heads"),
        "render_readiness": render_probe.get("readiness_body"),
        "render_modules": render_probe.get("module_probes"),
        "local_modules": local_modules.get("modules"),
        "platform_ops_local": local_modules.get("platform_ops"),
        "platform_ops_render": render_probe.get("platform_ops"),
    }

    json_path, md_path = write_reports(report_core)
    print(json.dumps(report_core, indent=2))
    print(f"\nReport written: {json_path}")
    print(f"Markdown report: {md_path}")
    print(f"\nVERDICT: {verdict}")
    if blockers:
        print("BLOCKERS:")
        for b in blockers:
            print(f"  - {b}")
    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
