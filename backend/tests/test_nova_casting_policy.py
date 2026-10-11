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


def test_audition_upload_is_applicant_owned_only():
    p = _policy()
    owner = p.CastingActor("talent-a", None, p.CastingRole.APPLICANT)
    reviewer = p.CastingActor("reviewer", "org-a", p.CastingRole.REVIEWER, True)
    assert p.may_upload_audition(owner, applicant_id="talent-a")
    assert not p.may_upload_audition(owner, applicant_id="talent-b")
    assert not p.may_upload_audition(reviewer, applicant_id="reviewer")


def test_audition_media_quarantine_and_tenant_isolation():
    p = _policy()
    reviewer = p.CastingActor("reviewer", "org-a", p.CastingRole.REVIEWER, True)
    applicant = p.CastingActor("talent-a", None, p.CastingRole.APPLICANT)
    assert not p.may_view_audition_media(reviewer, applicant_id="talent-a", organization_id="org-a", scan_status="PENDING")
    assert not p.may_view_audition_media(reviewer, applicant_id="talent-a", organization_id="org-b", scan_status="CLEAN")
    assert p.may_view_audition_media(reviewer, applicant_id="talent-a", organization_id="org-a", scan_status="CLEAN")
    assert p.may_view_audition_media(applicant, applicant_id="talent-a", organization_id="org-a", scan_status="CLEAN")


def test_campaign_reads_require_verified_membership():
    p = _policy()
    applicant = p.CastingActor("user-a", None, p.CastingRole.APPLICANT)
    reviewer = p.CastingActor("reviewer", "org-one", p.CastingRole.REVIEWER, True)
    outsider = p.CastingActor("reviewer", "org-two", p.CastingRole.REVIEWER, True)
    unverified = p.CastingActor("owner", "org-one", p.CastingRole.ORGANIZER, False)
    assert not p.may_view_campaign(applicant, organization_id="org-one")
    assert p.may_view_campaign(reviewer, organization_id="org-one")
    assert not p.may_view_campaign(outsider, organization_id="org-one")
    assert not p.may_view_campaign(unverified, organization_id="org-one")
    assert not p.may_manage_campaign(reviewer, organization_id="org-one")
