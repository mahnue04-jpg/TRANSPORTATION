"""Offline full-chain Studio owner approval -> Growth read-only preview.

Uses only disposable SQLite and fictional records; NO HTTP request, customer,
service communication, migrations or production account connections.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3
import sys
import types
from types import SimpleNamespace

import pytest

CORE = Path(__file__).resolve().parents[1] / "app/core/nova"
PKG = "_test_only_nova_full_bridge_542"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(CORE)]
sys.modules[PKG] = pkg


def load(name):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, CORE / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


load("agent_events")
load("studio_growth_adapter")
load("studio_growth_owner_context")
grants = load("studio_growth_grants")
bridge = load("studio_growth_owner_bridge")

NOW = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _owner_grants_enabled(monkeypatch):
    monkeypatch.setenv("NOVA_STUDIO_GROWTH_OWNER_GRANTS_ENABLED", "true")


def grant():
    return grants.OwnerGrant(
        grant_id="grant-1", organization_id="org-A", owner_user_id="owner-1",
        project_id="project-1", asset_id="asset-1", campaign_id="campaign-1",
        approved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        idempotency_key="grant-key-1",
    )


def setup(tmp_path):
    db = sqlite3.connect(tmp_path / "grants.sqlite", isolation_level=None)
    db.execute(grants.TEST_SCHEMA)
    ledger = grants.OwnerGrantLedger(db)
    ledger.record(grant(), authenticated_owner_id="owner-1")
    project = SimpleNamespace(id="project-1", owner_id="owner-1")
    asset = SimpleNamespace(id="asset-1", project_id="project-1",
                            owner_id="owner-1", kind="video", status="GENERATED")

    class StudioStore:
        def get_project(self, project_id, owner_id):
            return project if project_id == project.id and owner_id == project.owner_id else None

        def list_assets(self, project_id, owner_id):
            return [asset] if project_id == asset.project_id and owner_id == asset.owner_id else []

    return dict(
        authenticated_user=SimpleNamespace(
            user_id="owner-1", organization_id="org-A", role="admin",
        ),
        requested_organization_id="org-A",
        membership_reader=lambda uid, org: uid == "owner-1" and org == "org-A",
        studio_store=StudioStore(),
        grant_ledger=ledger,
        growth_profile={
            "configured": True, "organization_id": "org-A",
            "is_synthetic_demo": True, "activated": False, "agent_disabled": True,
            "contact_email": "private@example.invalid",
        },
        project_id="project-1",
        asset_id="asset-1",
        campaign_id="campaign-1",
        studio_service_principal="studio-service-A",
        now=NOW,
        enabled=True,
    ), db


def test_full_chain_read_only_preview_with_persisted_grant(tmp_path):
    args, db = setup(tmp_path)
    try:
        result = bridge.preview_approved_studio_campaign(**args)
        assert result["mode"] == "synthetic_read_only_preview"
        assert result["campaign_id"] == "campaign-1"
        assert result["growth_campaign_intake_connected"] is False
        assert result["lead_created"] is False
        assert result["publishing_enabled"] is False
        assert result["outbound_messages_enabled"] is False
        assert "private@example.invalid" not in str(result)
        assert db.execute("SELECT COUNT(*) FROM studio_growth_owner_grants").fetchone()[0] == 1
    finally:
        db.close()


@pytest.mark.parametrize("change", [
    {"requested_organization_id": "org-B"},
    {"project_id": "wrong-project"},
    {"asset_id": "wrong-asset"},
    {"campaign_id": "wrong-campaign"},
    {"authenticated_user": SimpleNamespace(
        user_id="owner-1", organization_id="org-A", role="staff",
    )},
    {"membership_reader": lambda uid, org: False},
    {"studio_service_principal": "bad principal"},
    {"growth_profile": {
        "configured": True, "organization_id": "org-A",
        "is_synthetic_demo": True, "activated": True, "agent_disabled": True,
    }},
    {"growth_profile": {
        "configured": True, "organization_id": "org-B",
        "is_synthetic_demo": True, "activated": False, "agent_disabled": True,
    }},
    {"enabled": False},
])
def test_full_chain_fails_closed_on_identity_tenant_asset_or_profile(tmp_path, change):
    args, db = setup(tmp_path)
    args.update(change)
    try:
        with pytest.raises(PermissionError):
            bridge.preview_approved_studio_campaign(**args)
    finally:
        db.close()


def test_revoked_grant_blocks_complete_bridge(tmp_path):
    args, db = setup(tmp_path)
    try:
        assert args["grant_ledger"].revoke(
            organization_id="org-A", grant_id="grant-1",
            authenticated_owner_id="owner-1", now=NOW,
        )
        with pytest.raises(PermissionError, match="active, matching"):
            bridge.preview_approved_studio_campaign(**args)
    finally:
        db.close()


def test_expired_grant_blocks_complete_bridge(tmp_path):
    args, db = setup(tmp_path)
    args["now"] = NOW + timedelta(hours=1)
    try:
        with pytest.raises(PermissionError, match="active, matching"):
            bridge.preview_approved_studio_campaign(**args)
    finally:
        db.close()


def test_default_off_and_no_registered_http_route(monkeypatch, tmp_path):
    args, db = setup(tmp_path)
    monkeypatch.delenv("NOVA_STUDIO_GROWTH_STAGING_ADAPTER_ENABLED", raising=False)
    args["enabled"] = None
    try:
        with pytest.raises(PermissionError, match="disabled"):
            bridge.preview_approved_studio_campaign(**args)
        assert not hasattr(bridge, "router")
        assert "app.main" not in sys.modules
    finally:
        db.close()


def test_owner_grant_switch_is_independent_of_staging(monkeypatch, tmp_path):
    args, db = setup(tmp_path)
    monkeypatch.setenv("NOVA_STUDIO_GROWTH_STAGING_ADAPTER_ENABLED", "true")
    monkeypatch.setenv("NOVA_STUDIO_GROWTH_OWNER_GRANTS_ENABLED", "true")
    args["enabled"] = None
    try:
        result = bridge.preview_approved_studio_campaign(**args)
        assert result["mode"] == "synthetic_read_only_preview"
        monkeypatch.delenv("NOVA_STUDIO_GROWTH_OWNER_GRANTS_ENABLED", raising=False)
        with pytest.raises(PermissionError, match="owner grant"):
            bridge.preview_approved_studio_campaign(**args)
        args["enabled"] = True
        with pytest.raises(PermissionError, match="owner grant"):
            bridge.preview_approved_studio_campaign(**args)
    finally:
        db.close()
