"""Disposable SQLite proof of the Studio->Growth owner-grant contract.

No migrations, customer data, network connections or production stores.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

import pytest

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/studio_growth_grants.py"
spec = importlib.util.spec_from_file_location("studio_growth_grants_test_only", PATH)
grants = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = grants
spec.loader.exec_module(grants)

NOW = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)


def grant(**changes):
    data = dict(grant_id="grant-1", organization_id="org-A",
                owner_user_id="owner-A", project_id="project-1",
                asset_id="asset-1", campaign_id="campaign-1",
                approved_at=NOW, expires_at=NOW + timedelta(minutes=30),
                idempotency_key="approval-key-1")
    data.update(changes)
    return grants.OwnerGrant(**data)


def ledger(tmp_path):
    con = sqlite3.connect(tmp_path / "grants.sqlite", isolation_level=None)
    con.execute(grants.TEST_SCHEMA)
    return grants.OwnerGrantLedger(con), con


def read(book, **overrides):
    data = dict(organization_id="org-A", owner_id="owner-A",
                project_id="project-1", asset_id="asset-1",
                campaign_id="campaign-1", now=NOW + timedelta(minutes=1))
    data.update(overrides)
    return book.read_approved(**data)


def test_owner_grant_roundtrip_and_restart(tmp_path):
    book, con = ledger(tmp_path)
    assert book.record(grant(), authenticated_owner_id="owner-A") == "recorded"
    assert book.record(grant(), authenticated_owner_id="owner-A") == "duplicate"
    assert read(book) == dict(
        organization_id="org-A", owner_id="owner-A", project_id="project-1",
        asset_id="asset-1", approved=True,
        action="share_campaign_asset_with_growth",
    )
    con.close()
    again = sqlite3.connect(tmp_path / "grants.sqlite", isolation_level=None)
    assert read(grants.OwnerGrantLedger(again))["approved"] is True
    again.close()


@pytest.mark.parametrize("scope", [
    dict(organization_id="org-B"), dict(owner_id="other-owner"),
    dict(project_id="other-project"), dict(asset_id="other-asset"),
    dict(campaign_id="other-campaign"),
])
def test_wrong_scope_and_tenant_deny(tmp_path, scope):
    book, con = ledger(tmp_path)
    book.record(grant(), authenticated_owner_id="owner-A")
    assert read(book, **scope) is None
    con.close()


def test_expiry_and_revocation_and_wrong_revoker(tmp_path):
    book, con = ledger(tmp_path)
    book.record(grant(), authenticated_owner_id="owner-A")
    assert read(book, now=NOW + timedelta(minutes=30)) is None
    assert read(book, now=NOW - timedelta(seconds=1)) is None
    assert book.revoke(organization_id="org-B", grant_id="grant-1",
                       authenticated_owner_id="owner-A", now=NOW) is False
    assert book.revoke(organization_id="org-A", grant_id="grant-1",
                       authenticated_owner_id="other-owner", now=NOW) is False
    assert book.revoke(organization_id="org-A", grant_id="grant-1",
                       authenticated_owner_id="owner-A", now=NOW) is True
    assert book.revoke(organization_id="org-A", grant_id="grant-1",
                       authenticated_owner_id="owner-A", now=NOW) is False
    assert read(book) is None
    con.close()


def test_owner_forgery_and_replay_conflict_denied(tmp_path):
    book, con = ledger(tmp_path)
    with pytest.raises(PermissionError):
        book.record(grant(), authenticated_owner_id="wrong-owner")
    book.record(grant(), authenticated_owner_id="owner-A")
    with pytest.raises(PermissionError):
        book.record(grant(asset_id="other-asset"), authenticated_owner_id="owner-A")
    con.close()


def test_unique_grant_and_single_asset_scope(tmp_path):
    book, con = ledger(tmp_path)
    book.record(grant(), authenticated_owner_id="owner-A")
    with pytest.raises(sqlite3.IntegrityError):
        book.record(grant(grant_id="grant-2", idempotency_key="another-key"),
                    authenticated_owner_id="owner-A")
    assert read(book) is not None
    con.close()


def test_schema_is_explicit_not_created_on_import(tmp_path):
    con = sqlite3.connect(tmp_path / "empty.sqlite")
    book = grants.OwnerGrantLedger(con)
    with pytest.raises(sqlite3.OperationalError):
        book.record(grant(), authenticated_owner_id="owner-A")
    assert con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    con.close()


@pytest.mark.parametrize("changes", [
    dict(grant_id="bad id"),
    dict(organization_id=""),
    dict(action="publish_ads"),
    dict(schema_version="unknown"),
    dict(expires_at=NOW),
    dict(approved_at=NOW + timedelta(days=1)),
])
def test_invalid_grants_rejected(changes):
    with pytest.raises(ValueError):
        grant(**changes)


def test_grant_type_does_not_expose_customer_or_media_fields():
    assert set(grants.OwnerGrant.__dataclass_fields__) == {
        "grant_id", "organization_id", "owner_user_id",
        "project_id", "asset_id", "campaign_id",
        "approved_at", "expires_at", "idempotency_key",
        "action", "schema_version",
    }
