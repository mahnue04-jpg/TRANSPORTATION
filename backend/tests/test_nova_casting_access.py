"""Standalone casting access tests: no live routes, DB or uploads."""
import importlib.util
import sys
import types
from pathlib import Path
import pytest

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"


def modules():
    prefix = "_casting_access_isolated"
    pkg = types.ModuleType(prefix)
    pkg.__path__ = [str(FOLDER)]
    sys.modules[prefix] = pkg
    for name in ("casting_policy", "casting_workflow_policy", "casting_responses", "casting_access"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{prefix}.casting_policy"], sys.modules[f"{prefix}.casting_access"]


def test_application_access_scoped_to_applicant_and_verified_organizer():
    policy, access = modules()
    app = {"id": "a1", "campaign_id": "c1", "owner_id": "org1", "applicant_id": "user1", "status": "DRAFT", "created_at": "now"}
    campaign = {"id": "c1", "owner_id": "org1"}
    applicant = policy.CastingActor("user1", None, policy.CastingRole.APPLICANT)
    outsider = policy.CastingActor("user2", None, policy.CastingRole.APPLICANT)
    organizer = policy.CastingActor("org-user", "org1", policy.CastingRole.ORGANIZER, True)
    assert access.read_application(actor=applicant, application=app, campaign=campaign)["id"] == "a1"
    assert access.read_application(actor=organizer, application=app, campaign=campaign)["id"] == "a1"
    with pytest.raises(access.CastingAccessDenied):
        access.read_application(actor=outsider, application=app, campaign=campaign)
    with pytest.raises(access.CastingAccessDenied):
        access.read_application(actor=organizer, application={**app, "owner_id": "org2"}, campaign=campaign)


def test_submission_remains_disabled_even_with_consent():
    policy, access = modules()
    applicant = policy.CastingActor("user1", None, policy.CastingRole.APPLICANT)
    app = {"id": "a1", "campaign_id": "c1", "owner_id": "org1", "applicant_id": "user1", "status": "DRAFT"}
    campaign = {"id": "c1", "owner_id": "org1"}
    assert not access.submit_application(actor=applicant, application=app, campaign=campaign, consent_recorded=True)
    assert access.submit_application(
        actor=applicant, application=app, campaign=campaign,
        consent_recorded=True, sandbox_intake=True,
    )


def test_missing_identifiers_fail_closed_without_exceptions():
    policy, access = modules()
    actor = policy.CastingActor("user1", None, policy.CastingRole.APPLICANT)
    complete = {"id": "a1", "campaign_id": "c1", "owner_id": "org1", "applicant_id": "user1", "status": "DRAFT", "created_at": "now"}
    campaign = {"id": "c1", "owner_id": "org1"}
    for key in ("id", "campaign_id", "applicant_id"):
        incomplete = {k: v for k, v in complete.items() if k != key}
        with pytest.raises(access.CastingAccessDenied):
            access.read_application(actor=actor, application=incomplete, campaign=campaign)
        assert not access.submit_application(actor=actor, application=incomplete, campaign=campaign, consent_recorded=True)
    for key in ("id", "owner_id"):
        incomplete_campaign = {k: v for k, v in campaign.items() if k != key}
        with pytest.raises(access.CastingAccessDenied):
            access.read_application(actor=actor, application=complete, campaign=incomplete_campaign)
        assert not access.submit_application(actor=actor, application=complete, campaign=incomplete_campaign, consent_recorded=True)


def test_application_read_requires_all_public_projection_fields():
    policy, access = modules()
    actor = policy.CastingActor("user1", None, policy.CastingRole.APPLICANT)
    app = {"id": "a1", "campaign_id": "c1", "owner_id": "org1", "applicant_id": "user1", "status": "DRAFT", "created_at": "now"}
    campaign = {"id": "c1", "owner_id": "org1"}
    for field in ("created_at", "status"):
        missing = {k: v for k, v in app.items() if k != field}
        with pytest.raises(access.CastingAccessDenied):
            access.read_application(actor=actor, application=missing, campaign=campaign)
