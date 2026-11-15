"""Campaign scope, honest business counts, persistence and tenant isolation."""
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.growth_agent.acquisition import (
    AcquisitionReviewIn, campaign_board, save_campaign_review,
)
from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.models import GaContact, GaLeadEvent


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    GaContact.__table__.create(engine)
    GaLeadEvent.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            GaContact(id="real", organization_id="org-a", display_name="Example business"),
            GaContact(id="other", organization_id="org-b", display_name="Other tenant"),
            GaContact(id="demo", organization_id="org-a", is_synthetic_demo=True),
            GaContact(id="stop", organization_id="org-a", do_not_contact=True),
        ])
        session.commit()
        yield session
    engine.dispose()


def review(db, stage, contact="real", **changes):
    body = AcquisitionReviewIn(stage=stage, **{
        "has_open_inquiries": True, "authorized_list_use": True,
        "requires_external_sending": False, "requires_sensitive_data": False, **changes,
    })
    return save_campaign_review(db, "org-a", contact, body, actor_user_id="owner-a")


def test_saved_journey_does_not_claim_verified_money(db):
    for stage in ("new", "qualified", "quoted", "ordered", "delivered"):
        assert review(db, stage)["changed"]
    db.expire_all()
    board = campaign_board(db, "org-a")
    assert board["counts"]["delivered"] == 1
    assert sum(board["counts"].values()) == 1  # latest stage, not all events
    assert board["verified_revenue_cents"] is None
    assert board["contacts"][0]["review"]["payment_verified"] is False
    assert board["contacts"][0]["review"]["reviewed_by"] == "owner-a"
    assert board["external_actions_performed"] is False
    assert review(db, "delivered")["changed"] is False
    assert db.query(GaLeadEvent).count() == 5


@pytest.mark.parametrize("contact", ["other", "demo", "missing"])
def test_no_foreign_or_synthetic_contacts_can_be_assigned(db, contact):
    with pytest.raises(GrowthAgentError) as error:
        review(db, "new", contact=contact)
    assert error.value.http_status == 404
    assert db.query(GaLeadEvent).count() == 0
    assert campaign_board(db, "org-b")["total_reviewed"] == 0


@pytest.mark.parametrize("change", [
    {"has_open_inquiries": False}, {"authorized_list_use": False},
    {"requires_external_sending": True}, {"requires_sensitive_data": True},
])
def test_qualification_requires_verified_scope_answers(db, change):
    with pytest.raises(GrowthAgentError, match="scope blockers"):
        review(db, "qualified", **change)
    assert db.query(GaLeadEvent).count() == 0


def test_opted_out_contact_is_never_qualified(db):
    saved = review(db, "new", contact="stop")
    assert saved["review"]["scope_blockers"]
    with pytest.raises(GrowthAgentError):
        review(db, "qualified", contact="stop")


def test_cannot_skip_to_sale_or_rewrite_completed_delivery(db):
    with pytest.raises(GrowthAgentError, match="Cannot move"):
        review(db, "ordered")
    for stage in ("qualified", "quoted", "ordered", "delivered"):
        review(db, stage)
    with pytest.raises(GrowthAgentError, match="Cannot move"):
        review(db, "new")


def test_no_synthetic_or_other_tenant_counts_and_no_implicit_attribution(db):
    board = campaign_board(db, "org-a")
    assert board["total_reviewed"] == 0
    assert board["unassigned_contacts"] == 2
    assert not board["contacts"]
    review(db, "new")
    assert campaign_board(db, "org-a")["unassigned_contacts"] == 1
    assert campaign_board(db, "org-b")["contacts"] == []


def test_schema_rejects_false_consent_strings_and_fake_revenue():
    values = dict(stage="qualified", has_open_inquiries=True, authorized_list_use=True,
                  requires_external_sending=False, requires_sensitive_data=False)
    for patch in ({"authorized_list_use": "false"}, {"verified_revenue_cents": 100000}, {"stage": "paid"}):
        with pytest.raises(ValidationError):
            AcquisitionReviewIn(**(values | patch))


def test_counts_are_not_limited_to_visible_page(db):
    db.add_all([GaContact(id=f"c{i}", organization_id="org-a") for i in range(105)])
    db.commit()
    for i in range(105):
        review(db, "new", contact=f"c{i}")
    board = campaign_board(db, "org-a")
    assert board["total_reviewed"] == board["counts"]["new"] == 105
    assert len(board["contacts"]) == board["contact_limit"] == 100
