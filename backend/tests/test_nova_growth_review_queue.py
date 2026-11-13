"""Isolated integration checks for the read-only Growth Agent review queue."""
from __future__ import annotations

import os

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ["NOVA_GROWTH_AGENT_DEMO_MODE"] = "true"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.nova.growth_agent.models import GaWorkflowRun, GaWorkflowDefinition, GaDeliveryAttempt, GaAuditEvent
from app.core.nova.growth_agent.service import GrowthAgentService
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.db.session import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    ensure_growth_agent_schema(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(svc, org):
    svc.upsert_profile(
        org, "owner-test",
        {
            "business_name": "Test Office",
            "website": "https://example.test",
            "timezone": "America/Chicago",
            "operating_hours": {"mon_fri": "09:00-17:00"},
            "services": [{"code": "consult", "name": "Consultation", "duration_minutes": 30}],
            "faqs": [{"id": "hours", "question": "Hours?", "answer": "9 to 5"}],
            "contact_email": "owner@example.test",
            "handoff_phone": "+15555550101",
            "escalation_settings": {"handoff_on_unknown": True},
        },
        activate=True,
    )
    contact = svc._upsert_contact(
        org, name="Test Lead", email="lead-" + org + "@example.test",
        consent_transactional=True, consent_marketing=False, channel="email", source="synthetic_test",
    )
    svc.db.commit()
    return contact


def test_preview_queue_is_tenant_scoped_read_only_and_excludes_completed(db):
    svc = GrowthAgentService(db)
    first, second = "owner-org-1", "owner-org-2"
    lead_a = _seed(svc, first)
    lead_b = _seed(svc, second)
    before_a = svc.preview_workflow(first, workflow_code="inquiry_ack", contact_id=lead_a.id)
    before_b = svc.preview_workflow(second, workflow_code="inquiry_ack", contact_id=lead_b.id)

    audit_count = db.query(GaAuditEvent).count()
    delivery_count = db.query(GaDeliveryAttempt).count()
    rows = svc.list_workflow_review_queue(first)
    assert any(row["run_id"] == before_a["run_id"] for row in rows)
    assert not any(row["run_id"] == before_b["run_id"] for row in rows)
    assert all(row["requires_approval"] is True for row in rows)
    assert all(row["status"] in ("preview", "awaiting_approval") for row in rows)
    assert db.query(GaAuditEvent).count() == audit_count
    assert db.query(GaDeliveryAttempt).count() == delivery_count

    db.query(GaWorkflowRun).filter_by(id=before_a["run_id"]).update({"status": "completed"})
    db.commit()
    assert not any(row["run_id"] == before_a["run_id"] for row in svc.list_workflow_review_queue(first))


def test_nonapproval_workflows_are_excluded_and_preview_details_are_not_leaked(db):
    svc = GrowthAgentService(db)
    org = "owner-org-3"
    contact = _seed(svc, org)
    run = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
    workflow = db.query(GaWorkflowDefinition).filter_by(organization_id=org, code="inquiry_ack").one()
    workflow.requires_approval = False
    db.commit()
    assert all(row["run_id"] != run["run_id"] for row in svc.list_workflow_review_queue(org))

    workflow.requires_approval = True
    db.commit()
    rows = svc.list_workflow_review_queue(org)
    found = next(row for row in rows if row["run_id"] == run["run_id"])
    assert set(found) == {
        "run_id", "workflow_code", "workflow_name", "status", "requires_approval",
        "dry_run", "is_synthetic_demo", "created_at",
    }
    assert not any("message" in key or "email" in key or "token" in key for key in found)


def test_queue_limit_is_bounded(db):
    svc = GrowthAgentService(db)
    org = "owner-org-4"
    contact = _seed(svc, org)
    for _ in range(3):
        svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
    assert len(svc.list_workflow_review_queue(org, limit=2)) <= 2
    assert len(svc.list_workflow_review_queue(org, limit=0)) <= 1


def test_review_details_are_tenant_scoped_redacted_and_read_only(db):
    from app.core.nova.growth_agent.errors import GrowthAgentError

    svc = GrowthAgentService(db)
    org, other = "review-detail-owner", "review-detail-other"
    lead = _seed(svc, org)
    _seed(svc, other)
    run = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=lead.id)
    before_audits = db.query(GaAuditEvent).count()
    before_attempts = db.query(GaDeliveryAttempt).count()
    detail = svc.workflow_review_details(org, run["run_id"])
    assert detail["run_id"] == run["run_id"]
    assert detail["content_redacted"] is True
    assert detail["execution_performed"] is False
    assert detail["requires_approval"] is True
    assert detail["step_count"] >= 1
    assert len(detail["steps"]) >= 1
    assert all(set(step).issubset({"channel", "scheduled_for_utc", "quiet_hours_adjusted"}) for step in detail["steps"])
    assert "messages" not in detail and "contact_id" not in detail
    assert "body_preview" not in repr(detail)
    assert db.query(GaAuditEvent).count() == before_audits
    assert db.query(GaDeliveryAttempt).count() == before_attempts
    with pytest.raises(GrowthAgentError) as other_error:
        svc.workflow_review_details(other, run["run_id"])
    assert other_error.value.http_status == 404

    db.query(GaWorkflowRun).filter_by(id=run["run_id"]).update({"status": "completed"})
    db.commit()
    with pytest.raises(GrowthAgentError) as completed_error:
        svc.workflow_review_details(org, run["run_id"])
    assert completed_error.value.http_status == 404


def test_owner_reject_is_audited_and_blocks_execution(db):
    from app.core.nova.growth_agent.errors import GrowthAgentError

    svc = GrowthAgentService(db)
    org = "review-reject-owner"
    lead = _seed(svc, org)
    preview = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=lead.id)
    before = db.query(GaDeliveryAttempt).count()
    result = svc.decide_workflow_review(
        org, preview["run_id"], decision="reject", actor_user_id="owner-test"
    )
    assert result == {
        "run_id": preview["run_id"], "decision": "reject", "status": "cancelled",
        "execution_performed": False, "live_send": False,
    }
    assert db.query(GaDeliveryAttempt).count() == before
    assert any(e.action == "workflow.review.reject" and e.entity_id == preview["run_id"]
               for e in db.query(GaAuditEvent).all())
    assert svc.list_workflow_review_queue(org) == []
    with pytest.raises(GrowthAgentError) as denied:
        svc.approve_and_execute_workflow(org, run_id=preview["run_id"], dry_run=True)
    assert denied.value.http_status == 409
    with pytest.raises(GrowthAgentError) as repeated:
        svc.decide_workflow_review(org, preview["run_id"], decision="reject")
    assert repeated.value.http_status == 409


def test_request_information_blocks_execution_and_cross_tenant_decisions(db):
    from app.core.nova.growth_agent.errors import GrowthAgentError

    svc = GrowthAgentService(db)
    org, other = "review-info-owner", "review-other-owner"
    lead = _seed(svc, org)
    _seed(svc, other)
    preview = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=lead.id)
    with pytest.raises(GrowthAgentError) as cross:
        svc.decide_workflow_review(other, preview["run_id"], decision="reject")
    assert cross.value.http_status == 409
    result = svc.decide_workflow_review(
        org, preview["run_id"], decision="request_information", actor_user_id="owner-test"
    )
    assert result["status"] == "needs_information"
    assert result["execution_performed"] is False
    with pytest.raises(GrowthAgentError) as denied:
        svc.approve_and_execute_workflow(org, run_id=preview["run_id"], dry_run=True)
    assert denied.value.http_status == 409
    with pytest.raises(GrowthAgentError) as bad:
        svc.decide_workflow_review(org, preview["run_id"], decision="approve", actor_user_id="owner-test")
    assert bad.value.http_status == 409


def test_explicit_owner_approval_records_state_but_does_not_execute(db):
    from app.core.nova.growth_agent.errors import GrowthAgentError

    svc = GrowthAgentService(db)
    org = "review-approve-owner"
    contact = _seed(svc, org)
    preview = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
    before_attempts = db.query(GaDeliveryAttempt).count()
    with pytest.raises(GrowthAgentError) as anonymous:
        svc.decide_workflow_review(org, preview["run_id"], decision="approve")
    assert anonymous.value.http_status == 403
    with pytest.raises(GrowthAgentError) as no_approval:
        svc.approve_and_execute_workflow(
            org, run_id=preview["run_id"], dry_run=False, actor_user_id="owner-test"
        )
    assert no_approval.value.http_status == 403

    result = svc.decide_workflow_review(
        org, preview["run_id"], decision="approve", actor_user_id="owner-test"
    )
    assert result == {
        "run_id": preview["run_id"], "decision": "approve", "status": "approved",
        "execution_performed": False, "live_send": False,
    }
    assert db.query(GaDeliveryAttempt).count() == before_attempts
    assert any(
        event.action == "workflow.review.approve" and event.entity_id == preview["run_id"]
        for event in db.query(GaAuditEvent).all()
    )
    with pytest.raises(GrowthAgentError) as duplicate:
        svc.decide_workflow_review(
            org, preview["run_id"], decision="approve", actor_user_id="owner-test"
        )
    assert duplicate.value.http_status == 409
