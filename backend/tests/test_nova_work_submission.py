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


def test_naive_and_aware_timestamps_compare_safely():
    from datetime import datetime, timezone

    decided_at = datetime(2026, 9, 23, 4, 0, 0)  # SQLite-style naive UTC
    newer = SimpleNamespace(updated_at=datetime(2026, 9, 23, 4, 0, 1, tzinfo=timezone.utc))

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

def test_explicit_application_email_detected_from_listing_context():
    opp = SimpleNamespace(
        source_url="https://example.test/opportunity",
        description="To apply, send your proposal and capability statement to work@example.com.",
        requirements="",
    )
    assert submission._explicit_application_emails(opp) == ["work@example.com"]


def test_generic_contact_email_not_treated_as_application_target():
    opp = SimpleNamespace(
        source_url="https://example.test/opportunity",
        description="Questions? Contact support@example.com for general company information.",
        requirements="",
    )
    assert submission._explicit_application_emails(opp) == []


def test_mailto_source_is_explicit_application_email():
    opp = SimpleNamespace(
        source_url="mailto:apply@example.com?subject=Proposal",
        description="",
        requirements="",
    )
    assert submission._explicit_application_emails(opp) == ["apply@example.com"]


def test_confirmed_email_send_records_external_submission_only_after_transport_success(monkeypatch):
    decided_at = submission.service.now()
    application = SimpleNamespace(
        application_id="NWA-EMAIL1",
        opportunity_id="NWO-EMAIL1",
        approval_state="APPROVED",
        approved_for_future_submission=True,
        externally_submitted=False,
        manual_submission_recorded=False,
        decided_at=decided_at,
    )
    opportunity = SimpleNamespace(
        opportunity_id="NWO-EMAIL1",
        opportunity_title="Remote Operations Support",
        description="Apply by email: send your proposal to apply@example.com.",
        requirements="",
        source_url="https://example.test/remote-ops",
    )
    material = SimpleNamespace(
        kind="cover_letter",
        body="DRAFT cover letter — owner must approve before any future submission.\n\nApproved application body.",
        created_at=decided_at - timedelta(seconds=2),
        updated_at=decided_at - timedelta(seconds=1),
    )

    class Query:
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def all(self):
            return [material]

    class DB:
        def query(self, *args, **kwargs):
            return Query()

    monkeypatch.setattr(submission.service, "get_application", lambda *a, **k: application)
    monkeypatch.setattr(submission.service, "get_opportunity", lambda *a, **k: opportunity)

    from app.core.nova.communications import service as communications_service
    sent = {}
    def fake_send(db, payload, *, organization_id, user):
        sent["to"] = payload.to
        sent["subject"] = payload.subject
        sent["body"] = payload.body
        sent["confirm_send"] = payload.confirm_send
        return {"status": "sent", "provider": "smtp"}
    monkeypatch.setattr(communications_service, "send_confirmed", fake_send)

    recorded = {}
    def fake_record(db, application_id, *, organization_id, user, provider, receipt=None):
        recorded["application_id"] = application_id
        recorded["provider"] = provider
        recorded["receipt"] = receipt
        return SimpleNamespace(application_id=application_id, opportunity_id="NWO-EMAIL1")
    monkeypatch.setattr(submission.service, "record_confirmed_external_submission", fake_record)

    result = submission.submit_via_confirmed_email(
        DB(),
        application.application_id,
        to_email=None,
        organization_id="org-1",
        user=SimpleNamespace(user_id="owner-1"),
    )
    assert result["status"] == "SUBMITTED"
    assert result["externally_submitted"] is True
    assert result["recipient"] == "apply@example.com"
    assert sent["to"] == ["apply@example.com"]
    assert sent["confirm_send"] is True
    assert "DRAFT cover letter" not in sent["body"]
    assert recorded["application_id"] == application.application_id
    assert recorded["provider"] == "email:smtp"


def test_email_send_failure_does_not_record_submission(monkeypatch):
    decided_at = submission.service.now()
    application = SimpleNamespace(
        application_id="NWA-EMAIL2",
        opportunity_id="NWO-EMAIL2",
        approval_state="APPROVED",
        approved_for_future_submission=True,
        externally_submitted=False,
        manual_submission_recorded=False,
        decided_at=decided_at,
    )
    opportunity = SimpleNamespace(
        opportunity_id="NWO-EMAIL2",
        opportunity_title="Research Support",
        description="Applications: email proposal to jobs@example.com.",
        requirements="",
        source_url="https://example.test/research",
    )
    material = SimpleNamespace(
        kind="proposal",
        body="DRAFT proposal outline.\n\nApproved proposal body.",
        created_at=decided_at - timedelta(seconds=2),
        updated_at=decided_at - timedelta(seconds=1),
    )

    class Query:
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def all(self):
            return [material]

    class DB:
        def query(self, *args, **kwargs):
            return Query()

    monkeypatch.setattr(submission.service, "get_application", lambda *a, **k: application)
    monkeypatch.setattr(submission.service, "get_opportunity", lambda *a, **k: opportunity)
    from app.core.nova.communications import service as communications_service
    def fail_send(*args, **kwargs):
        raise communications_service.NovaCommunicationsError("provider unavailable", status_code=502)
    monkeypatch.setattr(communications_service, "send_confirmed", fail_send)

    def should_not_record(*args, **kwargs):
        raise AssertionError("submission must not be recorded when transport fails")
    monkeypatch.setattr(submission.service, "record_confirmed_external_submission", should_not_record)

    with pytest.raises(submission.service.NovaWorkError):
        submission.submit_via_confirmed_email(
            DB(),
            application.application_id,
            to_email=None,
            organization_id="org-1",
            user=SimpleNamespace(user_id="owner-1"),
        )

