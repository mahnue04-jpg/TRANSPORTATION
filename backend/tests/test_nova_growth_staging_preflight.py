"""Unit tests for the non-mutating Growth Agent staging preflight."""
from app.core.nova.growth_agent.staging_preflight import validate


def good_env():
    return {
        "RENDER_GIT_COMMIT": "a" * 40,
        "NOVA_GA_APPROVED_STAGING_SHA": "a" * 40,
        "APP_ENV": "staging",
        "AMICOR_ENVIRONMENT": "staging",
        "DATABASE_URL": "postgresql+psycopg2://synthetic:fakepassword@dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos",
        "NOVA_STRIPE_LIVE_ENABLED": "false",
        "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED": "false",
    }


def test_valid_identity_only():
    assert validate(good_env())[0] is True


def test_wrong_commit_denied():
    env = good_env()
    env["RENDER_GIT_COMMIT"] = "b" * 40
    assert validate(env)[0] is False


def test_missing_approval_denied():
    env = good_env()
    env.pop("NOVA_GA_APPROVED_STAGING_SHA")
    assert validate(env)[0] is False


def test_production_environment_denied():
    env = good_env()
    env["APP_ENV"] = "production"
    assert validate(env)[0] is False


def test_prod_database_denied():
    env = good_env()
    env["DATABASE_URL"] = "postgresql://synthetic:fakepassword@production.example.invalid/amicor"
    assert validate(env)[0] is False


def test_database_password_not_logged():
    env = good_env()
    env["DATABASE_URL"] = "not-a-url://secret-password"
    ok, reason = validate(env)
    assert not ok
    assert "secret-password" not in reason


def test_live_payment_denied():
    env = good_env()
    env["NOVA_STRIPE_LIVE_ENABLED"] = "true"
    assert not validate(env)[0]


def test_retention_delete_denied():
    env = good_env()
    env["NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED"] = "true"
    assert not validate(env)[0]


def test_query_parameters_denied():
    env = good_env()
    env["DATABASE_URL"] += "?sslmode=disable"
    assert not validate(env)[0]


def test_background_mock_worker_denied():
    env = good_env()
    env["NOVA_GROWTH_AGENT_BACKGROUND_WORKER"] = "true"
    assert not validate(env)[0]


def test_retention_scheduler_denied():
    env = good_env()
    env["NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED"] = "true"
    assert not validate(env)[0]
