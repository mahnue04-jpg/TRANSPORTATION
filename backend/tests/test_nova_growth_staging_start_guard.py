"""No-network, no-database-write tests for the Render staging startup gate."""
from __future__ import annotations

import pytest
from scripts.verify_growth_staging_start import validate_environment


SHA = "a" * 40


def _env():
    return {
        "NOVA_GA_APPROVED_STAGING_SHA": SHA,
        "RENDER_GIT_COMMIT": SHA,
        "RENDER_EXTERNAL_URL": "https://nova-growth-validation-490.onrender.com",
        "NOVA_GROWTH_AGENT_ENABLED": "true",
        "NOVA_GROWTH_AGENT_DEMO_MODE": "true",
        "DATABASE_URL": "postgresql://example:synthetic-pass@dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos",
        "PORT": "10000",
    }


def test_exact_approved_staging_configuration_normalizes_database_driver():
    url = validate_environment(_env())
    assert url.startswith("postgresql+psycopg2://")
    assert "nova_ga_490_dispos" in url


@pytest.mark.parametrize("change", [
    {"RENDER_GIT_COMMIT": "b" * 40},
    {"NOVA_GA_APPROVED_STAGING_SHA": ""},
    {"RENDER_EXTERNAL_URL": "https://getamicor.com"},
    {"APP_ENV": "production"},
    {"ENVIRONMENT": "prod"},
    {"NOVA_GROWTH_AGENT_ENABLED": "false"},
    {"NOVA_GROWTH_AGENT_DEMO_MODE": ""},
    {"NOVA_GROWTH_AGENT_BACKGROUND_WORKER": "true"},
    {"NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED": "yes"},
    {"NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED": "1"},
    {"NOVA_GA_REAL_SMS_SEND": "true"},
    {"DATABASE_URL": "postgresql://example:synthetic-pass@prod.example.com/amicor_prod"},
    {"DATABASE_URL": "postgresql://example:synthetic-pass@dpg-dbqv7mmtlv9c73d7tnb0-a/amicor_prod"},
    {"DATABASE_URL": "sqlite:///staging.db"},
    {"DATABASE_URL": "postgresql://example@dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos"},
    {"PORT": "0"},
])
def test_unsafe_staging_configuration_fails_closed(change):
    env = _env()
    env.update(change)
    with pytest.raises(RuntimeError):
        validate_environment(env)
