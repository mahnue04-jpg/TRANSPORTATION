"""No-service smoke checks for the Nova Central isolated staging factory.

These do not prove database zero-writes or deployed security, which require
separate disposable-ORM and runtime acceptance tests before staging approval.
"""
import importlib.util
import sys
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "nova_central_isolated.py"
spec = importlib.util.spec_from_file_location("nova_central_isolated_under_test", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "test")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("NOVA_CENTRAL_ISOLATED_TEST", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/nova-central-disposable-test.db")
    monkeypatch.setenv("NOVA_CENTRAL_APPROVED_COMMIT", "a" * 40)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", raising=False)
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED", raising=False)


def test_import_is_side_effect_free():
    assert "app.main" not in sys.modules
    assert not hasattr(module, "app")


def test_disposable_test_config_only(config):
    module._config()


@pytest.mark.parametrize("name,value", [
    ("APP_ENV", "production"),
    ("AMICOR_ENVIRONMENT", "production"),
    ("NOVA_CENTRAL_ISOLATED_TEST", "0"),
    ("NOVA_CENTRAL_APPROVED_COMMIT", "b" * 40),
    ("RENDER_GIT_COMMIT", ""),
    ("DATABASE_URL", "postgresql://example.invalid/unapproved"),
    ("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true"),
    ("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED", "true"),
])
def test_reject_insecure_config(config, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        module._config()


def test_staging_requires_explicit_new_postgres(config, monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_ISOLATED_TEST", "0")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "fictional-staging-secret-" + "x" * 40)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_ISSUER", "nova-central-staging")
    monkeypatch.setenv("JWT_AUDIENCE", "nova-central-readiness")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@central-only.internal/nova_central_542_dispos")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_HOST", "central-only.internal")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_NAME", "nova_central_542_dispos")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_USER", "user")
    module._config()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@central-only.internal/amicor")
    with pytest.raises(RuntimeError):
        module._config()


def test_missing_staging_allowlist_is_rejected(config, monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_ISOLATED_TEST", "0")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "fictional-staging-secret-" + "x" * 40)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_ISSUER", "nova-central-staging")
    monkeypatch.setenv("JWT_AUDIENCE", "nova-central-readiness")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@central-only.internal/nova_central_542_dispos")
    with pytest.raises(RuntimeError):
        module._config()


@pytest.mark.parametrize("value", ["z" * 40, "A" * 40, "a" * 39, "a" * 41])
def test_reject_noncanonical_commit_pin(config, monkeypatch, value):
    monkeypatch.setenv("NOVA_CENTRAL_APPROVED_COMMIT", value)
    monkeypatch.setenv("RENDER_GIT_COMMIT", value)
    with pytest.raises(RuntimeError):
        module._config()


def test_disposable_test_mode_denied_on_render(config, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError):
        module._config()


def test_disposable_test_mode_denied_in_staging(config, monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "fictional-staging-secret-" + "x" * 40)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_ISSUER", "nova-central-staging")
    monkeypatch.setenv("JWT_AUDIENCE", "nova-central-readiness")
    with pytest.raises(RuntimeError):
        module._config()


def test_disposable_test_mode_denied_with_render_service_id(config, monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-disallowed-runtime")
    with pytest.raises(RuntimeError):
        module._config()


@pytest.mark.parametrize("url", [
    "postgresql://other:pass@central-only.internal/nova_central_542_dispos",
    "postgresql://user:pass@other.internal/nova_central_542_dispos",
    "postgresql://user:pass@central-only.internal/amicor",
    "postgresql://user:pass@central-only.internal:5433/nova_central_542_dispos",
    "postgresql://user:pass@central-only.internal/nova_central_542_dispos?options=-csearch_path%3Dpublic",
    "postgresql://user:pass@central-only.internal/nova_central_542_dispos#fragment",
    "postgresql://user@central-only.internal/nova_central_542_dispos",
])
def test_staging_rejects_wrong_database_identity_or_ambiguous_url(config, monkeypatch, url):
    monkeypatch.setenv("NOVA_CENTRAL_ISOLATED_TEST", "0")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "fictional-staging-secret-" + "x" * 40)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_ISSUER", "nova-central-staging")
    monkeypatch.setenv("JWT_AUDIENCE", "nova-central-readiness")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_HOST", "central-only.internal")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_NAME", "nova_central_542_dispos")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_USER", "user")
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(RuntimeError):
        module._config()


def test_staging_requires_separate_approved_database_user(config, monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_ISOLATED_TEST", "0")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "fictional-staging-secret-" + "x" * 40)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_ISSUER", "nova-central-staging")
    monkeypatch.setenv("JWT_AUDIENCE", "nova-central-readiness")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@central-only.internal/nova_central_542_dispos")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_HOST", "central-only.internal")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_NAME", "nova_central_542_dispos")
    monkeypatch.delenv("NOVA_CENTRAL_EXPECTED_DB_USER", raising=False)
    with pytest.raises(RuntimeError):
        module._config()


@pytest.mark.parametrize("field,value", [
    ("JWT_SECRET", ""),
    ("JWT_SECRET", "weak"),
    ("JWT_ISSUER", ""),
    ("JWT_AUDIENCE", ""),
    ("SECRET_KEY", "a-different-secret"),
])
def test_staging_rejects_insecure_jwt_settings(config, monkeypatch, field, value):
    monkeypatch.setenv("NOVA_CENTRAL_ISOLATED_TEST", "0")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "fictional-staging-secret-" + "x" * 40)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_ISSUER", "nova-central-staging")
    monkeypatch.setenv("JWT_AUDIENCE", "nova-central-readiness")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@central-only.internal/nova_central_542_dispos")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_HOST", "central-only.internal")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_NAME", "nova_central_542_dispos")
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_USER", "user")
    monkeypatch.setenv(field, value)
    with pytest.raises(RuntimeError):
        module._config()
