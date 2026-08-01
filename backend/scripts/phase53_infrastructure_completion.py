"""Phase 53: Production infrastructure completion validation."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
REPORT_DIR = REPO_ROOT
DATA_DIR = BACKEND_ROOT / "data"

STAGING_BASE = os.getenv(
    "AMICOR_STAGING_URL",
    os.getenv("AMICOR_PUBLIC_URL", "https://amicor-health-isf-py.onrender.com"),
).rstrip("/")

PLATFORM_OPS_ENDPOINTS = [
    ("GET", "/api/platform-ops/driver-onboarding/document-categories", None, None),
    ("POST", "/api/platform-ops/driver-onboarding/applications", "admin", {"organization_id": "{org_id}"}),
]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def check_alembic_clean_upgrade() -> dict:
    stamp = _utc_stamp()
    db_path = DATA_DIR / f"phase53_alembic_{stamp}.db"
    if db_path.exists():
        db_path.unlink()
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    heads = subprocess.run(
        ["alembic", "heads"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    head_lines = [line.strip() for line in heads.stdout.splitlines() if "(head)" in line]
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass
    error_lines = (result.stderr or result.stdout or "").strip().splitlines()
    return {
        "success": result.returncode == 0,
        "head": head_lines[0] if head_lines else "",
        "error_summary": error_lines[-1] if error_lines and result.returncode != 0 else "",
    }


def check_document_storage() -> dict:
    import tempfile

    sys.path.insert(0, str(BACKEND_ROOT))
    from app.modules.platform_ops.storage import (
        STORAGE_BACKEND_RENDER_DISK,
        RenderDiskDocumentStorage,
        get_document_storage,
    )

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PLATFORM_OPS_DOCUMENT_STORAGE"] = STORAGE_BACKEND_RENDER_DISK
        os.environ["PLATFORM_OPS_DOCUMENT_STORAGE_PATH"] = tmp
        storage = get_document_storage()
        payload = b"phase53-storage-proof-" + uuid4().bytes
        org_id = str(uuid4())
        app_id = str(uuid4())
        backend, storage_ref, byte_size = storage.store(
            organization_id=org_id,
            application_id=app_id,
            category="drivers_license_front",
            filename="proof.pdf",
            content_type="application/pdf",
            stream=io.BytesIO(payload),
        )
        retrieved, _ = storage.retrieve(storage_ref=storage_ref)
        storage.delete(storage_ref=storage_ref)
        after_delete_missing = False
        try:
            storage.retrieve(storage_ref=storage_ref)
        except FileNotFoundError:
            after_delete_missing = True

    return {
        "backend": backend,
        "byte_size": byte_size,
        "upload_ok": byte_size == len(payload),
        "download_ok": retrieved == payload,
        "delete_ok": after_delete_missing,
        "render_disk_class": isinstance(storage, RenderDiskDocumentStorage),
        "factory_ok": backend == STORAGE_BACKEND_RENDER_DISK,
        "ready": (
            backend == STORAGE_BACKEND_RENDER_DISK
            and retrieved == payload
            and after_delete_missing
        ),
    }


def check_platform_ops_local() -> dict:
    stamp = _utc_stamp()
    db_path = DATA_DIR / f"phase53_platform_ops_{stamp}.db"
    if db_path.exists():
        db_path.unlink()

    docs_path = DATA_DIR / f"phase53_docs_{stamp}"
    docs_path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["TESTING"] = "true"
    env["AMICOR_ENVIRONMENT"] = "staging"
    env["PLATFORM_OPS_DOCUMENT_STORAGE"] = "render_disk"
    env["PLATFORM_OPS_DOCUMENT_STORAGE_PATH"] = str(docs_path)
    env["DB_FILENAME"] = str(db_path)
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    migrate = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if migrate.returncode != 0:
        return {
            "environment": "local_staging_simulation",
            "error": "alembic upgrade failed before platform ops probe",
            "detail": (migrate.stderr or migrate.stdout or "")[-500:],
            "ready": False,
        }

    os.environ.update(
        {
            "TESTING": "true",
            "AMICOR_ENVIRONMENT": "staging",
            "PLATFORM_OPS_DOCUMENT_STORAGE": "render_disk",
            "PLATFORM_OPS_DOCUMENT_STORAGE_PATH": str(docs_path),
            "DB_FILENAME": str(db_path),
            "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        }
    )

    sys.path.insert(0, str(BACKEND_ROOT))
    from fastapi.testclient import TestClient

    from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
    from app.db.session import SessionLocal
    from app.main import app

    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    org_id = "00000000-0000-0000-0000-00000000a1c0"

    admin_login = client.post("/api/auth/login", json={"email": "admin@amicor.local", "password": SEED_PASSWORD})
    if admin_login.status_code != 200:
        return {
            "environment": "local_staging_simulation",
            "error": f"admin login failed: {admin_login.status_code}",
            "ready": False,
        }
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    if not org_id:
        return {
            "environment": "local_staging_simulation",
            "error": "organization_id missing for seeded admin user",
            "ready": False,
        }

    endpoints = [
        ("GET", "/api/platform-ops/driver-onboarding/document-categories", None, 200),
        ("POST", "/api/platform-ops/driver-onboarding/applications", {"organization_id": org_id}, 200),
    ]
    results = []
    application_id = ""
    applicant_token = ""
    for method, path, body, expected in endpoints:
        if method == "GET":
            resp = client.get(path, headers=admin_headers if admin_token else None)
        else:
            resp = client.post(path, json=body, headers=admin_headers)
        if path.endswith("/applications") and resp.status_code == 200:
            application_id = resp.json().get("application", {}).get("id", "")
            applicant_token = resp.json().get("applicant_access_token", "")
        results.append({"path": path, "status": resp.status_code, "pass": resp.status_code == expected})

    upload_ok = False
    download_ok = False
    if application_id and applicant_token:
        files = {"file": ("license.pdf", b"%PDF-1.4 phase53", "application/pdf")}
        upload = client.post(
            f"/api/platform-ops/driver-onboarding/applications/{application_id}/documents",
            params={"category": "drivers_license_front"},
            headers={"X-Applicant-Token": applicant_token},
            files=files,
        )
        upload_ok = upload.status_code == 200
        document_id = upload.json().get("id", "") if upload_ok else ""
        if document_id:
            download = client.get(
                f"/api/platform-ops/driver-onboarding/applications/{application_id}/documents/{document_id}/download",
                headers={"X-Applicant-Token": applicant_token},
            )
            download_ok = download.status_code == 200 and download.content == b"%PDF-1.4 phase53"
            results.append(
                {
                    "path": f"/applications/{application_id}/documents/upload",
                    "status": upload.status_code,
                    "pass": upload_ok,
                }
            )
            results.append(
                {
                    "path": f"/applications/{application_id}/documents/{document_id}/download",
                    "status": download.status_code,
                    "pass": download_ok,
                }
            )

    list_resp = client.get(
        "/api/platform-ops/driver-onboarding/applications",
        headers=admin_headers,
        params={"organization_id": org_id},
    )
    results.append(
        {
            "path": "/api/platform-ops/driver-onboarding/applications",
            "status": list_resp.status_code,
            "pass": list_resp.status_code == 200,
        }
    )

    all_pass = all(item["pass"] for item in results) and upload_ok and download_ok
    return {
        "environment": "local_staging_simulation",
        "endpoints": results,
        "upload_download_verified": upload_ok and download_ok,
        "all_endpoints_200": all(item["pass"] for item in results),
        "ready": all_pass,
    }


def probe_staging_render() -> dict:
    import httpx

    report: dict = {"base_url": STAGING_BASE, "reachable": False, "endpoints": []}
    try:
        live = httpx.get(f"{STAGING_BASE}/api/health/live", timeout=120)
        report["reachable"] = live.status_code == 200
        categories = httpx.get(
            f"{STAGING_BASE}/api/platform-ops/driver-onboarding/document-categories",
            timeout=120,
        )
        report["endpoints"].append(
            {
                "path": "/api/platform-ops/driver-onboarding/document-categories",
                "status": categories.status_code,
                "pass": categories.status_code == 200,
            }
        )
        report["platform_ops_deployed"] = categories.status_code == 200
        report["ready"] = report["reachable"] and categories.status_code == 200
        if categories.status_code == 404:
            report["detail"] = (
                "Platform Ops not yet deployed to staging Render — push branch and run releaseCommand"
            )
    except Exception as exc:
        report["error"] = str(exc)
        report["ready"] = False
    return report


def decide_verdict(report: dict) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if not report["alembic_clean_upgrade"].get("success"):
        blockers.append(
            "Alembic clean-database upgrade failed: "
            + report["alembic_clean_upgrade"].get("error_summary", "unknown")
        )
    if not report["document_storage"].get("ready"):
        blockers.append("Production document storage adapter failed upload/download verification")
    if not report["platform_ops_local"].get("ready"):
        blockers.append("Local staging Platform Ops endpoints or upload/download failed")
    staging = report.get("staging_render_probe", {})
    if staging.get("reachable") and not staging.get("platform_ops_deployed"):
        blockers.append(
            "Platform Ops returns 404 on staging Render — deploy infrastructure branch before production"
        )
    if blockers:
        return "NO-GO", blockers
    if not staging.get("platform_ops_deployed"):
        return "NO-GO", [
            "Infrastructure verified locally; staging Render deploy pending — Platform Ops still 404 remotely"
        ]
    return "GO", []


def write_reports(report: dict) -> tuple[Path, Path]:
    stamp = _utc_stamp()
    json_path = REPORT_DIR / f"PHASE_53_INFRASTRUCTURE_COMPLETION_{stamp}.json"
    md_path = REPORT_DIR / f"PHASE_53_INFRASTRUCTURE_COMPLETION_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Phase 53 — Production Infrastructure Completion",
        "",
        f"**Verdict:** {report.get('verdict')}",
        f"**Timestamp:** {report.get('timestamp')}",
        "",
    ]
    if report.get("blockers"):
        lines.extend(["## Remaining blockers", ""])
        for item in report["blockers"]:
            lines.append(f"- {item}")
        lines.append("")
    lines.extend(["## Infrastructure checks", ""])
    for name, check in report.get("checks_summary", {}).items():
        status = "PASS" if check.get("pass") else "FAIL"
        lines.append(f"- [{status}] **{name}**: {check.get('detail', '')}")
    lines.extend(["", "## Staging deploy notes", ""])
    lines.extend(report.get("staging_deploy_notes", []))
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    alembic = check_alembic_clean_upgrade()
    storage = check_document_storage()
    platform_ops_local = check_platform_ops_local()
    staging_probe = probe_staging_render()

    report = {
        "phase": 53,
        "timestamp": timestamp,
        "staging_url": STAGING_BASE,
        "alembic_clean_upgrade": alembic,
        "document_storage": storage,
        "platform_ops_local": platform_ops_local,
        "staging_render_probe": staging_probe,
        "staging_deploy_notes": [
            "1. Attach Render persistent disk mounted at /data/onboarding_docs",
            "2. Set PLATFORM_OPS_DOCUMENT_STORAGE=render_disk on staging service",
            "3. Deploy branch with releaseCommand: alembic upgrade heads",
            "4. Re-run phase53 script — staging document-categories must return 200",
            "5. Do not promote to production until verdict GO with staging probe passing",
        ],
        "checks_summary": {
            "alembic_clean_db": {
                "pass": alembic.get("success"),
                "detail": alembic.get("head") or alembic.get("error_summary", ""),
            },
            "render_disk_storage": {
                "pass": storage.get("ready"),
                "detail": f"backend={storage.get('backend')} upload/download/delete verified",
            },
            "platform_ops_local_staging": {
                "pass": platform_ops_local.get("ready"),
                "detail": "All Platform Ops endpoints HTTP 200 locally with staging config",
            },
            "platform_ops_staging_render": {
                "pass": staging_probe.get("platform_ops_deployed"),
                "detail": staging_probe.get("detail", f"probe status={staging_probe.get('endpoints')}"),
            },
        },
    }
    verdict, blockers = decide_verdict(report)
    report["verdict"] = verdict
    report["blockers"] = blockers

    json_path, md_path = write_reports(report)
    print(json.dumps(report, indent=2))
    print(f"\nReport: {json_path}")
    print(f"Markdown: {md_path}")
    print(f"\nVERDICT: {verdict}")
    for item in blockers:
        print(f"  BLOCKER: {item}")

    # Re-run phase52 audit if infrastructure passes locally
    if alembic.get("success") and storage.get("ready"):
        os.environ["PLATFORM_OPS_DOCUMENT_STORAGE"] = "render_disk"
        phase52 = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "phase52_deployment_preparation.py")],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        report["phase52_rerun_exit_code"] = phase52.returncode
        tail = (phase52.stdout or "").strip().splitlines()[-5:]
        report["phase52_rerun_tail"] = tail

    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
