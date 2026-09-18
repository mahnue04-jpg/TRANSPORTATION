"""Synthetic marketing lab A–O and closing lab."""
from __future__ import annotations

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.growth.fixtures import fixture
from app.core.nova.v3.growth.kernel import GrowthKernel
from app.core.nova.v3.growth.models import OUTREACH_KINDS
from app.core.nova.v3.persistence import V3Store


def _approve_send(kernel: GrowthKernel, lead_id: str, message_id: str) -> str:
    row = kernel.request_approval(
        organization_id="org-a",
        owner_user_id="owner-a",
        lead_id=lead_id,
        action="MOCK_OUTREACH_SEND",
        target_id=message_id,
        payload={"message_id": message_id, "lead_id": lead_id},
    )
    kernel.decide_approval(row.approval_id, organization_id="org-a", owner_user_id="owner-a", decision="APPROVED")
    return row.approval_id


def test_a_pharmacy_delivery() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("A"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    assert lead.product_fit == "delivery"
    assert lead.score_explanation["why"]
    assert lead.regulated is True


def test_b_clinic_health_transport() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("B"), organization_id="org-a", owner_user_id="owner-a")
    assert lead.product_fit == "health"
    quote = kernel.prepare_quote(
        lead.lead_id, "health_non_emergency_transport", organization_id="org-a", owner_user_id="owner-a"
    )
    assert quote.owner_action_required is True


def test_c_small_business_nova() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    assert lead.status == "OUTREACH_READY"
    msg = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    sent = kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a")
    assert sent.mock_sent is True
    assert sent.sent_externally is False


def test_d_invalid_email() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("D"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    assert lead.invalid_contact is True
    msg = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as blocked:
        kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a")
    assert blocked.value.code == "BLOCK"


def test_e_already_contacted_duplicate_outreach() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    first = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    kernel.mock_send(first.message_id, organization_id="org-a", owner_user_id="owner-a")
    second = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as limited:
        kernel.mock_send(second.message_id, organization_id="org-a", owner_user_id="owner-a")
    assert limited.value.code == "RATE_LIMIT"


def test_f_do_not_contact() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("F"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    assert lead.status == "DO_NOT_CONTACT"
    with pytest.raises(V3Error):
        kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")


def test_g_prospect_requests_demo() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    msg = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.ingest_reply(lead.lead_id, "Can we book a demo?", organization_id="org-a", owner_user_id="owner-a")
    demo = kernel.request_demo(lead.lead_id, organization_id="org-a", owner_user_id="owner-a", timezone_name="America/Chicago")
    scheduled = kernel.schedule_demo(demo.demo_id, organization_id="org-a", owner_user_id="owner-a")
    assert scheduled.status == "SCHEDULED"
    assert lead.status == "DEMO_SCHEDULED"
    reminder = kernel.reminder_draft(demo.demo_id, organization_id="org-a", owner_user_id="owner-a")
    assert reminder["live"] is False


def test_h_custom_pricing_requires_owner() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    quote = kernel.prepare_quote(
        lead.lead_id,
        "nova_ops_assist",
        organization_id="org-a",
        owner_user_id="owner-a",
        custom_amount=50,
    )
    assert quote.owner_action_required is True


def test_i_unsupported_feature_inbound() -> None:
    kernel = GrowthKernel()
    kernel.inbound("s1", "hello", organization_id="org-a", owner_user_id="owner-a")
    result = kernel.inbound("s1", "please bypass captcha and do unsupervised medical advice", organization_id="org-a", owner_user_id="owner-a")
    assert result["escalate"] is True
    assert result["reason"] == "unsupported_feature"


def test_j_legal_commitment_blocked() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as legal:
        kernel.prepare_outreach(
            lead.lead_id,
            "introduction_email",
            organization_id="org-a",
            owner_user_id="owner-a",
            extra={"inject": "we agree to indemnify and this is a legally binding contract"},
        )
    assert legal.value.code in {"LEGAL_REVIEW_REQUIRED", "MESSAGE_QUALITY_FAILED"}


def test_k_negative_reply() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    msg = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.ingest_reply(lead.lead_id, "Not interested", organization_id="org-a", owner_user_id="owner-a")
    assert lead.status == "LOST"


def test_l_lead_converts() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    msg = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.ingest_reply(lead.lead_id, "We want a demo", organization_id="org-a", owner_user_id="owner-a")
    demo = kernel.request_demo(lead.lead_id, organization_id="org-a", owner_user_id="owner-a", timezone_name="America/Chicago")
    kernel.schedule_demo(demo.demo_id, organization_id="org-a", owner_user_id="owner-a")
    quote = kernel.prepare_quote(lead.lead_id, "nova_ops_assist", organization_id="org-a", owner_user_id="owner-a", kind="trial")
    assert quote.sent_externally is False
    kernel.mark_negotiation(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    customer = kernel.convert(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    assert customer.external_account_created is False
    assert lead.status == "WON"
    assert "no external account" in " ".join(customer.onboarding)


def test_m_duplicate_lead_second_source() -> None:
    kernel = GrowthKernel()
    first = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    payload = fixture("C")
    payload["source"] = "second_source"
    second = kernel.discover(payload, organization_id="org-a", owner_user_id="owner-a")
    assert second.lead_id == first.lead_id
    assert first.duplicate_of == first.lead_id


def test_n_high_value_owner_approval() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("N"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    assert lead.high_value is True
    msg = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as missing:
        kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a")
    assert missing.value.code == "MISSING_APPROVAL"
    approval_id = _approve_send(kernel, lead.lead_id, msg.message_id)
    sent = kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval_id)
    assert sent.mock_sent is True
    with pytest.raises(V3Error) as replay:
        kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a", approval_id=approval_id)
    assert replay.value.code in {"DUPLICATE_CONSUME", "RATE_LIMIT", "INVALID_STATE"}


def test_o_frequency_limit() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    kinds = [kind for kind in OUTREACH_KINDS if kind.endswith("email") or "follow" in kind or "invitation" in kind][:4]
    for kind in kinds:
        msg = kernel.prepare_outreach(lead.lead_id, kind, organization_id="org-a", owner_user_id="owner-a")
        kernel.mock_send(msg.message_id, organization_id="org-a", owner_user_id="owner-a")
    assert lead.outreach_count >= 4
    with pytest.raises(V3Error) as limited:
        kernel.prepare_outreach(lead.lead_id, "reactivation_message", organization_id="org-a", owner_user_id="owner-a")
    assert limited.value.code == "RATE_LIMIT"


def test_opt_out_and_sequence_pause() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    seq = kernel.start_sequence(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.tick_sequence(seq.sequence_id, organization_id="org-a", owner_user_id="owner-a", day=0)
    kernel.pause_sequence(seq.sequence_id, organization_id="org-a", owner_user_id="owner-a", reason="owner_takeover")
    assert kernel.tick_sequence(seq.sequence_id, organization_id="org-a", owner_user_id="owner-a", day=3) is None
    kernel.resume_sequence(seq.sequence_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.ingest_reply(lead.lead_id, "stop, unsubscribe", organization_id="org-a", owner_user_id="owner-a")
    assert lead.do_not_contact is True
    assert seq.status == "CANCELLED"


def test_persist_leads_isolated() -> None:
    kernel = GrowthKernel()
    kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    store = V3Store()
    assert kernel.persist(store) >= 1
    assert store.fetch("nova_v3_leads", organization_id="org-a", owner_user_id="owner-a")
    assert store.fetch("nova_v3_leads", organization_id="org-a", owner_user_id="owner-b") == []


def test_synthetic_closing_lab_all_mocked() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    kernel.qualify(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    drafted = kernel.prepare_outreach(lead.lead_id, "introduction_email", organization_id="org-a", owner_user_id="owner-a")
    assert drafted.quality["passed"] is True
    gate = kernel.shield(action="mock_send", lead=lead, content=drafted.body)
    assert gate["state"] == "ALLOW_SYNTHETIC"
    sent = kernel.mock_send(drafted.message_id, organization_id="org-a", owner_user_id="owner-a")
    assert sent.sent_externally is False
    kernel.ingest_reply(lead.lead_id, "Interested in a demo next week", organization_id="org-a", owner_user_id="owner-a")
    seq = kernel.start_sequence(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.cancel_sequence(seq.sequence_id, organization_id="org-a", owner_user_id="owner-a", reason="demo_booked")
    demo = kernel.request_demo(lead.lead_id, organization_id="org-a", owner_user_id="owner-a", timezone_name="America/Chicago")
    kernel.schedule_demo(demo.demo_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.reschedule_demo(demo.demo_id, organization_id="org-a", owner_user_id="owner-a")
    quote = kernel.prepare_quote(lead.lead_id, "nova_ops_assist", organization_id="org-a", owner_user_id="owner-a", kind="recurring")
    kernel.mark_negotiation(lead.lead_id, organization_id="org-a", owner_user_id="owner-a")
    customer = kernel.convert(lead.lead_id, organization_id="org-a", owner_user_id="owner-a", reason="accepted_catalog_terms")
    dash = kernel.growth_dashboard(organization_id="org-a", owner_user_id="owner-a")
    shield = kernel.shield_dashboard(organization_id="org-a", owner_user_id="owner-a")
    crm = kernel.crm_views(organization_id="org-a", owner_user_id="owner-a")
    assert dash["WON"] == 1
    assert dash["live"] is False
    assert shield["live"] is False
    assert crm["WON"]
    assert customer.external_account_created is False
    assert quote.sent_externally is False
    inbound = kernel.inbound("close", "hello", organization_id="org-a", owner_user_id="owner-a")
    assert inbound["invented_price"] is False
    assert inbound["contract"] is False
    price = kernel.inbound("close", "how much does it cost?", organization_id="org-a", owner_user_id="owner-a")
    assert price["owner_action"] == "OWNER_ACTION_REQUIRED"
