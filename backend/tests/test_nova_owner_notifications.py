from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.nova.work_revenue import owner_notifications


def test_owner_approval_notification_sends_only_after_commit(monkeypatch):
    sent = []
    monkeypatch.setattr(owner_notifications, "_send", lambda payload: sent.append(payload))
    session = Session()
    action = SimpleNamespace(
        action_id="NWAO-TEST",
        action_type="REVIEW_DRAFT",
        explanation="Review the prepared draft.",
        opportunity_id="NWO-TEST",
        application_id=None,
        engagement_id=None,
        ref_type="draft",
        ref_id="NWM-TEST",
    )
    owner_notifications.queue_owner_approval_notification(
        session,
        action,
        owner_email="owner@example.com",
    )
    assert sent == []
    session.commit()
    assert len(sent) == 1
    assert sent[0]["to"] == "owner@example.com"
    assert sent[0]["action_id"] == "NWAO-TEST"


def test_owner_approval_notification_discarded_on_rollback(monkeypatch):
    sent = []
    monkeypatch.setattr(owner_notifications, "_send", lambda payload: sent.append(payload))
    session = Session()
    action = SimpleNamespace(
        action_id="NWAO-ROLLBACK",
        action_type="PRICING_COMMITMENT",
        explanation="Owner must approve pricing.",
        opportunity_id="NWO-ROLLBACK",
        application_id=None,
        engagement_id=None,
        ref_type="opportunity",
        ref_id="NWO-ROLLBACK",
    )
    owner_notifications.queue_owner_approval_notification(
        session,
        action,
        owner_email="owner@example.com",
    )
    session.rollback()
    assert sent == []
