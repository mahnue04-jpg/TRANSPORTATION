"""Standalone checks for verified-session casting identity adapter."""
import importlib.util
import sys
import types
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"


def load_identity():
    prefix = "_casting_identity_tests"
    pkg = types.ModuleType(prefix)
    pkg.__path__ = [str(FOLDER)]
    sys.modules[prefix] = pkg
    for name in ("casting_policy", "casting_identity"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{prefix}.casting_identity"]


def test_verified_organizer_only_from_matching_active_membership():
    identity = load_identity()
    good = dict(session_user_id="u1", membership_user_id="u1", membership_org_id="org1",
                membership_role="organizer", membership_active=True, organization_verified=True)
    actor = identity.from_verified_session(**good)
    assert actor and actor.organization_id == "org1"
    for bad in ({"membership_user_id": "u2"}, {"membership_active": False},
                {"organization_verified": False}, {"membership_role": "admin"},
                {"membership_org_id": ""}):
        assert identity.from_verified_session(**{**good, **bad}) is None


def test_applicant_identity_requires_session():
    identity = load_identity()
    assert identity.applicant_from_verified_session(session_user_id="u1")
    assert identity.applicant_from_verified_session(session_user_id="") is None
