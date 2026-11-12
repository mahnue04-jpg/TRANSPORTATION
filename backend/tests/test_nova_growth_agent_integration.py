"""Integration: CRM lifecycle, widget→conversation, workflow dry-run, booking concurrency."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ["NOVA_GROWTH_AGENT_DEMO_MODE"] = "true"

from app.core.nova.growth_agent.demo import run_synthetic_demo
from app.core.nova.growth_agent.errors import ConsentRequiredError, DoubleBookError
from app.core.nova.growth_agent.models import GaContact, GaDeliveryAttempt
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.core.nova.growth_agent.service import GrowthAgentService
from app.db.session import Base


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ensure_growth_agent_schema(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _activate(svc: GrowthAgentService, org: str, owner: str = "owner-1"):
    return svc.upsert_profile(
        org,
        owner,
        {
            "business_name": "Test Biz",
            "website": "https://test.example",
            "timezone": "America/Chicago",
            "operating_hours": {"mon_fri": "09:00-17:00"},
            "services": [{"code": "consult", "name": "Consult", "duration_minutes": 30}],
            "faqs": [
                {
                    "id": "faq_hours",
                    "question": "What are your hours?",
                    "keywords": ["hours"],
                    "answer": "Mon–Fri 9–5.",
                }
            ],
            "contact_email": "owner@test.example",
            "handoff_phone": "+15555550123",
            "escalation_settings": {"handoff_on_unknown": True},
        },
        activate=True,
    )


def test_crm_lifecycle_and_widget_flow(db):
    svc = GrowthAgentService(db)
    org = "org-int-1"
    _activate(svc, org)
    widget = svc.create_widget_installation(org, domain="test.example")
    with pytest.raises(ConsentRequiredError):
        svc.widget_chat(
            token=widget["token"],
            origin="https://test.example",
            message="Hello",
            visitor_email="lead@example.com",
            visitor_name="Lead",
            consent_transactional=False,
            consent_marketing=False,
        )
    chat = svc.widget_chat(
        token=widget["token"],
        origin="https://test.example",
        message="What are your hours?",
        visitor_email="lead@example.com",
        visitor_name="Lead",
        consent_transactional=True,
        consent_marketing=False,
    )
    assert chat["grounded"] is True
    assert chat["ai_disclosed"] is True
    leads = svc.list_leads(org)
    assert len(leads) == 1
    updated = svc.update_lead(org, chat["contact_id"], lead_state="contacted", notes="Called")
    assert updated["lead_state"] == "contacted"
    conv = svc.get_conversation(org, chat["conversation_id"])
    assert any(m["role"] == "assistant" for m in conv["messages"])


def test_workflow_dry_run_mock_delivery_and_opt_out(db):
    svc = GrowthAgentService(db)
    org = "org-int-2"
    _activate(svc, org)
    contact = svc._upsert_contact(
        org,
        name="Pat",
        email="pat@example.com",
        consent_transactional=True,
        consent_marketing=True,
        channel="email",
        source="test",
    )
    db.commit()
    preview = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
    result = svc.approve_and_execute_workflow(
        org,
        run_id=preview["run_id"],
        dry_run=True,
        idempotency_key="wf-1",
    )
    assert result["live_send"] is False
    assert any(a["status"] == "sent_mock" for a in result["attempts"])

    # replay idempotent
    result2 = svc.approve_and_execute_workflow(
        org,
        run_id=preview["run_id"],
        dry_run=True,
        idempotency_key="wf-1",
    )
    assert result2["run_id"] == result["run_id"]

    svc.record_consent(
        org,
        contact_id=contact.id,
        channel="email",
        purpose="marketing",
        status="opted_out",
        collection_source="test_stop",
        actor_user_id="owner-1",
    )
    mkt = svc.preview_workflow(org, workflow_code="post_service_followup", contact_id=contact.id)
    suppressed = svc.approve_and_execute_workflow(
        org,
        run_id=mkt["run_id"],
        dry_run=True,
        idempotency_key="wf-mkt",
    )
    assert suppressed["status"] == "suppressed" or any(
        a.get("status") == "suppressed" for a in suppressed["attempts"]
    )


def test_booking_concurrency_no_double_book(tmp_path):
    # File-backed SQLite so concurrent sessions are serialized safely (StaticPool is not).
    db_path = tmp_path / "booking_concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    ensure_growth_agent_schema(bind=engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionFactory()
    try:
        svc = GrowthAgentService(db)
        org = "org-int-3"
        _activate(svc, org)
        contact = svc._upsert_contact(
            org,
            name="Sam",
            email="sam@example.com",
            consent_transactional=True,
            channel="email",
            source="test",
        )
        db.commit()
        day = None
        for offset in range(1, 10):
            candidate = datetime.now(timezone.utc) + timedelta(days=offset)
            if candidate.weekday() < 5:
                day = candidate.strftime("%Y-%m-%d")
                break
        availability = svc.list_availability(org, service_code="consult", day=day)
        assert availability["slots"]
        slot = availability["slots"][0]["starts_at_utc"]
        contact_id = contact.id
    finally:
        db.close()

    def attempt(i: int):
        local_db = SessionFactory()
        try:
            local = GrowthAgentService(local_db)
            out = local.book_appointment(
                org,
                contact_id=contact_id,
                service_code="consult",
                starts_at_utc=slot,
                idempotency_key=f"concurrent-{i}",
            )
            return ("ok", out["id"], f"concurrent-{i}")
        except DoubleBookError:
            return ("double", None, f"concurrent-{i}")
        except Exception as exc:  # noqa: BLE001
            return ("err", str(exc), f"concurrent-{i}")
        finally:
            local_db.close()

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, i) for i in range(2)]
        for fut in as_completed(futures):
            results.append(fut.result())

    oks = [r for r in results if r[0] == "ok"]
    doubles = [r for r in results if r[0] == "double"]
    errs = [r for r in results if r[0] == "err"]
    assert not errs, errs
    assert len(oks) == 1, results
    assert len(doubles) == 1, results

    winner_id, winner_key = oks[0][1], oks[0][2]
    verify = SessionFactory()
    try:
        svc = GrowthAgentService(verify)
        again = svc.book_appointment(
            org,
            contact_id=contact_id,
            service_code="consult",
            starts_at_utc=slot,
            idempotency_key=winner_key,
        )
        assert again["id"] == winner_id
        with pytest.raises(DoubleBookError):
            svc.book_appointment(
                org,
                contact_id=contact_id,
                service_code="consult",
                starts_at_utc=slot,
                idempotency_key="concurrent-fresh-key",
            )
    finally:
        verify.close()


def test_cancel_rebook_and_reschedule(db):
    svc = GrowthAgentService(db)
    org = "org-int-4"
    _activate(svc, org)
    contact = svc._upsert_contact(
        org,
        name="Jamie",
        email="jamie@example.com",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()
    day = None
    for offset in range(1, 10):
        candidate = datetime.now(timezone.utc) + timedelta(days=offset)
        if candidate.weekday() < 5:
            day = candidate.strftime("%Y-%m-%d")
            break
    availability = svc.list_availability(org, service_code="consult", day=day)
    assert len(availability["slots"]) >= 2
    slot_a = availability["slots"][0]["starts_at_utc"]
    slot_b = availability["slots"][1]["starts_at_utc"]

    booked = svc.book_appointment(
        org,
        contact_id=contact.id,
        service_code="consult",
        starts_at_utc=slot_a,
        idempotency_key="book-a",
    )
    cancelled = svc.cancel_appointment(org, booked["id"], actor_user_id="owner-1")
    assert cancelled["status"] == "cancelled"

    rebooked = svc.book_appointment(
        org,
        contact_id=contact.id,
        service_code="consult",
        starts_at_utc=slot_a,
        idempotency_key="book-a-again",
    )
    assert rebooked["status"] == "confirmed"
    assert rebooked["id"] == booked["id"]

    moved = svc.reschedule_appointment(
        org,
        rebooked["id"],
        starts_at_utc=slot_b,
        idempotency_key="resched-1",
        actor_user_id="owner-1",
    )
    assert moved["status"] == "rescheduled"
    assert moved["starts_at_utc"] == slot_b
    replay = svc.reschedule_appointment(
        org,
        rebooked["id"],
        starts_at_utc=slot_b,
        idempotency_key="resched-1",
        actor_user_id="owner-1",
    )
    assert replay["id"] == moved["id"]


def test_synthetic_demo_end_to_end(db):
    report = run_synthetic_demo(db, organization_id="org-demo", owner_user_id="owner-demo")
    assert report["label"].startswith("SYNTHETIC")
    assert report["booking_idempotent_replay"] is True
    assert report["chat"]["duplicate_contact_reused"] is True
    assert report["crm_edit"]["lead_state"] == "qualified"
    assert report["cancel_rebook"]["cancelled_status"] == "cancelled"
    assert report["cancel_rebook"]["reused_same_row"] is True
    assert report["reschedule"]["status"] == "rescheduled"
    assert report["restart_recovery"]["recovered_count"] >= 1
    assert report["marketing_suppressed"]["status"] == "suppressed" or any(
        a.get("status") == "suppressed" for a in report["marketing_suppressed"]["attempts"]
    )
    assert report["export_includes"]["appointments"] >= 1
    assert report["export_includes"]["consent_records"] >= 1
    assert report["double_book_blocked"] in {"DOUBLE_BOOK", "IntegrityError"} or report["double_book_blocked"]
    assert report["handoff"]["handler"] == "human"
    assert report["analytics"]["is_attribution"] is False
    assert report["analytics"]["booked_appointments"] >= 1
    assert report["health"]["live_flags"]["sms"] is False


def test_restart_recovery_reclaims_queued_delivery(db):
    svc = GrowthAgentService(db)
    org = "org-recover"
    _activate(svc, org)
    contact = svc._upsert_contact(
        org,
        name="Riley",
        email="riley@example.com",
        consent_transactional=True,
        consent_marketing=True,
        channel="email",
        source="test",
    )
    db.commit()
    preview = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
    queued = GaDeliveryAttempt(
        id="queued-attempt-1",
        organization_id=org,
        workflow_run_id=preview["run_id"],
        channel="email",
        provider="mock",
        status="queued",
        idempotency_key=f"{preview['run_id']}:ack:email",
        cost_estimate_usd=0.0,
        attempt_number=1,
        payload_redacted_json={},
    )
    db.add(queued)
    db.commit()
    recovered = svc.recover_pending_deliveries(org, actor_user_id="owner-1")
    assert recovered["recovered_count"] == 1
    assert recovered["attempts"][0]["status"] == "sent_mock"
    assert recovered["live_send"] is False


def test_channel_opt_out_without_blanket_dnc(db):
    svc = GrowthAgentService(db)
    org = "org-optout"
    _activate(svc, org)
    contact = svc._upsert_contact(
        org,
        name="Casey",
        email="casey@example.com",
        consent_transactional=True,
        consent_marketing=True,
        channel="email",
        source="test",
    )
    db.commit()
    svc.record_consent(
        org,
        contact_id=contact.id,
        channel="email",
        purpose="marketing",
        status="opted_out",
        collection_source="owner_opt_out",
        actor_user_id="owner-1",
    )
    refreshed = svc._org_query(GaContact, org).filter_by(id=contact.id).one()
    assert refreshed.do_not_contact is False
    mkt = svc.preview_workflow(org, workflow_code="post_service_followup", contact_id=contact.id)
    suppressed = svc.approve_and_execute_workflow(
        org,
        run_id=mkt["run_id"],
        dry_run=True,
        idempotency_key="optout-mkt",
    )
    assert suppressed["status"] == "suppressed" or any(
        a.get("status") == "suppressed" for a in suppressed["attempts"]
    )
    # Transactional ack still allowed after channel marketing opt-out
    ack = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
    executed = svc.approve_and_execute_workflow(
        org,
        run_id=ack["run_id"],
        dry_run=True,
        idempotency_key="optout-ack",
    )
    assert executed["status"] == "completed"
    assert any(a.get("status") == "sent_mock" for a in executed["attempts"])


def test_cross_tenant_query_isolation(db):
    svc = GrowthAgentService(db)
    _activate(svc, "org-a")
    _activate(svc, "org-b")
    contact = svc._upsert_contact(
        "org-a",
        name="Only A",
        email="a@example.com",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()
    assert svc.list_leads("org-b") == []
    with pytest.raises(Exception):
        svc.get_conversation("org-b", "missing")
    # Contact from A must not appear when listing B
    assert all(l["id"] != contact.id for l in svc.list_leads("org-b"))


def test_synthetic_profile_flag_persists_across_save_and_reload(db):
    """Owner-selected synthetic profiles must not be silently relabeled as real."""
    svc = GrowthAgentService(db)
    org = "org-synthetic-label"
    payload = {
        "business_name": "Cedar Ridge Home Services",
        "website": "https://demo.cedar-ridge.example",
        "timezone": "America/Chicago",
        "operating_hours": {"mon_fri": "09:00-17:00"},
        "services": [{"code": "consult", "name": "Consultation", "duration_minutes": 30}],
        "faqs": [{
            "id": "faq_hours",
            "question": "What are your hours?",
            "keywords": ["hours"],
            "answer": "Mon-Fri 9-5 local time.",
        }],
        "contact_email": "owner@cedar-ridge.example",
        "handoff_phone": "+15555550100",
        "escalation_settings": {"handoff_on_unknown": True},
        "is_synthetic_demo": True,
    }
    saved = svc.upsert_profile(org, "owner-synthetic", payload, activate=True)
    assert saved["activated"] is True
    assert saved["is_synthetic_demo"] is True
    db.commit()
    assert GrowthAgentService(db).get_profile(org)["is_synthetic_demo"] is True

    # Later UI saves must explicitly retain the selection.
    saved_again = svc.upsert_profile(org, "owner-synthetic", payload, activate=False)
    assert saved_again["is_synthetic_demo"] is True
    db.commit()
    assert GrowthAgentService(db).get_profile(org)["is_synthetic_demo"] is True


def test_growth_setup_page_discloses_explicit_synthetic_control():
    """Prevent UI regression where the API defaults the demo flag to false."""
    from pathlib import Path
    ui = Path(__file__).resolve().parents[1] / "static" / "nova-growth"
    markup = (ui / "index.html").read_text(encoding="utf-8")
    script = (ui / "growth.js").read_text(encoding="utf-8")
    assert 'id="biz-synthetic"' in markup
    assert 'is_synthetic_demo: $("biz-synthetic").checked' in script
    assert '$("biz-synthetic").checked = p.is_synthetic_demo === true' in script


def test_widget_contact_and_conversation_inherit_synthetic_profile(db):
    """Synthetic demo chat records must not be displayed as genuine leads."""
    svc = GrowthAgentService(db)
    org = "org-synthetic-widget"
    payload = {
        "business_name": "Cedar Ridge Synthetic",
        "website": "https://synthetic.example",
        "timezone": "America/Chicago",
        "operating_hours": {"mon_fri": "09:00-17:00"},
        "services": [{"code": "consult", "name": "Consult", "duration_minutes": 30}],
        "faqs": [{"id": "hours", "question": "Hours?", "keywords": ["hours"], "answer": "9 to 5"}],
        "contact_email": "owner@synthetic.example",
        "escalation_settings": {"handoff_on_unknown": True},
        "is_synthetic_demo": True,
    }
    svc.upsert_profile(org, "synthetic-owner", payload, activate=True)
    install = svc.create_widget_installation(org, domain="synthetic.example")
    chat = svc.widget_chat(
        token=install["token"],
        origin="https://synthetic.example",
        message="What are your hours?",
        visitor_name="Demo Visitor",
        visitor_email="visitor@synthetic.example",
        consent_transactional=True,
    )
    leads = svc.list_leads(org)
    conv = svc.get_conversation(org, chat["conversation_id"])
    assert len(leads) == 1
    assert leads[0]["is_synthetic_demo"] is True
    assert conv["is_synthetic_demo"] is True


def test_booking_inherits_synthetic_label_from_contact_even_if_caller_omits_flag(db):
    """Prevent default-false booking requests from mislabeling demo appointments."""
    from datetime import datetime, timedelta, timezone

    svc = GrowthAgentService(db)
    org = "org-synthetic-booking"
    svc.upsert_profile(
        org, "owner-synthetic",
        {
            "business_name": "Cedar Ridge Synthetic",
            "website": "https://synthetic.example",
            "timezone": "America/Chicago",
            "operating_hours": {"mon_fri": "09:00-17:00"},
            "services": [{"code": "consult", "name": "Consult", "duration_minutes": 30}],
            "faqs": [{"id": "hours", "question": "Hours?", "keywords": ["hours"], "answer": "9 to 5"}],
            "contact_email": "owner@synthetic.example",
            "escalation_settings": {"handoff_on_unknown": True},
            "is_synthetic_demo": True,
        },
        activate=True,
    )
    contact = svc._upsert_contact(
        org, name="Test Visitor", email="visitor@synthetic.example",
        consent_transactional=True, is_synthetic_demo=True,
    )
    db.commit()
    # Future weekday morning UTC avoids dependence on dates of existing rows.
    monday = datetime(2027, 1, 4, 15, 0, tzinfo=timezone.utc)
    booking = svc.book_appointment(
        org,
        contact_id=contact.id,
        service_code="consult",
        starts_at_utc=monday.isoformat().replace("+00:00", "Z"),
        idempotency_key="synthetic-booking-default-false",
    )
    assert booking["status"] == "confirmed"
    assert booking["is_synthetic_demo"] is True
    listed = svc.list_appointments(org)
    assert any(a["id"] == booking["id"] and a["is_synthetic_demo"] for a in listed)
