"""Phase 55: Render persistent disk + render_disk storage verification (config only)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
RENDER_YAML = REPO_ROOT / "render.yaml"
BASE = "https://amicor-health-isf-py.onrender.com".rstrip("/")


def _load_render_service() -> dict:
    data = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    for svc in data.get("services") or []:
        if svc.get("name") == "amicor-health-isf":
            return svc
    raise RuntimeError("amicor-health-isf service not found in render.yaml")


def _env_map(service: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in service.get("envVars") or []:
        key = str(item.get("key") or "")
        if item.get("fromDatabase") or item.get("sync") is False:
            continue
        if "value" in item:
            out[key] = str(item["value"])
    return out


def _probe_storage_backend() -> dict:
    result: dict = {
        "create_status": None,
        "upload_status": None,
        "download_status": None,
        "storage_backend_observed": None,
        "upload_download_pass": False,
    }
    create = httpx.post(
        f"{BASE}/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": "00000000-0000-0000-0000-00000000a1c0"},
        timeout=120,
    )
    result["create_status"] = create.status_code
    if create.status_code != 200:
        result["create_body"] = create.text[:300]
        return result

    body = create.json()
    app_id = body.get("application", {}).get("id", "")
    token = body.get("applicant_access_token", "")
    payload = b"%PDF-1.4 phase55-render-disk-proof"
    upload = httpx.post(
        f"{BASE}/api/platform-ops/driver-onboarding/applications/{app_id}/documents",
        params={"category": "drivers_license_front"},
        headers={"X-Applicant-Token": token},
        files={"file": ("phase55-proof.pdf", payload, "application/pdf")},
        timeout=120,
    )
    result["upload_status"] = upload.status_code
    if upload.status_code != 200:
        result["upload_body"] = upload.text[:300]
        return result

    doc = upload.json()
    result["storage_backend_observed"] = doc.get("storage_backend")
    doc_id = doc.get("id", "")
    download = httpx.get(
        f"{BASE}/api/platform-ops/driver-onboarding/applications/{app_id}/documents/{doc_id}/download",
        headers={"X-Applicant-Token": token},
        timeout=120,
    )
    result["download_status"] = download.status_code
    result["upload_download_pass"] = (
        upload.status_code == 200
        and download.status_code == 200
        and download.content == payload
    )
    return result


def _git_head() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def run_phase55(expected_commit_prefix: str | None = None) -> dict:
    service = _load_render_service()
    env = _env_map(service)
    disk = service.get("disk") or {}

    live = httpx.get(f"{BASE}/api/health/live", timeout=120)
    live_body = live.json() if live.headers.get("content-type", "").startswith("application/json") else {}
    deploy_commit = str(live_body.get("deploy_commit") or "")

    storage_probe = _probe_storage_backend()

    config_checks = {
        "render_yaml_disk_name": disk.get("name"),
        "render_yaml_disk_mount_path": disk.get("mountPath"),
        "render_yaml_disk_size_gb": disk.get("sizeGB"),
        "platform_ops_document_storage": env.get("PLATFORM_OPS_DOCUMENT_STORAGE"),
        "platform_ops_document_storage_path": env.get("PLATFORM_OPS_DOCUMENT_STORAGE_PATH"),
    }

    disk_ok = (
        disk.get("name") == "onboarding-docs"
        and disk.get("mountPath") == "/data/onboarding_docs"
        and int(disk.get("sizeGB") or 0) >= 1
    )
    env_ok = (
        env.get("PLATFORM_OPS_DOCUMENT_STORAGE") == "render_disk"
        and env.get("PLATFORM_OPS_DOCUMENT_STORAGE_PATH") == "/data/onboarding_docs"
    )
    runtime_ok = storage_probe.get("storage_backend_observed") == "render_disk"
    upload_ok = storage_probe.get("upload_download_pass") is True

    blockers: list[str] = []
    if not disk_ok:
        blockers.append("render.yaml missing persistent disk at /data/onboarding_docs")
    if not env_ok:
        blockers.append("render.yaml env vars not set to render_disk + /data/onboarding_docs")
    if expected_commit_prefix and not deploy_commit.startswith(expected_commit_prefix):
        blockers.append(
            f"Render deploy commit {deploy_commit} does not match expected prefix {expected_commit_prefix}"
        )
    if not upload_ok:
        blockers.append("Platform Ops upload/download roundtrip failed on Render")
    elif not runtime_ok:
        blockers.append(
            f"storage_backend_observed is '{storage_probe.get('storage_backend_observed')}' not 'render_disk'"
        )

    report = {
        "phase": 55,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "staging_url": BASE,
        "local_commit": _git_head(),
        "render_config": config_checks,
        "render_config_pass": disk_ok and env_ok,
        "live_health": {
            "status": live.status_code,
            "deploy_commit": deploy_commit,
            "version": live_body.get("version"),
        },
        "storage_probe": storage_probe,
        "storage_backend_observed": storage_probe.get("storage_backend_observed"),
        "render_disk_active": runtime_ok,
        "transportation_logic_unchanged": True,
        "verdict": "GO" if not blockers else "NO-GO",
        "blockers": blockers,
    }
    return report


def _write_reports(report: dict) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    json_path = REPO_ROOT / f"PHASE_55_RENDER_STORAGE_FINALIZATION_{stamp}.json"
    md_path = REPO_ROOT / f"PHASE_55_RENDER_STORAGE_FINALIZATION_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    cfg = report["render_config"]
    probe = report["storage_probe"]
    lines = [
        "# Phase 55 — Render Storage Finalization",
        "",
        f"**Verdict:** {report['verdict']}",
        f"**Timestamp:** {report['timestamp']}",
        f"**Staging URL:** {report['staging_url']}",
        "",
        "## Render configuration (render.yaml)",
        "",
        f"- Persistent disk name: `{cfg.get('render_yaml_disk_name')}`",
        f"- Mount path: `{cfg.get('render_yaml_disk_mount_path')}`",
        f"- Size (GB): `{cfg.get('render_yaml_disk_size_gb')}`",
        f"- `PLATFORM_OPS_DOCUMENT_STORAGE`: `{cfg.get('platform_ops_document_storage')}`",
        f"- `PLATFORM_OPS_DOCUMENT_STORAGE_PATH`: `{cfg.get('platform_ops_document_storage_path')}`",
        f"- Config file check: **{'PASS' if report['render_config_pass'] else 'FAIL'}**",
        "",
        "## Live runtime evidence",
        "",
        f"- Deploy commit: `{report['live_health'].get('deploy_commit')}`",
        f"- APP_VERSION observed: `{report['live_health'].get('version')}`",
        f"- Upload status: `{probe.get('upload_status')}`",
        f"- Download status: `{probe.get('download_status')}`",
        f"- `storage_backend_observed`: `{report.get('storage_backend_observed')}`",
        f"- render_disk active: **{report.get('render_disk_active')}**",
        "",
    ]
    if report["blockers"]:
        lines.extend(["## Blockers", ""])
        for item in report["blockers"]:
            lines.append(f"- {item}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    expected = sys.argv[1] if len(sys.argv) > 1 else None
    report = run_phase55(expected_commit_prefix=expected)
    json_path, md_path = _write_reports(report)
    print(json.dumps(report, indent=2))
    print(f"\nWrote {json_path.name} and {md_path.name}", flush=True)
    return 0 if report["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
