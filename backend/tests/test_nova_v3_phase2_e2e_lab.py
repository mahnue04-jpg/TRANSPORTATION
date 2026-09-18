"""Nova V3 Phase 2 synthetic end-to-end lab scenarios A–L."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
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


def _engagement(kernel: NovaV3Kernel):
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    kernel.lab_action("approve_opportunity", {"opportunity_id": opp["opportunity_id"]}, organization_id="org-a", owner_user_id="owner-a")
    proposal = kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    kernel.lab_action("approve_proposal", {"proposal_id": proposal.proposal_id}, organization_id="org-a", owner_user_id="owner-a")
    kernel.lab_action("mock_submit", {"proposal_id": proposal.proposal_id}, organization_id="org-a", owner_user_id="owner-a")
    return kernel.accept_synthetic(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a")


def _delivered_work(kernel: NovaV3Kernel, engagement):
    work = kernel.lab_action(
        "create_task",
        {"engagement_id": engagement.engagement_id, "work_type": "administrative_reporting", "source_inputs": {"notes": "owner"}},
        organization_id="org-a",
        owner_user_id="owner-a",
    )
    kernel.execute_work(work.work_item_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.owner_approve_deliverable(work.work_item_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.mock_deliver(work.work_item_id, organization_id="org-a", owner_user_id="owner-a")
    return work


def test_a_normal_successful_work_to_revenue_lifecycle() -> None:
    kernel = NovaV3Kernel()
    engagement = _engagement(kernel)
    _delivered_work(kernel, engagement)
    invoice = kernel.create_invoice(
        organization_id="org-a",
        owner_user_id="owner-a",
        engagement_id=engagement.engagement_id,
        amount=1000,
        kind="fixed",
    )
    kernel.lab_action("approve_invoice", {"invoice_id": invoice.invoice_id}, organization_id="org-a", owner_user_id="owner-a")
    kernel.mock_deliver_invoice(invoice.invoice_id, organization_id="org-a", owner_user_id="owner-a")
    event = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="pay-full",
        invoice_id=invoice.invoice_id,
        amount=1000,
        event_type="payment",
        occurred_at=kernel.now,
    )
    assert event.applied_to_ledger is False
    assert kernel.get_engagement(engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a").received_amount == 0
    paid = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1000
    )
    assert paid.status == "PAID"
    kernel.set_engagement_status(engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", status="CLOSED")
    snapshot = kernel.lab_snapshot(organization_id="org-a", owner_user_id="owner-a")
    assert snapshot["audit"]
    flags = live_flags()
    assert flags["LIVE_DISCOVERY"] is False
    assert flags["REAL_WEBHOOK_PUBLIC_ENDPOINT"] is False
    assert flags["REAL_BACKGROUND_WORKER"] is False


def test_b_owner_rejects_opportunity() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    rejected = kernel.lab_action(
        "reject_opportunity", {"opportunity_id": opp["opportunity_id"]}, organization_id="org-a", owner_user_id="owner-a"
    )
    assert rejected.status == "REJECTED"
    with pytest.raises(V3Error):
        kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")


def test_c_proposal_approval_expires() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    proposal = kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    approval_id = _approve(
        kernel,
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
        expires_at=kernel.now,
    )
    kernel.now = kernel.now + timedelta(seconds=1)
    with pytest.raises(V3Error) as expired:
        kernel.mock_submit(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval_id)
    assert expired.value.code == "EXPIRED_APPROVAL"


def test_d_connector_temporarily_fails_and_retries() -> None:
    kernel = NovaV3Kernel()
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="connector_health_check",
        timezone_name="America/Chicago",
    )
    kernel.register_connector(organization_id="org-a", owner_user_id="owner-a", kind="crm", state="TEMPORARY_FAILURE")
    kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert job.status == "PREPARED"
    assert job.retry_count == 1
    kernel.connectors[next(iter(kernel.connectors))].state = "CONNECTED"
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert ran[0].status == "EXECUTED"


def test_e_scheduler_restarts_safely() -> None:
    kernel = NovaV3Kernel()
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="recurring_work",
        timezone_name="America/Chicago",
    )
    kernel.crash_before_job_commit = True
    kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    kernel.now = kernel.now + timedelta(seconds=45)
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert ran[0].job_id == job.job_id
    assert job.run_count == 1


def test_f_partial_then_full_payment() -> None:
    kernel = NovaV3Kernel()
    engagement = _engagement(kernel)
    _delivered_work(kernel, engagement)
    partial = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=400
    )
    assert partial.status == "PARTIALLY_PAID"
    paid = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1000
    )
    assert paid.status == "PAID"


def test_g_duplicate_payment_event() -> None:
    kernel = NovaV3Kernel()
    first = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="dup",
        invoice_id=None,
        amount=10,
        event_type="payment",
        occurred_at=kernel.now,
    )
    dup = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="dup",
        invoice_id=None,
        amount=99,
        event_type="payment",
        occurred_at=kernel.now,
    )
    assert dup.duplicate is True
    assert dup.amount == first.amount
    assert dup.applied_to_ledger is False


def test_h_overpayment_requires_owner_review() -> None:
    kernel = NovaV3Kernel()
    engagement = _engagement(kernel)
    with pytest.raises(V3Error) as over:
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1000.01
        )
    assert over.value.code == "OVERPAYMENT_REQUIRES_OWNER_REVIEW"


def test_i_cross_owner_isolation_attack() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    with pytest.raises(V3Error) as forbidden:
        kernel.get_opportunity(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-b")
    assert forbidden.value.http_status == 403
    with pytest.raises(V3Error) as hidden:
        kernel.get_opportunity(opp["opportunity_id"], organization_id="org-b", owner_user_id="owner-a")
    assert hidden.value.http_status == 404


def test_j_archived_engagement_mutation_attempt() -> None:
    kernel = NovaV3Kernel()
    engagement = _engagement(kernel)
    kernel.set_engagement_status(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", status="ARCHIVED"
    )
    with pytest.raises(V3Error) as frozen:
        kernel.lab_action(
            "create_task",
            {"engagement_id": engagement.engagement_id},
            organization_id="org-a",
            owner_user_id="owner-a",
        )
    assert frozen.value.code == "FINANCIAL_FREEZE"
    with pytest.raises(V3Error):
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1
        )


def test_k_credential_expiration_triggers_human_action_required() -> None:
    kernel = NovaV3Kernel()
    kernel.register_connector(organization_id="org-a", owner_user_id="owner-a", kind="opportunity_source", state="CONNECTED")
    kernel.register_credential(
        organization_id="org-a",
        owner_user_id="owner-a",
        provider="lab_board",
        credential_type="oauth",
        authorization_scope="readonly",
        expires_at=kernel.now - timedelta(seconds=1),
        refresh_capable=False,
        owner_approved=True,
    )
    kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="credential_expiry_check",
        timezone_name="America/Chicago",
    )
    kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    cred = next(iter(kernel.credentials.values()))
    connector = next(iter(kernel.connectors.values()))
    assert cred.connection_status == "HUMAN_ACTION_REQUIRED"
    assert connector.state == "HUMAN_ACTION_REQUIRED"


def test_l_cancelled_engagement_stops_future_worker_activity() -> None:
    kernel = NovaV3Kernel()
    engagement = _engagement(kernel)
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="stale_engagement_check",
        timezone_name="America/Chicago",
        ref_id=engagement.engagement_id,
    )
    kernel.set_engagement_status(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", status="CANCELLED"
    )
    assert job.status == "CANCELLED"
    assert kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
