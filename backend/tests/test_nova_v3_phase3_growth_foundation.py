"""Nova V3 Phase 3 growth scoring, lifecycle, shield, quotes."""
from __future__ import annotations

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.growth.kernel import GrowthKernel
from app.core.nova.v3.growth.lifecycle import transition
from app.core.nova.v3.growth.quotes import prepare_quote
from app.core.nova.v3.growth.scoring import score_lead
from app.core.nova.v3.growth.fixtures import fixture


def test_growth_flags_are_hard_off() -> None:
    flags = live_flags()
    for key in (
        "LIVE_LEAD_DISCOVERY",
        "REAL_OUTREACH_SEND",
        "REAL_EMAIL_SEND",
        "REAL_SMS_SEND",
        "REAL_SOCIAL_POST",
        "REAL_AD_SPEND",
        "REAL_CALENDAR_WRITE",
        "REAL_CLIENT_CONTACT",
        "REAL_PROPOSAL_SEND",
        "REAL_CONTRACT_ACCEPTANCE",
        "REAL_PAYMENT_EXECUTION",
    ):
        assert flags[key] is False


def test_score_is_explainable() -> None:
    explained = score_lead(fixture("C"))
    assert explained["why"]
    assert explained["reasons"]
    assert explained["recommended_next_action"]
    assert explained["qualification_status"] == "QUALIFIED"
    assert explained["contactability"] is True


def test_illegal_lead_transition() -> None:
    with pytest.raises(V3Error) as exc:
        transition("DISCOVERED", "WON")
    assert exc.value.code == "ILLEGAL_TRANSITION"


def test_pricing_guard_no_invented_price_or_discount() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    missing = kernel.prepare_quote(
        lead.lead_id, "health_non_emergency_transport", organization_id="org-a", owner_user_id="owner-a"
    )
    assert missing.owner_action_required is True
    assert missing.amount is None
    with pytest.raises(V3Error) as disc:
        prepare_quote(lead, service_id="nova_ops_assist", discount_pct=50)
    assert disc.value.code == "UNAUTHORIZED_DISCOUNT"


def test_cross_owner_isolation() -> None:
    kernel = GrowthKernel()
    lead = kernel.discover(fixture("C"), organization_id="org-a", owner_user_id="owner-a")
    with pytest.raises(V3Error) as forbidden:
        kernel.get_lead(lead.lead_id, organization_id="org-a", owner_user_id="owner-b")
    assert forbidden.value.http_status == 403
