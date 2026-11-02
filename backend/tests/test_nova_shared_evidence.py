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
