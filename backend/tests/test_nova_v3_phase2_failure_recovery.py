"""Failure injection and recovery for Nova V3 Phase 2."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.kernel import NovaV3Kernel
from app.core.nova.v3.persistence import V3Store
from app.core.nova.v3.webhooks import sign_lab_payload
from app.core.nova.v3.worker import lease_job


def test_database_write_failure_recovery() -> None:
    kernel = NovaV3Kernel()
    kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")
    store = V3Store()
    kernel.fail_next_persist = True
    with pytest.raises(RuntimeError):
        kernel.persist(store)
    assert kernel.persist(store) >= 1


def test_duplicate_event_and_malformed_webhook() -> None:
    kernel = NovaV3Kernel()
    payload = {"type": "x", "amount": 1}
    signature = sign_lab_payload(payload)
    kernel.ingest_lab_webhook(
        organization_id="org-a",
        owner_user_id="owner-a",
        provider="lab",
        event_id="same",
        payload=payload,
        signature=signature,
    )
    dup = kernel.ingest_lab_webhook(
        organization_id="org-a",
        owner_user_id="owner-a",
        provider="lab",
        event_id="same",
        payload=payload,
        signature=signature,
    )
    assert dup.duplicate is True
    with pytest.raises(V3Error) as malformed:
        kernel.ingest_lab_webhook(
            organization_id="org-a",
            owner_user_id="owner-a",
            provider="lab",
            event_id="",
            payload=payload,
            signature=signature,
        )
    assert malformed.value.code == "MALFORMED_WEBHOOK"


def test_retry_exhaustion_and_stale_lock() -> None:
    kernel = NovaV3Kernel()
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="connector_health_check",
        timezone_name="America/Chicago",
    )
    job.max_attempts = 2
    kernel.register_connector(
        organization_id="org-a", owner_user_id="owner-a", kind="invoice_delivery", state="TEMPORARY_FAILURE"
    )
    kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert job.dead_letter is True
    other = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="payment_reconciliation",
        timezone_name="America/Chicago",
    )
    lease_job(other, worker_id="w1", now=kernel.now, ttl=timedelta(seconds=1))
    kernel.now = kernel.now + timedelta(seconds=5)
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="w2")
    assert any(item.job_id == other.job_id for item in ran)


def test_approval_expiry_and_owner_revoke_mid_flow() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    proposal = kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    requested = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
        expires_at=kernel.now,
    )
    kernel.decide_approval(requested.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    kernel.now = kernel.now + timedelta(seconds=2)
    with pytest.raises(V3Error) as expired:
        kernel.mock_submit(
            proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=requested.approval_id
        )
    assert expired.value.code == "EXPIRED_APPROVAL"
    live = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
    )
    kernel.decide_approval(live.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    kernel.revoke_approval(live.approval_id, organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as revoked:
        kernel.mock_submit(
            proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=live.approval_id
        )
    assert revoked.value.code == "REVOKED_APPROVAL"


def test_payment_before_invoice_paused_and_cross_owner() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    proposal = kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    approval = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
    )
    kernel.decide_approval(approval.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    kernel.mock_submit(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval.approval_id)
    engagement = kernel.accept_synthetic(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a")
    before = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="early",
        invoice_id="no-invoice",
        amount=25,
        event_type="payment",
        occurred_at=kernel.now,
    )
    assert before.unknown_invoice is True
    assert engagement.received_amount == 0
    kernel.pause_engagement(engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as paused:
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=10
        )
    assert paused.value.code == "PAUSED_WORKFLOW"
    with pytest.raises(V3Error) as owner:
        kernel.get_engagement(engagement.engagement_id, organization_id="org-a", owner_user_id="owner-b")
    assert owner.value.http_status == 403


def test_concurrent_worker_execution_guard() -> None:
    kernel = NovaV3Kernel()
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="work_deadline",
        timezone_name="America/Chicago",
    )
    lease_job(job, worker_id="alpha", now=kernel.now, ttl=timedelta(seconds=30))
    with pytest.raises(V3Error) as mismatch:
        kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="beta")
    assert mismatch.value.code == "LEASE_MISMATCH"
