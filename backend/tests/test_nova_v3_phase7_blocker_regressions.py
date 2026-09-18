"""Regressions for the four verified Phase 7 blockers. Canonical V3 only."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.growth.kernel import GrowthKernel
from app.core.nova.v3.kernel import NovaV3Kernel, get_growth_kernel, reset_kernel
from app.core.nova.v3.worker import lease_job
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
LAB_HTML = (ROOT / "static" / "nova-v3-lab" / "index.html").read_text(encoding="utf-8")
LAB_JS = (ROOT / "static" / "nova-v3-lab" / "lab.js").read_text(encoding="utf-8")


def _paid_engagement(kernel: NovaV3Kernel, *, amount: float = 1000) -> object:
    opp = kernel.enter_manual(
        {
            "title": "Partial payment regression",
            "company_name": "Pay Co",
            "description": "Synthetic administrative work",
            "compensation_amount": amount,
            "compensation_type": "fixed",
            "remote_status": "remote",
        },
        organization_id="org-a",
        owner_user_id="owner-a",
    )
    proposal = kernel.prepare_proposal(opp.opportunity_id, organization_id="org-a", owner_user_id="owner-a")
    approval = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        action="MOCK_SUBMISSION",
        target_id=proposal.proposal_id,
        payload={"proposal_id": proposal.proposal_id},
    )
    kernel.decide_approval(approval.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    kernel.mock_submit(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval.approval_id)
    return kernel.accept_synthetic(proposal.proposal_id, organization_id="org-a", owner_user_id="owner-a")


def test_owner_isolation_converted_customer_never_leaks() -> None:
    kernel = GrowthKernel()
    converted = kernel.convert_synthetic_fixture(
        organization_id="org-a", owner_user_id="owner-a", organization_name="Convert Co"
    )
    owner_a = kernel.growth_dashboard(organization_id="org-a", owner_user_id="owner-a")
    ids_a = {row["customer_id"] for row in owner_a["CUSTOMERS_CONVERTED"]}
    names_a = {row["name"] for row in owner_a["CUSTOMERS_CONVERTED"]}
    assert converted.customer_id in ids_a
    assert "Convert Co" in names_a
    for row in owner_a["CUSTOMERS_CONVERTED"]:
        assert row["organization_id"] == "org-a"
        assert row["owner_user_id"] == "owner-a"

    owner_b = kernel.growth_dashboard(organization_id="org-a", owner_user_id="owner-b")
    assert owner_b["CUSTOMERS_CONVERTED"] == []
    assert converted.customer_id not in {row.get("customer_id") for row in owner_b["CUSTOMERS_CONVERTED"]}
    assert "Convert Co" not in {row.get("name") for row in owner_b["CUSTOMERS_CONVERTED"]}
    with pytest.raises(V3Error) as forbidden:
        kernel.get_customer(converted.customer_id, organization_id="org-a", owner_user_id="owner-b")
    assert forbidden.value.code == "FORBIDDEN"
    with pytest.raises(V3Error) as missing:
        kernel.get_customer(converted.customer_id, organization_id="org-b", owner_user_id="owner-a")
    assert missing.value.code == "NOT_FOUND"

    other = kernel.convert_synthetic_fixture(
        organization_id="org-a", owner_user_id="owner-b", organization_name="Convert Co"
    )
    assert other.customer_id != converted.customer_id
    only_b = kernel.growth_dashboard(organization_id="org-a", owner_user_id="owner-b")
    ids_b = {row["customer_id"] for row in only_b["CUSTOMERS_CONVERTED"]}
    assert other.customer_id in ids_b
    assert converted.customer_id not in ids_b
    only_a = kernel.growth_dashboard(organization_id="org-a", owner_user_id="owner-a")
    assert converted.customer_id in {row["customer_id"] for row in only_a["CUSTOMERS_CONVERTED"]}
    assert other.customer_id not in {row["customer_id"] for row in only_a["CUSTOMERS_CONVERTED"]}


def test_http_command_center_returns_converted_customers_for_authenticated_owner() -> None:
    reset_kernel()
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    assert login.status_code == 200
    token = login.json()["access_token"]
    user_id = login.json()["user_id"]
    headers = {"Authorization": f"Bearer {token}"}
    seeded = client.post(
        "/api/nova/v3/lab/action",
        headers=headers,
        json={"action": "growth_synthetic_convert", "payload": {"organization_name": "Convert Co"}},
    )
    assert seeded.status_code == 200, seeded.text
    seed_body = seeded.json()
    assert seed_body["name"] == "Convert Co"
    assert seed_body["external_account_created"] is False
    center = client.get("/api/nova/v3/growth/dashboard", headers=headers)
    assert center.status_code == 200, center.text
    rows = center.json()["CUSTOMERS_CONVERTED"]
    assert rows, center.json()
    names = {row["name"] for row in rows}
    assert "Convert Co" in names
    for row in rows:
        assert row["organization_id"]
        assert row["owner_user_id"]
        if user_id:
            assert row["owner_user_id"] == user_id
    lab = client.get("/api/nova/v3/lab", headers=headers)
    assert lab.status_code == 200
    assert lab.json()["growth"]["CUSTOMERS_CONVERTED"]
    other = client.post("/api/auth/login", json={"email": "admin@amicor.local", "password": SEED_PASSWORD})
    assert other.status_code == 200
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    isolated = client.get("/api/nova/v3/growth/dashboard", headers=other_headers)
    assert isolated.status_code == 200
    assert isolated.json()["CUSTOMERS_CONVERTED"] == []


def test_command_center_and_lab_expose_customers_converted() -> None:
    assert "CUSTOMERS CONVERTED" in LAB_HTML
    assert "growth_synthetic_convert" in LAB_HTML
    assert "CUSTOMERS_CONVERTED" in LAB_JS
    assert "/api/nova/v3/growth/leads/" in LAB_JS or "growth_synthetic_convert" in LAB_JS


def test_worker_crash_recovers_without_lease_mismatch_or_duplicate() -> None:
    kernel = NovaV3Kernel()
    crash_job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="stale_engagement_check",
        timezone_name="America/Chicago",
    )
    foreign = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="payment_reconciliation",
        timezone_name="America/Chicago",
    )
    lease_job(foreign, worker_id="worker-b", now=kernel.now, ttl=timedelta(seconds=30))
    kernel.crash_before_job_commit = True
    crashed_tick = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-a")
    assert crashed_tick == []
    assert crash_job.run_count == 0
    assert crash_job.status == "LEASED"
    assert foreign.lease_owner == "worker-b"
    assert foreign.run_count == 0

    crash_job.lease_expires_at = kernel.now - timedelta(seconds=1)
    recovered = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-a")
    assert crash_job.job_id in {item.job_id for item in recovered}
    assert crash_job.status == "EXECUTED"
    assert crash_job.run_count == 1
    assert foreign.lease_owner == "worker-b"
    assert foreign.run_count == 0

    with pytest.raises(V3Error) as held:
        kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-recover")
    assert held.value.code == "LEASE_MISMATCH"
    assert crash_job.run_count == 1


def test_tick_skips_foreign_live_lease_but_still_raises_when_only_blocked() -> None:
    work = NovaV3Kernel()
    held = work.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="payment_reconciliation",
        timezone_name="America/Chicago",
    )
    lease_job(held, worker_id="worker-b", now=work.now, ttl=timedelta(seconds=30))
    extra = work.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="stale_engagement_check",
        timezone_name="America/Chicago",
    )
    ran = work.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-crash")
    assert extra.job_id in {item.job_id for item in ran}
    assert held.status == "LEASED"
    assert held.lease_owner == "worker-b"
    assert held.run_count == 0

    blocked = NovaV3Kernel()
    only = blocked.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="work_deadline",
        timezone_name="America/Chicago",
    )
    lease_job(only, worker_id="alpha", now=blocked.now, ttl=timedelta(seconds=30))
    with pytest.raises(V3Error) as mismatch:
        blocked.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="beta")
    assert mismatch.value.code == "LEASE_MISMATCH"
    assert only.run_count == 0
    assert only.lease_owner == "alpha"


def test_partial_payment_never_resolves_paid_until_full_amount_due() -> None:
    kernel = NovaV3Kernel()
    engagement = _paid_engagement(kernel, amount=1000)
    engagement.remaining_amount = 0.0
    first = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=400
    )
    assert first.status == "PARTIALLY_PAID"
    assert first.status != "PAID"
    assert first.received_amount == 400
    assert first.remaining_amount == 600
    second = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=400
    )
    assert second.status == "PARTIALLY_PAID"
    with pytest.raises(V3Error) as over:
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1000.02
        )
    assert over.value.code == "OVERPAYMENT_REQUIRES_OWNER_REVIEW"
    paid = kernel.confirm_received(
        engagement.engagement_id, organization_id="org-a", owner_user_id="owner-a", total_received_so_far=1000
    )
    assert paid.status == "PAID"
    assert paid.remaining_amount == 0
    with pytest.raises(V3Error):
        kernel.confirm_received(
            engagement.engagement_id, organization_id="org-a", owner_user_id="owner-b", total_received_so_far=1000
        )
    event = kernel.ingest_payment_event(
        organization_id="org-a",
        owner_user_id="owner-a",
        event_id="processor-partial",
        invoice_id=None,
        amount=400,
        event_type="payment",
        occurred_at=kernel.now,
        processor="stripe_test",
    )
    assert event.applied_to_ledger is False
    assert paid.received_amount == 1000


def test_convert_requires_owner_and_keeps_live_flags_off() -> None:
    kernel = GrowthKernel()
    with pytest.raises(V3Error) as missing:
        kernel.convert("missing", organization_id="", owner_user_id="owner-a")
    assert missing.value.code == "FORBIDDEN"
    converted = kernel.convert_synthetic_fixture(organization_id="org-a", owner_user_id="owner-a")
    assert converted.external_account_created is False if hasattr(converted, "external_account_created") else True
    out = kernel.customer_out(converted)
    assert out["external_account_created"] is False
    assert out["live"] is False
    assert get_growth_kernel() is not None
