"""Pure casting authorization checks; no real applicant data or database required."""
import importlib.util
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/casting_policy.py"


def _policy():
    import sys
    module_name = "casting_policy_test_module"
    spec = importlib.util.spec_from_file_location(module_name, POLICY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_applicant_sees_only_own_application():
    p = _policy()
    actor = p.CastingActor("user-a", None, p.CastingRole.APPLICANT)
    assert p.may_view_application(actor, applicant_id="user-a", organization_id="org-one")
    assert not p.may_view_application(actor, applicant_id="user-b", organization_id="org-one")
    assert not p.may_review_application(actor, organization_id="org-one")
    assert not p.may_manage_campaign(actor, organization_id="org-one")


def test_reviewers_cannot_cross_tenant_or_manage_campaign():
    p = _policy()
    actor = p.CastingActor("reviewer", "org-one", p.CastingRole.REVIEWER, True)
    assert p.may_view_application(actor, applicant_id="other", organization_id="org-one")
    assert p.may_review_application(actor, organization_id="org-one")
    assert not p.may_review_application(actor, organization_id="org-two")
    assert not p.may_view_application(actor, applicant_id="other", organization_id="org-two")
    assert not p.may_manage_campaign(actor, organization_id="org-one")


def test_unverified_organizer_is_denied_even_in_own_org():
    p = _policy()
    unverified = p.CastingActor("organizer", "org-one", p.CastingRole.ORGANIZER, False)
    verified = p.CastingActor("organizer", "org-one", p.CastingRole.ORGANIZER, True)
    assert not p.may_manage_campaign(unverified, organization_id="org-one")
    assert not p.may_review_application(unverified, organization_id="org-one")
    assert p.may_manage_campaign(verified, organization_id="org-one")
    assert not p.may_manage_campaign(verified, organization_id="org-two")


def test_empty_identity_is_never_authorized():
    p = _policy()
    actor = p.CastingActor("", "org-one", p.CastingRole.ORGANIZER, True)
    assert not p.may_view_application(actor, applicant_id="", organization_id="org-one")
    assert not p.may_review_application(actor, organization_id="org-one")
    assert not p.may_manage_campaign(actor, organization_id="org-one")
