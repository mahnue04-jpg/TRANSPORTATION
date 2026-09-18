"""Nova V3 synthetic end-to-end revenue lab and attack paths."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.kernel import NovaV3Kernel


def _approve(kernel: NovaV3Kernel, *, action: str, target_id: str, payload: dict, expires_at=None) -> str:
    requested = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action=action,
        target_id=target_id,
        payload=payload,
        expires_at=expires_at,
    )
    kernel.decide_approval(requested.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    return requested.approval_id


def test_phase1_synthetic_revenue_success_path() -> None:
    kernel = NovaV3Kernel()
    ingested = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")
    opportunity = ingested["created"][0]
    assert opportunity["company_name"] == "Example Test Client LLC"
    proposal = kernel.prepare_proposal(opportunity["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    approval_id = _approve(
        kernel, action="MOCK_SUBMISSION", target_id=proposal.proposal_id, payload={"proposal_id": proposal.proposal_id}
    )
    submitted = kernel.mock_submit(
        proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval_id
    )
    assert submitted.externally_submitted is False
    assert submitted.mock_submitted is True
    engagement = kernel.accept_synthetic(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a")
    assert engagement.expected_amount == 1000
    work_approval = _approve(
        kernel,
        action="WORK_EXECUTE",
        target_id=engagement.engagement_id,
        payload={"work_type": "administrative_reporting", "engagement_id": engagement.engagement_id},
    )
    work = kernel.create_work_item(
        organization_id="org-a",
        owner_user_id="owner-a",
        engagement_id=engagement.engagement_id,
        work_type="administrative_reporting",
        source_inputs={"notes": "owner supplied"},
        approval_id=work_approval,
    )
    executed = kernel.execute_work(work.work_item_id, organization_id="org-a", owner_user_id="owner-a")
    assert executed.delivery_status == "INTERNAL_ONLY"
    assert "Not delivered" in executed.deliverable
    kernel.owner_approve_deliverable(work.work_item_id, organization_id="org-a", owner_user_id="owner-a")
    delivered = kernel.mock_deliver(work.work_item_id, organization_id="org-a", owner_user_id="owner-a")
    assert delivered.delivery_status == "MOCK_DELIVERED"
    invoice = kernel.create_invoice(
        organization_id="org-a",
        owner_user_id="owner-a",
        engagement_id=engagement.engagement_id,
        amount=1000,
        kind="fixed",
    )
    inv_approval = _approve(
        kernel,
        action="INVOICE_MOCK_DELIVER",
        target_id=invoice.invoice_id,
        payload={"invoice_id": invoice.invoice_id},
    )
    kernel.approve_invoice(
        invoice.invoice_id, organization_id="org-a", owner_user_id="owner-a", approval_id=inv_approval
    )
    mock_inv = kernel.mock_deliver_invoice(invoice.invoice_id, organization_id="org-a", owner_user_id="owner-a")
    assert mock_inv.stripe_invoice_created is False
    zero = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=0
    )
    assert zero.received_amount == 0
    event = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="evt-1",
        invoice_id=invoice.invoice_id,
        amount=400,
        event_type="payment",
        occurred_at=kernel.now,
    )
    assert event.applied_to_ledger is False
    assert kernel.get_engagement(engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a").received_amount == 0
    partial = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=400
    )
    assert partial.status == "PARTIALLY_PAID"
    assert partial.remaining_amount == 600
    paid = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1000
    )
    assert paid.status == "PAID"
    assert paid.remaining_amount == 0
    kernel.set_engagement_status(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", status="CLOSED"
    )
    diag = kernel.diagnostics(organization_id="org-a", owner_user_id="owner-a")
    assert diag["secrets_exposed"] is False
    assert diag["worker_run_status"] == "PREPARE_ONLY"
    assert diag["reconciliation_discrepancies"] == 0


def test_approval_and_payment_failure_paths() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    proposal = kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    denied = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
    )
    kernel.decide_approval(denied.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="REJECTED")
    with pytest.raises(V3Error) as rejected:
        kernel.mock_submit(
            proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=denied.approval_id
        )
    assert rejected.value.code == "REJECTED_APPROVAL"

    expired_id = _approve(
        kernel,
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
        expires_at=kernel.now,
    )
    kernel.now = kernel.now + timedelta(seconds=2)
    with pytest.raises(V3Error) as expired:
        kernel.mock_submit(
            proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=expired_id
        )
    assert expired.value.code == "EXPIRED_APPROVAL"

    live_id = _approve(
        kernel,
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
    )
    kernel.revoke_approval(live_id, organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as revoked:
        kernel.mock_submit(
            proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=live_id
        )
    assert revoked.value.code == "REVOKED_APPROVAL"


def test_payments_jobs_messages_and_freeze() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    proposal = kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    approval_id = _approve(
        kernel, action="MOCK_SUBMISSION", target_id=proposal.proposal_id, payload={"proposal_id": proposal.proposal_id}
    )
    kernel.mock_submit(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval_id)
    engagement = kernel.accept_synthetic(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=400
    )
    with pytest.raises(V3Error) as over:
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1500
        )
    assert over.value.code == "OVERPAYMENT_REQUIRES_OWNER_REVIEW"
    first = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="dup-1",
        invoice_id=None,
        amount=10,
        event_type="payment",
        occurred_at=kernel.now,
    )
    dup = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="dup-1",
        invoice_id=None,
        amount=99,
        event_type="payment",
        occurred_at=kernel.now,
    )
    assert dup.duplicate is True
    assert dup.amount == first.amount
    late = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="late-1",
        invoice_id=None,
        amount=5,
        event_type="payment",
        occurred_at=kernel.now - timedelta(days=30),
    )
    assert late.late is True
    refund = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="refund-1",
        invoice_id=None,
        amount=5,
        event_type="refund",
        occurred_at=kernel.now,
    )
    assert refund.applied_to_ledger is False
    correction = kernel.historical_correct(
        engagement.engagement_id,
        organization_id="org-a",
        owner_user_id="owner-a",
        original_amount=400,
        corrected_amount=350,
        reason="owner restated cash",
        authorized=True,
        idempotency_key="corr-1",
    )
    replay = kernel.historical_correct(
        engagement.engagement_id,
        organization_id="org-a",
        owner_user_id="owner-a",
        original_amount=400,
        corrected_amount=1,
        reason="owner restated cash",
        authorized=True,
        idempotency_key="corr-1",
    )
    assert replay.correction_id == correction.correction_id
    kernel.set_engagement_status(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", status="CANCELLED"
    )
    with pytest.raises(V3Error) as frozen:
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=350
        )
    assert frozen.value.code == "FINANCIAL_FREEZE"

    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="invoice_follow_up",
        timezone_name="America/New_York",
        frequency="daily",
    )
    again = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="invoice_follow_up",
        timezone_name="America/New_York",
        frequency="daily",
    )
    assert again.job_id == job.job_id
    kernel.pause_job(job.job_id, organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error):
        kernel.run_job(job.job_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.resume_job(job.job_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.run_job(job.job_id, organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error):
        kernel.run_job(job.job_id, organization_id="org-a", owner_user_id="owner-a")

    message = kernel.prepare_message(
        organization_id="org-a", owner_user_id="owner-a", channel="email", body="Internal draft only."
    )
    msg_approval = _approve(
        kernel,
        action="MOCK_MESSAGE",
        target_id=message.message_id,
        payload={"message_id": message.message_id, "channel": "email"},
    )
    sent = kernel.send_mock(
        message.message_id, organization_id="org-a", owner_user_id="owner-a", approval_id=msg_approval
    )
    assert sent.sent_externally is False
    other_job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-b",
        kind="invoice_follow_up",
        timezone_name="America/New_York",
        frequency="daily",
    )
    assert other_job.job_id != job.job_id
