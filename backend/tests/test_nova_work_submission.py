from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.nova.work_revenue import submission


def test_known_discovery_provider_is_handoff_only():
    opp = SimpleNamespace(source="remotive", source_type="approved_api", source_url="https://remotive.com/jobs/1")
    policy = submission.policy_for_opportunity(opp)
    assert policy.provider_id == "remotive"
    assert policy.tier == "C"
    assert policy.submission_mode == "handoff"
    assert policy.allowlisted is True
    assert policy.live_adapter_implemented is False
    assert policy.terms_permit_automation is False


def test_unknown_provider_fails_closed():
    opp = SimpleNamespace(source="mystery", source_type="manual", source_url="https://example.invalid/apply")
    policy = submission.policy_for_opportunity(opp)
    assert policy.provider_id == "mystery"
    assert policy.allowlisted is False
    assert policy.submission_mode == "blocked"
    assert policy.live_adapter_implemented is False


def test_sam_gov_never_claims_direct_submit():
    opp = SimpleNamespace(source="sam.gov", source_type="approved_api", source_url="https://sam.gov/opp/123")
    policy = submission.policy_for_opportunity(opp)
    assert policy.provider_id == "sam_gov"
    assert policy.submission_mode == "handoff"
    assert policy.identity_required is True
    assert policy.signature_required is True
    assert policy.live_adapter_implemented is False


def test_material_change_after_approval_is_stale():
    decided_at = submission.service.now()
    newer = SimpleNamespace(updated_at=decided_at + timedelta(seconds=1))

    class Query:
        def filter(self, *args, **kwargs):
            return self
        def all(self):
            return [newer]

    class DB:
        def query(self, *args, **kwargs):
            return Query()

    assert submission._materials_changed_after_approval(
        DB(),
        application_id="NWA-1",
        organization_id="org-1",
        decided_at=decided_at,
    ) is True


def test_no_material_change_after_approval():
    decided_at = submission.service.now()
    older = SimpleNamespace(updated_at=decided_at - timedelta(seconds=1))

    class Query:
        def filter(self, *args, **kwargs):
            return self
        def all(self):
            return [older]

    class DB:
        def query(self, *args, **kwargs):
            return Query()

    assert submission._materials_changed_after_approval(
        DB(),
        application_id="NWA-1",
        organization_id="org-1",
        decided_at=decided_at,
    ) is False
