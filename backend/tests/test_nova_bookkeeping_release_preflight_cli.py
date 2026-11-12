"""Offline release report must remain blocked and never leak secrets."""
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.nova_bookkeeping_release_preflight import build_report

ROOT = Path(__file__).resolve().parents[1]


def test_offline_report_denies_release_even_with_staging_labels():
    report = build_report({
        "APP_ENV": "staging", "AMICOR_ENVIRONMENT": "staging",
        "PLATFORM_OPS_DOCUMENT_STORAGE": "s3_private",
        "NOVA_BOOKKEEPING_DURABLE_ENABLED": "false",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED": "false",
        "DATABASE_URL": "postgresql://secret:password@host/db",
        "AMICOR_DOCUMENT_S3_SECRET_KEY": "SECRET_SHOULD_NEVER_APPEAR",
    })
    assert report["status"] == "BLOCKED"
    assert report["production_release_authorized"] is False
    assert report["deployment_performed"] is False
    assert report["real_render_staging_checked"] is False
    assert report["owner_release_approval_recorded"] is False
    assert "SECRET_SHOULD_NEVER_APPEAR" not in json.dumps(report)
    assert "secret:password" not in json.dumps(report)


def test_cli_writes_sanitized_json_without_any_cloud_connection(tmp_path):
    target = tmp_path / "report.json"
    # CLI only accepts relative artifact paths, so use a dedicated temporary
    # working directory and a relative filename.
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT),
        "APP_ENV": "staging",
        "NOVA_BOOKKEEPING_DURABLE_ENABLED": "false",
        "DATABASE_URL": "postgresql://never:print@nowhere/notreal",
        "AMICOR_DOCUMENT_S3_SECRET_KEY": "ULTRA_PRIVATE_CI_SENTINEL",
    })
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/nova_bookkeeping_release_preflight.py"),
         "--output", "report.json"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    raw = target.read_text(encoding="utf-8")
    result = json.loads(raw)
    assert result["status"] == "BLOCKED"
    assert not result["production_release_authorized"]
    assert result["run_mode"] == "NO_EXTERNAL_CONNECTIONS"
    assert "ULTRA_PRIVATE_CI_SENTINEL" not in raw
    assert "never:print" not in raw


def test_cli_rejects_absolute_and_traversal_outputs(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    for unsafe in ("/tmp/forbidden.json", "../outside.json", "folder/../../unsafe.json"):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/nova_bookkeeping_release_preflight.py"),
             "--output", unsafe],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode != 0
        assert "relative local" in proc.stderr
