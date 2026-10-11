"""Standalone audition transition policy tests without full application imports."""
import importlib.util
import sys
import types
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"


def _load():
    prefix = "_casting_isolated_tests"
    pkg = types.ModuleType(prefix)
    pkg.__path__ = [str(FOLDER)]
    sys.modules[prefix] = pkg
    for name in ("casting_policy", "casting_workflow_policy"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{prefix}.casting_policy"], sys.modules[f"{prefix}.casting_workflow_policy"]


def test_submission_requires_owner_consent_and_open_campaign():
    policy, flow = _load()
    actor = policy.CastingActor("applicant-a", None, policy.CastingRole.APPLICANT)
    kwargs = dict(applicant_id="applicant-a", organization_id="org-a", current=flow.ApplicationState.DRAFT, target=flow.ApplicationState.SUBMITTED)
    assert not flow.may_transition_application(actor, **kwargs)
    assert not flow.may_transition_application(actor, **kwargs, consent_recorded=True)
    assert not flow.may_transition_application(actor, **kwargs, campaign_open=True)
    assert flow.may_transition_application(actor, **kwargs, consent_recorded=True, campaign_open=True)
    stranger = policy.CastingActor("applicant-b", None, policy.CastingRole.APPLICANT)
    assert not flow.may_transition_application(stranger, **kwargs, consent_recorded=True, campaign_open=True)


def test_withdrawal_and_callback_are_role_and_tenant_scoped():
    policy, flow = _load()
    applicant = policy.CastingActor("applicant-a", None, policy.CastingRole.APPLICANT)
    reviewer = policy.CastingActor("reviewer-a", "org-a", policy.CastingRole.REVIEWER, True)
    assert flow.may_transition_application(applicant, applicant_id="applicant-a", organization_id="org-a", current=flow.ApplicationState.SUBMITTED, target=flow.ApplicationState.WITHDRAWN)
    assert not flow.may_transition_application(reviewer, applicant_id="applicant-a", organization_id="org-a", current=flow.ApplicationState.SUBMITTED, target=flow.ApplicationState.WITHDRAWN)
    assert flow.may_schedule_callback(reviewer, organization_id="org-a", application_state=flow.ApplicationState.SUBMITTED)
    assert not flow.may_schedule_callback(reviewer, organization_id="org-b", application_state=flow.ApplicationState.SUBMITTED)
    assert not flow.may_schedule_callback(reviewer, organization_id="org-a", application_state=flow.ApplicationState.WITHDRAWN)
    assert not flow.may_schedule_callback(applicant, organization_id="org-a", application_state=flow.ApplicationState.SUBMITTED)


def test_sandbox_submit_requires_consent_and_refuses_a_public_campaign():
    policy, flow = _load()
    actor = policy.CastingActor("applicant-a", None, policy.CastingRole.APPLICANT)
    kwargs = dict(
        applicant_id="applicant-a", organization_id="org-a",
        current=flow.ApplicationState.DRAFT, target=flow.ApplicationState.SUBMITTED,
    )
    assert flow.may_transition_application(actor, **kwargs, consent_recorded=True, sandbox_intake=True)
    assert not flow.may_transition_application(actor, **kwargs, sandbox_intake=True)
    assert not flow.may_transition_application(
        actor, **kwargs, consent_recorded=True, campaign_open=True, sandbox_intake=True,
    )
