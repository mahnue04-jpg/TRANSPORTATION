"""Production migration safety regression tests.

Pure local module checks: never connect to a production or staging database.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
REVISIONS = (
    "20261112_nova_growth_agent.py",
    "20261112_nova_growth_agent_worker.py",
    "20261112_nova_growth_agent_retention_schedule.py",
)


def _revision(name):
    spec = importlib.util.spec_from_file_location("safe_growth_" + name.removesuffix(".py"), VERSIONS / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("filename", REVISIONS)
@pytest.mark.parametrize("environment", ("production", "prod"))
def test_growth_migrations_never_stamp_without_schema_in_production(monkeypatch, filename, environment):
    module = _revision(filename)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", environment)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(RuntimeError, match="blocked in production"):
        module.upgrade()
    with pytest.raises(RuntimeError, match="blocked in production"):
        module.downgrade()


@pytest.mark.parametrize("filename", REVISIONS)
def test_any_production_environment_alias_blocks_growth_ddl(monkeypatch, filename):
    module = _revision(filename)
    for key in ("AMICOR_ENVIRONMENT", "APP_ENV", "ENVIRONMENT"):
        for env_name in ("AMICOR_ENVIRONMENT", "APP_ENV", "ENVIRONMENT"):
            monkeypatch.delenv(env_name, raising=False)
        monkeypatch.setenv(key, "production")
        with pytest.raises(RuntimeError, match="blocked in production"):
            module.upgrade()
