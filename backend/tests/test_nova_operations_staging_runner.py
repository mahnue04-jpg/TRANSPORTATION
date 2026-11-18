"""Focused release gates for the manual Operations staging migration runner.

No Render credentials, database connection, paid resources, or live migrations.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[1] / "operations_staging_migration_runner.py"
    spec = importlib.util.spec_from_file_location("ops_staging_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _staging(monkeypatch, runner):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", "staging-only")
    monkeypatch.setenv("NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE", runner.EXPECTED_DB)
    for key in ("NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
                "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
                "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
                "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED"):
        monkeypatch.setenv(key, "false")


def test_only_staging_database_and_disabled_processing(monkeypatch, runner):
    _staging(monkeypatch, runner)
    runner._check_environment()
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    with pytest.raises(RuntimeError, match="Forbidden active capability"):
        runner._check_environment()
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE", "another_database")
    with pytest.raises(RuntimeError, match="Exact dedicated"):
        runner._check_environment()


def test_environment_conflict_is_rejected(monkeypatch, runner):
    _staging(monkeypatch, runner)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="Only explicitly"):
        runner._check_environment()


def test_restore_evidence_is_required(tmp_path, runner):
    with pytest.raises(RuntimeError, match="restore evidence"):
        runner._restore_evidence(None)
    path = tmp_path / "restore.json"
    path.write_text(json.dumps({"source_database": runner.EXPECTED_DB}))
    with pytest.raises(RuntimeError, match="Incomplete"):
        runner._restore_evidence(str(path))


def test_restore_evidence_must_be_separate_target(tmp_path, runner):
    path = tmp_path / "restore.json"
    record = {
        "source_database": runner.EXPECTED_DB,
        "backup_identifier": "synthetic-backup-marker",
        "restore_target": runner.EXPECTED_DB,
        "restore_verified_at": "2026-11-18T12:00:00Z",
        "verified_by": "synthetic-validator",
        "verification_result": "passed",
    }
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="isolated target"):
        runner._restore_evidence(str(path))
    record["restore_target"] = "isolated-disposable-restore"
    record["verification_result"] = "failed"
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="isolated target"):
        runner._restore_evidence(str(path))


def test_positive_shape_is_not_proof_of_real_restore(tmp_path, runner):
    # This is only a schema assertion; operator must independently verify
    # genuine Render backup and isolated restore before --apply.
    path = tmp_path / "restore.json"
    path.write_text(json.dumps({
        "source_database": runner.EXPECTED_DB,
        "backup_identifier": "example-only",
        "restore_target": "example-isolated-target",
        "restore_verified_at": "2026-11-18T12:00:00Z",
        "verified_by": "example",
        "verification_result": "passed",
    }))
    runner._restore_evidence(str(path))
