"""Isolated Growth Agent lifespan acceptance tests.

No service deployment, database connection, migration, schema ensure, or seed calls.
The feature flag is only for an explicitly pinned isolated staging acceptance host.
"""
import asyncio
import os

import pytest

from app import main as main_module


def _safe_env():
    return {
        "NOVA_GA_ISOLATED_SKIP_DB_BOOTSTRAP": "true",
        "APP_ENV": "staging",
        "AMICOR_ENVIRONMENT": "staging",
        "RENDER_GIT_COMMIT": "a" * 40,
        "NOVA_GA_APPROVED_STAGING_SHA": "a" * 40,
        "DATABASE_URL": "postgresql://synthetic:fake@dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos",
        "NOVA_GROWTH_AGENT_BACKGROUND_WORKER": "false",
        "NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED": "false",
        "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED": "false",
        "NOVA_STRIPE_LIVE_ENABLED": "false",
    }


def _boom(*args, **kwargs):
    raise AssertionError("platform startup must be bypassed")


def test_isolated_lifespan_skips_platform_startup(monkeypatch):
    env = _safe_env()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # This is the earliest platform startup call in the normal path.
    monkeypatch.setattr(main_module.app_startup, "register_shutdown_handlers", _boom)
    monkeypatch.setattr(main_module.app_startup, "startup_recovery", _boom)
    monkeypatch.setattr(main_module, "init_db", _boom)

    async def run():
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(run())


def test_isolated_lifespan_denies_unapproved_commit(monkeypatch):
    env = _safe_env()
    env["RENDER_GIT_COMMIT"] = "b" * 40
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(main_module.app_startup, "register_shutdown_handlers", _boom)

    async def run():
        async with main_module.lifespan(main_module.app):
            pass

    with pytest.raises(RuntimeError, match="Isolated Growth staging bootstrap denied"):
        asyncio.run(run())


def test_isolated_lifespan_denies_production(monkeypatch):
    env = _safe_env()
    env["APP_ENV"] = "production"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    async def run():
        async with main_module.lifespan(main_module.app):
            pass
    with pytest.raises(RuntimeError, match="APP_ENV must be staging"):
        asyncio.run(run())


def test_isolated_lifespan_denies_worker_on(monkeypatch):
    env = _safe_env()
    env["NOVA_GROWTH_AGENT_BACKGROUND_WORKER"] = "true"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    async def run():
        async with main_module.lifespan(main_module.app):
            pass
    with pytest.raises(RuntimeError, match="Unsafe live/deletion flag"):
        asyncio.run(run())


def test_isolated_testclient_serves_workspace_without_platform_bootstrap(monkeypatch):
    """Exercise FastAPI lifespan plus the actual Workspace page, not only a helper."""
    from fastapi.testclient import TestClient

    for key, value in _safe_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(main_module.app_startup, "register_shutdown_handlers", _boom)
    monkeypatch.setattr(main_module.app_startup, "startup_recovery", _boom)
    monkeypatch.setattr(main_module, "init_db", _boom)

    with TestClient(main_module.app) as client:
        page = client.get("/nova/workspace")
        assert page.status_code == 200
        assert "growth-readonly-refresh" in page.text
        # Protected management API must not leak records anonymously.
        protected = client.get("/api/nova/growth-agent/leads")
        assert protected.status_code in {401, 403}
