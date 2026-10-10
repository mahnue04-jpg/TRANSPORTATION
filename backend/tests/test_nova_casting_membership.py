"""Casting membership lookup tests: no live DB or new identity provider."""
import importlib.util
import sys
import types
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"


def load():
    prefix = "_casting_membership_test"
    package = types.ModuleType(prefix)
    package.__path__ = [str(FOLDER)]
    sys.modules[prefix] = package
    for name in ("casting_policy", "casting_identity", "casting_membership"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{prefix}.casting_membership"]


def test_membership_requires_server_verified_active_organization():
    member = load()
    record = dict(user_id="user1", organization_id="org1", nova_tenant_id="tenant1", active=True,
                  organization_verified=True, casting_role="organizer")
    assert member.verified_casting_member(session_user_id="user1", organization_id="org1", session_tenant_id="tenant1",
                                          lookup=lambda user, org: record)
    for override in ({"user_id": "other"}, {"organization_id": "other"},
                     {"active": False}, {"organization_verified": False},
                     {"casting_role": "admin"}, {"nova_tenant_id": "tenant2"}):
        assert member.verified_casting_member(
            session_user_id="user1", organization_id="org1", session_tenant_id="tenant1",
            lookup=lambda user, org, override=override: {**record, **override},
        ) is None
    assert member.verified_casting_member(
        session_user_id="user1", organization_id="org1", session_tenant_id="tenant1", lookup=lambda user, org: None,
    ) is None


def test_membership_lookup_outage_denies_casting_access():
    member = load()
    for error in (LookupError, ConnectionError, TimeoutError):
        def unavailable(user, org, error=error):
            raise error("membership store unavailable")
        assert member.verified_casting_member(
            session_user_id="user1", organization_id="org1",
            session_tenant_id="tenant1", lookup=unavailable,
        ) is None
