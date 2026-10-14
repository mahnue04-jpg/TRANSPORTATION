"""Casting pilot rules stay inside the sandbox and never send a message."""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/casting_pilot.py"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/20261014_casting_pilot.py"
ROUTER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/casting_router_pilot.py"


def load():
    spec = importlib.util.spec_from_file_location("casting_pilot_under_test", PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def organizer():
    return {"user_id": "organizer", "organization_id": "org-a", "role": "organizer", "verified": True}


def applicant(user_id="applicant"):
    return {"user_id": user_id, "organization_id": "org-a", "role": "applicant", "verified": True}


def role_payload():
    return {
        "title": "Harbor lead",
        "requirements": "Two-minute self-tape.",
        "deadline": "2026-11-20T18:00:00+00:00",
        "minimum_age": 18,
        "questions": [{"id": "union", "prompt": "Can you attend a sandbox callback?"}],
    }


def intake_payload(role_id, **override):
    payload = {
        "role_id": role_id,
        "display_name": "Jordan Hale",
        "contact_email": "jordan.hale@example.invalid",
        "video_url": "https://example.invalid/tapes/jordan",
        "age_years": 28,
        "consent_accepted": True,
        "consent_version": "sandbox-v1",
        "retention_days": 30,
        "answers": {"union": "Yes"},
    }
    payload.update(override)
    return payload


def test_harborlight_month_never_sends_or_casts():
    pilot = load()
    result = pilot.run_harborlight_walkthrough()
    assert result["label"] == "Demo / Early Access"
    assert result["published"] is False
    assert result["submitted_status"] == "SUBMITTED"
    assert result["resumed_receipt"] == result["receipt"]
    assert result["rubric_decision"] == "human_required"
    assert result["automatic_cast"] is False
    assert result["reviewer_hides_contact"] is True
    assert result["reviewer_hides_link"] is True
    assert result["approved_status"] == "approved"
    assert result["delivered"] is False
    assert result["external_delivery"] is False
    assert result["retry_attempts"] == 1
    assert result["call_sheet_count"] == 1
    assert result["suppressed_status"] == "suppressed"
    assert result["export_has_link"] is False
    assert result["export_has_jordan"] is True
    assert "Applicant does not meet the minimum age" in result["outcomes"]
    assert "Duplicate application" in result["outcomes"]
    assert "cross-tenant-denied" in result["outcomes"]
    assert "SMS is not configured" in result["outcomes"]
    assert "consent.revoked" in result["audit_actions"]
    assert "export.requested" in result["audit_actions"]


def test_links_consent_and_protected_fields_fail_closed():
    pilot = load()
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    book = pilot.PilotDirectory(now)
    role = book.create_role(organizer(), "campaign-1", role_payload())
    for url in (
        "javascript:alert(1)",
        "http://example.invalid/tape",
        "https://user:pass@example.invalid/tape",
        "https://127.0.0.1/tape",
        "https://localhost/tape",
        "data:video/mp4;base64,AAAA",
    ):
        try:
            book.save_intake(applicant(), application_id="app-1", campaign_id="campaign-1", payload=intake_payload(role["id"], video_url=url))
        except pilot.PilotRejected as exc:
            assert str(exc) == "Invalid video link"
        else:
            raise AssertionError(url)
    for payload in (
        intake_payload(role["id"], age_years=17),
        intake_payload(role["id"], consent_accepted=False),
        intake_payload(role["id"], display_name="<script>"),
        intake_payload(role["id"], facial_score=0.2),
        intake_payload(role["id"], guardian_attestation=True),
    ):
        try:
            book.save_intake(applicant(), application_id="app-1", campaign_id="campaign-1", payload=payload)
        except pilot.PilotRejected as exc:
            assert str(exc) in {
                "Applicant does not meet the minimum age",
                "Consent required",
                "Invalid name",
                "Unsupported field",
            }
        else:
            raise AssertionError(payload)


def test_expired_consent_duplicate_pagination_and_unsent_retry():
    pilot = load()
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    book = pilot.PilotDirectory(now)
    role = book.create_role(organizer(), "campaign-1", role_payload())
    book.save_intake(applicant(), application_id="app-1", campaign_id="campaign-1", payload=intake_payload(role["id"], retention_days=1))
    book.now = now + timedelta(days=2)
    try:
        book.submit_intake(applicant(), "app-1")
    except pilot.PilotRejected as exc:
        assert str(exc) == "Consent expired"
    else:
        raise AssertionError("expired consent submitted")
    fresh = pilot.PilotDirectory(now)
    created = fresh.create_role(organizer(), "campaign-1", role_payload())
    fresh.save_intake(applicant(), application_id="app-1", campaign_id="campaign-1", payload=intake_payload(created["id"]))
    try:
        fresh.save_intake(applicant("other"), application_id="app-2", campaign_id="campaign-1", payload=intake_payload(created["id"], display_name="Other Person"))
    except pilot.PilotRejected as exc:
        assert str(exc) == "Duplicate application"
    else:
        raise AssertionError("duplicate accepted")
    page = fresh.list_roles(organizer(), "campaign-1", limit=1, offset=0)
    assert page["limit"] == 1
    assert len(page["items"]) == 1
    try:
        fresh.list_roles(organizer(), "campaign-1", limit=500, offset=0)
    except pilot.PilotRejected as exc:
        assert str(exc) == "Request rejected"
    else:
        raise AssertionError("page limit ignored")
    first = fresh.draft_message(organizer(), {"kind": "update", "idempotency_key": "same-key-01", "channel": "email"})
    second = fresh.draft_message(organizer(), {"kind": "invite", "idempotency_key": "same-key-01", "channel": "email"})
    assert first["id"] == second["id"]
    assert first["delivered"] is False
    approved = fresh.approve_message(organizer(), first["id"])
    retried = fresh.retry_message(organizer(), first["id"])
    assert approved["external_delivery"] is False
    assert retried["delivered"] is False
    assert retried["attempt_count"] == 1
    try:
        fresh.draft_message(organizer(), {"kind": "reminder", "idempotency_key": "whatsapp-key", "channel": "whatsapp"})
    except pilot.PilotRejected as exc:
        assert str(exc) == "WhatsApp is not configured"
    else:
        raise AssertionError("whatsapp drafted")


def test_stop_list_expired_invite_and_minimized_export():
    pilot = load()
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    book = pilot.PilotDirectory(now)
    role = book.create_role(organizer(), "campaign-1", role_payload())
    book.save_intake(applicant(), application_id="app-1", campaign_id="campaign-1", payload=intake_payload(role["id"]))
    book.submit_intake(applicant(), "app-1")
    book.save_schedule(organizer(), "campaign-1", {
        "role_id": role["id"],
        "timezone": "America/New_York",
        "starts_at": "2026-11-01T15:00:00+00:00",
        "ends_at": "2026-11-01T16:00:00+00:00",
        "location_label": "Fictional room",
        "document_url": "https://example.invalid/side.pdf",
    })
    invite = book.draft_message(organizer(), {
        "kind": "invite", "application_id": "app-1", "idempotency_key": "expired-invite", "channel": "email",
    })
    approved = book.approve_message(organizer(), invite["id"])
    assert approved["status"] == "failed_closed"
    assert "Expired invite" in approved["body"]
    assert approved["delivered"] is False
    book.suppress(applicant(), {"contact_email": "jordan.hale@example.invalid", "reason": "stop"})
    message = book.draft_message(organizer(), {
        "kind": "reminder", "application_id": "app-1", "idempotency_key": "stop-key-01", "channel": "email",
    })
    assert message["status"] == "suppressed"
    assert message["external_delivery"] is False
    sheet = book.call_sheet(organizer(), role["id"])
    assert sheet["invite_expired"] is True
    assert sheet["external_delivery"] is False
    try:
        book.call_sheet({"user_id": "stranger", "organization_id": "org-a", "role": "applicant", "verified": True}, role["id"])
    except pilot.PilotDenied:
        pass
    else:
        raise AssertionError("stranger saw the call sheet")
    reviewer = {"user_id": "reviewer", "organization_id": "org-a", "role": "reviewer", "verified": True}
    try:
        book.export_csv(reviewer, include_contact=True)
    except pilot.PilotDenied:
        pass
    else:
        raise AssertionError("reviewer exported contacts")
    book.set_review(reviewer, "app-1", stage="Callback", shortlisted=True)
    rubric = book.add_rubric(reviewer, "app-1", {"criterion": "preparation", "score": 5, "comment": "Prepared sample."})
    assert rubric["automatic_cast"] is False
    assert rubric["decision"] == "human_required"
    minimized = book.minimize_intake(organizer(), "app-1")
    assert minimized["contact_email"] == ""
    assert minimized["video_url"] == ""
    exported = book.export_csv(organizer(), include_contact=True)
    assert "https://" not in exported
    assert "jordan.hale@example.invalid" not in exported
    assert "CAST" not in exported


def test_sample_offer_is_not_a_contract_or_partnership():
    pilot = load()
    plan = pilot.sample_harborlight_plan()
    assert plan["label"] == "Demo / Early Access"
    assert plan["offer"]["amount_usd"] == 2400
    assert plan["offer"]["sample"] is True
    assert plan["offer"]["contract"] is False
    assert plan["partnerships"] == []
    assert "Netflix" not in plan["capability"]
    assert "Zeus" not in plan["summary"]
    assert len(plan["timeline"]) == 8
    assert len(plan["roles"]) == 3


def test_pilot_migration_is_production_locked_and_reversible(monkeypatch):
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("casting_pilot_migration_under_test", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")

    def bind(connection):
        module.op = Operations(MigrationContext.configure(connection))

    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    with engine.begin() as connection:
        bind(connection)
        module.upgrade()
        assert "nova_casting_roles" not in set(sa.inspect(connection).get_table_names())
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(name, "disposable")
    with engine.begin() as connection:
        bind(connection)
        module.upgrade()
        assert "nova_casting_roles" not in set(sa.inspect(connection).get_table_names())
        connection.execute(sa.text(
            "CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE nova_casting_organizations (id VARCHAR(36) PRIMARY KEY)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE nova_casting_campaigns (id VARCHAR(48) PRIMARY KEY)"
        ))
        module.upgrade()
        names = set(sa.inspect(connection).get_table_names())
        assert "nova_casting_roles" in names
        assert "nova_casting_pilot_messages" in names
        connection.execute(sa.text(
            "INSERT INTO nova_casting_pilot_messages "
            "(id, organization_id, application_id, kind, channel, body, status, idempotency_key, "
            "attempt_count, approved_by, delivery_state, created_at, updated_at) VALUES "
            "('m1', 'org', '', 'update', 'email', 'not sent', 'draft', 'idem-key-1', 0, '', "
            "'not_sent', 't', 't')"
        ))
        failed = False
        try:
            with connection.begin_nested():
                connection.execute(sa.text(
                    "INSERT INTO nova_casting_pilot_messages "
                    "(id, organization_id, application_id, kind, channel, body, status, idempotency_key, "
                    "attempt_count, approved_by, delivery_state, created_at, updated_at) VALUES "
                    "('m2', 'org', '', 'update', 'email', 'sent', 'approved', 'idem-key-2', 0, '', "
                    "'sent', 't', 't')"
                ))
        except sa.exc.IntegrityError:
            failed = True
        assert failed is True
        module.downgrade()
        names = set(sa.inspect(connection).get_table_names())
        assert "nova_casting_roles" not in names
        assert "platform_users" in names
    engine.dispose()


def test_migration_and_router_stay_closed():
    migration = MIGRATION.read_text(encoding="utf-8")
    router = ROUTER.read_text(encoding="utf-8")
    assert 'revision = "20261014_casting_pilot"' in migration
    assert 'down_revision = "20261012_casting_org_name"' in migration
    assert "production" in migration
    assert "delivery_state = 'not_sent'" in migration
    assert "UploadFile" not in router
    assert "boto3" not in router
    assert "casting_sandbox_writes_enabled" in router
    assert "NOVA_CASTING_SMS_PROVIDER" in router
    assert "private, no-store" in router
