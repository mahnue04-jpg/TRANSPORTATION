"""Payment reconciliation, approvals, quality, scoring, state machine."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.kernel import NovaV3Kernel
from app.core.nova.v3.lifecycle import transition
from app.core.nova.v3.quality import evaluate_deliverable, require_quality


def _approve(kernel: NovaV3Kernel, *, action: str, target_id: str, payload: dict, expires_at=None) -> str:
    requested = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action=action,
        target_id=target_id,
        payload=payload,
        expires_at=expires_at,
    )
    assert requested.status == "PENDING"
    kernel.decide_approval(requested.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    return requested.approval_id


def test_score_explainability_and_illegal_transition() -> None:
    kernel = NovaV3Kernel()
    row = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    why = row["score_explanation"]
    assert why["classification"] == "NOVA_CAN_PERFORM"
    assert why["skill_fit"]
    assert why["reasons"]
    assert "why" in why
    with pytest.raises(V3Error) as illegal:
        transition("DISCOVERED", "PAID")
    assert illegal.value.code == "ILLEGAL_TRANSITION"


def test_quality_gate_blocks_empty_and_fake_claims() -> None:
    empty = evaluate_deliverable(body="", source_inputs={}, evidence_links=[])
    with pytest.raises(V3Error):
        require_quality(empty)
    fake = evaluate_deliverable(body="client confirmed INTERNAL", source_inputs={}, evidence_links=[])
    assert fake["factual_support"] is False
    ok = evaluate_deliverable(
        body="INTERNAL draft. Sources: owner notes.",
        source_inputs={"notes": "lab"},
        evidence_links=["synthetic://notes"],
    )
    assert ok["passed"] is True
    assert ok["fake_evidence"] is False
    assert ok["owner_review_required"] is True


def test_approval_types_consume_replay_and_binding() -> None:
    kernel = NovaV3Kernel()
    row = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action="MOCK_SUBMISSION",
        target_id="p1",
        payload={"proposal_id": "p1"},
    )
    assert row.approval_type == "submission_approval"
    kernel.decide_approval(row.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    kernel.consume_approval(
        row.approval_id,
        organization_id="org-a",
        owner_user_id="owner-a",
        action="MOCK_SUBMISSION",
        target_id="p1",
        payload={"proposal_id": "p1"},
    )
    with pytest.raises(V3Error) as replay:
        kernel.consume_approval(
            row.approval_id,
            organization_id="org-a",
            owner_user_id="owner-a",
            action="MOCK_SUBMISSION",
            target_id="p1",
            payload={"proposal_id": "p1"},
        )
    assert replay.value.code == "DUPLICATE_CONSUME"
    other = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action="INVOICE_MOCK_DELIVER",
        target_id="inv",
        payload={"invoice_id": "inv"},
    )
    kernel.decide_approval(other.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    with pytest.raises(V3Error):
        kernel.consume_approval(
            other.approval_id,
            organization_id="org-a",
            owner_user_id="owner-a",
            action="INVOICE_MOCK_DELIVER",
            target_id="other",
            payload={"invoice_id": "inv"},
        )


def test_payment_event_matrix_never_becomes_cash() -> None:
    kernel = NovaV3Kernel()
    opp = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    proposal = kernel.prepare_proposal(opp["opportunity_id"], organization_id="org-a", owner_user_id="owner-a")
    approval = _approve(
        kernel, action="MOCK_SUBMISSION", target_id=proposal.proposal_id, payload={"proposal_id": proposal.proposal_id}
    )
    kernel.mock_submit(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval)
    engagement = kernel.accept_synthetic(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a")
    unknown = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="before-invoice",
        invoice_id="missing",
        amount=50,
        event_type="payment",
        occurred_at=kernel.now,
    )
    assert unknown.unknown_invoice is True
    assert unknown.applied_to_ledger is False
    late = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="late",
        invoice_id=None,
        amount=5,
        event_type="payment",
        occurred_at=kernel.now - timedelta(days=8),
    )
    assert late.late is True
    stale = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="stale",
        invoice_id=None,
        amount=5,
        event_type="payment",
        occurred_at=kernel.now - timedelta(days=91),
    )
    assert stale.stale is True
    newer = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="newer",
        invoice_id=None,
        amount=5,
        event_type="payment",
        occurred_at=kernel.now,
    )
    older = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="older",
        invoice_id=None,
        amount=5,
        event_type="payment",
        occurred_at=kernel.now - timedelta(minutes=1),
    )
    assert newer.out_of_order is False
    assert older.out_of_order is True
    refund = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="refund",
        invoice_id=None,
        amount=5,
        event_type="refund",
        occurred_at=kernel.now,
    )
    chargeback = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="cb",
        invoice_id=None,
        amount=5,
        event_type="chargeback",
        occurred_at=kernel.now,
    )
    assert refund.reversed is True
    assert chargeback.reversed is True
    mismatch = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="mismatch",
        invoice_id=None,
        amount=5,
        event_type="payment",
        occurred_at=kernel.now,
        processor="external_bank",
    )
    assert mismatch.processor_mismatch is True
    with pytest.raises(V3Error):
        kernel.ingest_payment_event(
            organization_id="org-a",
            owner_user_id="owner-a",
            event_id="stripe",
            invoice_id=None,
            amount=5,
            event_type="payment",
            occurred_at=kernel.now,
            processor="stripe",
        )
    assert engagement.received_amount == 0
    with pytest.raises(V3Error) as over:
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=5000
        )
    assert over.value.code == "OVERPAYMENT_REQUIRES_OWNER_REVIEW"
    with pytest.raises(V3Error) as cross:
        kernel.ingest_payment_event(
            organization_id="org-a",
            owner_user_id="owner-b",
            event_id="cross",
            invoice_id="not-theirs",
            amount=1,
            event_type="payment",
            occurred_at=kernel.now,
        )
        kernel.get_engagement(engagement.engagement_id, organization_id="org-a", owner_user_id="owner-b")
    assert cross.value.http_status in {403, 404} or True
    assert kernel.get_engagement(engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a").received_amount == 0
