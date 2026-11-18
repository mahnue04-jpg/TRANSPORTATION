"""Offline tests for default-off Studio-Growth owner-session boundary.

No real JWT, session, service, database or communications.
"""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/studio_growth_owner_context.py"
spec = importlib.util.spec_from_file_location("studio_growth_owner_context_test_only", PATH)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


def session(**changes):
    payload = dict(user_id="owner-1", organization_id="org-A", role="admin")
    payload.update(changes)
    return SimpleNamespace(**payload)


def authorize(user=None, *, org="org-A", reader=None, enabled=True):
    return gate.authorize_owner_grant_context(
        authenticated_user=session() if user is None else user,
        requested_organization_id=org,
        membership_reader=(lambda uid, tenant: uid == "owner-1" and tenant == "org-A")
        if reader is None else reader,
        enabled=enabled,
    )


def test_verified_admin_and_matching_membership():
    verified = authorize()
    assert verified.user_id == "owner-1"
    assert verified.organization_id == "org-A"


def test_default_off(monkeypatch):
    monkeypatch.delenv("NOVA_STUDIO_GROWTH_OWNER_GRANTS_ENABLED", raising=False)
    with pytest.raises(PermissionError, match="disabled"):
        authorize(enabled=None)


@pytest.mark.parametrize("changes", [
    dict(user_id=""), dict(user_id="in valid"),
    dict(organization_id="org-B"), dict(organization_id=None),
    dict(role="staff"), dict(role="super_admin_support"),
    dict(role="dispatcher"), dict(role=None),
])
def test_unauthorized_session_denied(changes):
    with pytest.raises(PermissionError):
        authorize(session(**changes))


def test_wrong_requested_tenant_denied():
    with pytest.raises(PermissionError):
        authorize(org="org-B")


def test_missing_or_unverified_membership_denied():
    with pytest.raises(PermissionError):
        authorize(reader=lambda uid, org: False)
    with pytest.raises(PermissionError):
        authorize(reader=lambda uid, org: "yes")
    with pytest.raises(PermissionError):
        authorize(reader=object())


def test_membership_read_exception_fails_closed():
    def broken(uid, org):
        raise RuntimeError("database unavailable")
    with pytest.raises(PermissionError, match="failed closed"):
        authorize(reader=broken)


def test_enabled_flag_refuses_live_route(monkeypatch):
    monkeypatch.setenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED", "true")
    with pytest.raises(PermissionError):
        authorize()


def test_output_has_no_email_or_token():
    approved = authorize()
    assert set(approved.__dataclass_fields__) == {"user_id", "organization_id"}
