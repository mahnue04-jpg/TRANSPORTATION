"""Safety checks for staged Operations CSV Alembic migration."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20261109_nova_operations_csv_jobs.py"
spec = spec_from_file_location("nova_ops_csv_migration_test", FILE)
migration = module_from_spec(spec)
spec.loader.exec_module(migration)


def test_migration_is_safe_by_default(monkeypatch):
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV", "NOVA_OPERATIONS_CSV_SCHEMA_APPROVED"):
        monkeypatch.delenv(name, raising=False)
    assert migration._staging_approved() is False
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "staging-only")
    assert migration._staging_approved() is False


def test_only_explicit_consistent_staging_allows_schema(monkeypatch):
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "staging-only")
    assert migration._staging_approved() is True
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    assert migration._staging_approved() is False


def test_unapproved_staging_must_raise_instead_of_stamping(monkeypatch):
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", raising=False)
    with pytest.raises(RuntimeError, match="approval"):
        migration.upgrade()
