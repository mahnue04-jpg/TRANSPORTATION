"""Offline contract tests: no live network, customer data, payment or sending."""
from __future__ import annotations

import pytest

from app.core.nova.work_revenue.shared_evidence import EvidenceError, Stage, make_event


def event(previous=Stage.OWNER_APPROVED, current=Stage.SENT_VERIFIED, **overrides):
    data = dict(
        tenant_id="tenant-a",
        record_tenant_id="tenant-a",
        opportunity_id="lead-1",
        actor_id="owner-1",
        previous=previous,
        current=current,
        evidence={"transport_receipt_id": "mail-msg-123", "receipt_kind": "external_verified"},
    )
    data.update(overrides)
    return make_event(**data)


def test_verified_send_is_deterministic():
    first = event()
    assert first.current == Stage.SENT_VERIFIED
    assert first.idempotency_key == event().idempotency_key
    assert len(first.idempotency_key) == 64


@pytest.mark.parametrize("receipt_kind", ["mock", "local", "", None])
def test_mock_or_missing_receipts_never_count_as_sent(receipt_kind):
    with pytest.raises(EvidenceError):
        event(evidence={"transport_receipt_id": "fake", "receipt_kind": receipt_kind})


def test_cross_tenant_denied():
    with pytest.raises(EvidenceError, match="Cross-tenant"):
        event(record_tenant_id="tenant-b")


def test_skipped_stage_denied():
    with pytest.raises(EvidenceError, match="Unsupported"):
        event(previous=Stage.DISCOVERED, current=Stage.RECEIVED_VERIFIED)


def test_no_payment_without_independent_confirmation():
    with pytest.raises(EvidenceError, match="independent"):
        event(
            previous=Stage.DELIVERED_VERIFIED,
            current=Stage.RECEIVED_VERIFIED,
            evidence={"payment_confirmation_id": "owner-says-paid", "payment_kind": "owner_confirmed"},
        )


def test_payment_with_independent_confirmation():
    result = event(
        previous=Stage.DELIVERED_VERIFIED,
        current=Stage.RECEIVED_VERIFIED,
        evidence={"payment_confirmation_id": "processor-transaction-1", "payment_kind": "independently_verified"},
    )
    assert result.current == Stage.RECEIVED_VERIFIED


def test_job_artifact_requires_sha256():
    with pytest.raises(EvidenceError, match="SHA-256"):
        event(previous=Stage.CONTRACTED, current=Stage.JOB_COMPLETED, evidence={"artifact_sha256": "not-a-hash"})


def test_job_artifact_accepts_sha256():
    result = event(
        previous=Stage.CONTRACTED,
        current=Stage.JOB_COMPLETED,
        evidence={"artifact_sha256": "a" * 64},
    )
    assert result.evidence_type == "artifact_sha256"


@pytest.mark.parametrize("reference", [None, 123, "\nforged-event", "id\x00suffix", "x" * 1025])
def test_malformed_evidence_references_are_rejected(reference):
    with pytest.raises(EvidenceError, match="Missing or invalid"):
        event(evidence={"transport_receipt_id": reference, "receipt_kind": "external_verified"})


def test_non_mapping_evidence_is_rejected():
    with pytest.raises(EvidenceError, match="mapping"):
        event(evidence=None)


def test_synthetic_revenue_to_operations_delivery_lifecycle():
    """Offline first-client journey: evidence gates only; no live sends or jobs."""
    steps = (
        (Stage.DISCOVERED, Stage.QUALIFIED, {"source_url": "https://example.com/lead"}),
        (Stage.QUALIFIED, Stage.DRAFTED, {"draft_id": "synthetic-draft-1"}),
        (Stage.DRAFTED, Stage.OWNER_APPROVED, {"owner_approval_id": "synthetic-approval-1"}),
        (Stage.OWNER_APPROVED, Stage.SENT_VERIFIED, {
            "transport_receipt_id": "synthetic-verified-transport-1",
            "receipt_kind": "external_verified",
        }),
        (Stage.SENT_VERIFIED, Stage.REPLIED, {"reply_message_id": "synthetic-reply-1"}),
        (Stage.REPLIED, Stage.CONTRACTED, {"contract_reference": "synthetic-contract-1"}),
        (Stage.CONTRACTED, Stage.JOB_COMPLETED, {"artifact_sha256": "a" * 64}),
        (Stage.JOB_COMPLETED, Stage.DELIVERED_VERIFIED, {
            "delivery_receipt_id": "synthetic-delivery-1",
        }),
        (Stage.DELIVERED_VERIFIED, Stage.RECEIVED_VERIFIED, {
            "payment_confirmation_id": "synthetic-processor-1",
            "payment_kind": "independently_verified",
        }),
    )
    events = []
    for previous, current, evidence in steps:
        events.append(event(previous=previous, current=current, evidence=evidence))
    assert len(events) == 9
    assert len({item.idempotency_key for item in events}) == 9
    assert events[0].previous == Stage.DISCOVERED
    assert events[-1].current == Stage.RECEIVED_VERIFIED
    # This test only validates evidence contracts. It does not independently
    # verify the synthetic references or execute an actual customer workflow.


def test_synthetic_handoff_rejects_unverified_customer_delivery():
    with pytest.raises(EvidenceError, match="Unsupported stage transition"):
        event(
            previous=Stage.CONTRACTED,
            current=Stage.DELIVERED_VERIFIED,
            evidence={"delivery_receipt_id": "synthetic-delivery"},
        )
