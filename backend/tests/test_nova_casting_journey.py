"""Invitations, mock transport, disposable uploads, and migration reversibility."""
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "app/core/nova/creative_studio/casting_pilot.py"
MIGRATION = ROOT / "migrations/versions/20261015_casting_journey.py"
TRANSPORT = ROOT / "app/core/nova/creative_studio/casting_mock_transport.py"
UPLOADS = ROOT / "app/core/nova/creative_studio/casting_mock_uploads.py"
POSTGRES = os.getenv("CASTING_TEST_POSTGRES_URL", "")


def load_pilot():
    spec = importlib.util.spec_from_file_location("casting_pilot_journey_under_test", PILOT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _organizer(tenant="tenant-a"):
    return {"user_id": "organizer", "organization_id": "org-a", "tenant_id": tenant, "role": "organizer", "verified": True}


def _applicant(user_id="applicant", tenant="tenant-a"):
    return {"user_id": user_id, "organization_id": "org-a", "tenant_id": tenant, "role": "applicant", "verified": True}


def _role(pilot):
    return {
        "title": "Harbor lead",
        "requirements": "Adults only",
        "deadline": "2027-12-01T18:00:00+00:00",
        "minimum_age": 18,
        "questions": [{"id": "union", "prompt": "Can you attend?"}],
    }


def _book(pilot, when="2026-11-02T15:00:00+00:00"):
    book = pilot.PilotDirectory(datetime.fromisoformat(when))
    book.note_campaign(organization_id="org-a", tenant_id="tenant-a", campaign_id="campaign-1", status="DRAFT")
    return book


def test_transport_and_upload_modules_do_not_open_a_network_client():
    transport = TRANSPORT.read_text(encoding="utf-8")
    uploads = UPLOADS.read_text(encoding="utf-8")
    for source in (transport, uploads):
        assert "smtplib" not in source
        assert "http.client" not in source
        assert "urllib" not in source
        assert "socket" not in source
    assert "disposable-mock" in transport
    assert "public static" in uploads or "public" in uploads


def test_invite_is_tenant_bound_and_a_closed_campaign_cannot_mint_another():
    pilot = load_pilot()
    book = _book(pilot)
    role = book.create_role(_organizer(), "campaign-1", _role(pilot))
    issued = book.issue_invite(_organizer(), "campaign-1", {
        "role_id": role["id"], "expires_at": "2026-11-20T18:00:00+00:00",
    })
    assert issued["published"] is False
    assert issued["external_delivery"] is False
    try:
        book.redeem_invite(_applicant(tenant="tenant-b"), issued["token"])
    except pilot.PilotDenied:
        pass
    else:
        raise AssertionError("other tenant redeemed the invite")
    book.note_campaign(organization_id="org-a", tenant_id="tenant-a", campaign_id="campaign-1", status="CLOSED")
    try:
        book.issue_invite(_organizer(), "campaign-1", {
            "role_id": role["id"], "expires_at": "2026-11-21T18:00:00+00:00",
        })
    except pilot.PilotRejected as exc:
        assert str(exc) == "Campaign cannot be published"
    else:
        raise AssertionError("closed campaign minted an invite")
    try:
        book.redeem_invite(_applicant(), issued["token"])
    except pilot.PilotRejected as exc:
        assert str(exc) == "Campaign cannot be published"
    else:
        raise AssertionError("closed campaign redeemed an invite")


def test_expired_invite_does_not_open_an_application():
    pilot = load_pilot()
    book = _book(pilot)
    role = book.create_role(_organizer(), "campaign-1", _role(pilot))
    issued = book.issue_invite(_organizer(), "campaign-1", {
        "role_id": role["id"], "expires_at": "2026-11-01T00:00:00+00:00",
    })
    assert issued["status"] == "expired"
    try:
        book.redeem_invite(_applicant(), issued["token"])
    except pilot.PilotRejected as exc:
        assert str(exc) == "Expired invite"
    else:
        raise AssertionError("expired invite opened")
    assert book.intakes == {}


def test_mock_transport_fail_retry_and_opt_out_never_deliver():
    pilot = load_pilot()
    book = _book(pilot)
    role = book.create_role(_organizer(), "campaign-1", _role(pilot))
    book.note_campaign(organization_id="org-a", tenant_id="tenant-a", campaign_id="campaign-1", status="DRAFT")
    issued = book.issue_invite(_organizer(), "campaign-1", {
        "role_id": role["id"], "expires_at": "2026-12-01T00:00:00+00:00",
    })
    redeemed = book.redeem_invite(_applicant(), issued["token"])
    saved = book.save_intake(_applicant(), application_id=redeemed["application_id"], campaign_id="campaign-1", payload={
        "role_id": role["id"],
        "display_name": "Jordan Hale",
        "contact_email": "jordan.hale@example.invalid",
        "video_url": "https://example.invalid/tape",
        "age_years": 28,
        "consent_accepted": True,
        "consent_version": "sandbox-v1",
        "retention_days": 30,
        "answers": {"union": "Yes"},
    })
    book.submit_intake(_applicant(), saved["id"])
    drafted = book.draft_message(_organizer(), {
        "kind": "confirmation", "idempotency_key": "journey-unit-1", "channel": "email",
        "application_id": saved["id"],
    })
    try:
        book.dispatch_mock(_organizer(), drafted["id"])
    except pilot.PilotRejected:
        pass
    else:
        raise AssertionError("unapproved draft was handed to the mock")
    book.approve_message(_organizer(), drafted["id"])
    failed = book.dispatch_mock(_organizer(), drafted["id"], fail=True)
    assert failed["mock_outcome"] == "mock_failed"
    assert failed["delivery_state"] == "not_sent"
    assert failed["real_delivery"] is False
    accepted = book.dispatch_mock(_organizer(), drafted["id"], fail=False)
    assert accepted["mock_outcome"] == "mock_accepted"
    assert accepted["mock_receipt"].startswith("MOCK-")
    assert accepted["external_delivery"] is False
    replay = book.dispatch_mock(_organizer(), drafted["id"], fail=True)
    assert replay["mock_receipt"] == accepted["mock_receipt"]
    book.suppress(_applicant(), {"contact_email": "jordan.hale@example.invalid", "reason": "stop"})
    stopped = book.draft_message(_organizer(), {
        "kind": "update", "idempotency_key": "journey-stop-1", "channel": "email",
        "application_id": saved["id"],
    })
    sent = book.dispatch_mock(_organizer(), stopped["id"])
    assert sent["mock_outcome"] == "suppressed"
    assert sent["mock_receipt"] == ""
    assert all(row["delivery_state"] == "not_sent" and row["delivered"] is False for row in book.messages.values())


def _uploads():
    import sys
    import types

    studio = ROOT / "app/core/nova/creative_studio"
    packages = {
        "app": ROOT / "app",
        "app.core": ROOT / "app/core",
        "app.core.nova": ROOT / "app/core/nova",
        "app.core.nova.creative_studio": studio,
    }
    for name, path in packages.items():
        module = sys.modules.get(name)
        if module is None or not hasattr(module, "__path__"):
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            module.__package__ = name
            sys.modules[name] = module
    from app.core.nova.creative_studio import casting_mock_uploads
    return casting_mock_uploads


def test_mock_upload_rejects_hostile_bytes_and_releases_nothing():
    uploads = _uploads()
    evaluate_mock_upload = uploads.evaluate_mock_upload
    hold = uploads.hold
    holds = uploads.holds
    wipe = uploads.wipe

    body = b"ftyp" + b"isom" + b"\x00\x00\x00\x00"
    clean = (len(body) + 4).to_bytes(4, "big") + body
    accepted = evaluate_mock_upload(clean, "video/mp4")
    assert accepted["scan_status"] == "CLEAN"
    assert accepted["store_bytes"] is True
    rejected = evaluate_mock_upload(clean + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE", "video/mp4")
    assert rejected["scan_status"] == "REJECTED"
    assert rejected["store_bytes"] is False
    wrong = evaluate_mock_upload(clean, "text/html")
    assert wrong["scan_status"] == "REJECTED"
    hold("media-1", clean)
    assert holds("media-1") is True
    assert wipe() == 1
    assert holds("media-1") is False


def _run_migration(engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("casting_journey_migration_under_test", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def bind(connection):
        module.op = Operations(MigrationContext.configure(connection))

    return module, bind


def _parents(connection):
    connection.execute(sa.text("CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(sa.text("CREATE TABLE nova_casting_organizations (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(sa.text("CREATE TABLE nova_casting_campaigns (id VARCHAR(48) PRIMARY KEY)"))
    connection.execute(sa.text("CREATE TABLE nova_casting_roles (id VARCHAR(48) PRIMARY KEY)"))
    connection.execute(sa.text("CREATE TABLE nova_casting_intakes (id VARCHAR(48) PRIMARY KEY)"))
    connection.execute(sa.text(
        "CREATE TABLE nova_casting_pilot_messages (id VARCHAR(48) PRIMARY KEY, delivery_state VARCHAR(16))"
    ))


def _assert_reversible(engine):
    module, bind = _run_migration(engine)
    with engine.begin() as connection:
        bind(connection)
        os.environ["AMICOR_ENVIRONMENT"] = "production"
        os.environ["ENVIRONMENT"] = "production"
        os.environ["APP_ENV"] = "production"
        module.upgrade()
        assert "nova_casting_invites" not in set(sa.inspect(connection).get_table_names())
        for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
            os.environ[name] = "disposable"
        module.upgrade()
        assert "nova_casting_invites" not in set(sa.inspect(connection).get_table_names())
        _parents(connection)
        connection.execute(sa.text("INSERT INTO platform_users (id) VALUES ('u')"))
        connection.execute(sa.text("INSERT INTO nova_casting_organizations (id) VALUES ('o')"))
        connection.execute(sa.text("INSERT INTO nova_casting_intakes (id) VALUES ('a')"))
        module.upgrade()
        names = set(sa.inspect(connection).get_table_names())
        assert "nova_casting_invites" in names
        assert "nova_casting_mock_attempts" in names
        assert "nova_casting_mock_media" in names
        failed = False
        try:
            with connection.begin_nested():
                connection.execute(sa.text(
                    "INSERT INTO nova_casting_mock_media "
                    "(id, organization_id, application_id, applicant_id, mime_type, byte_size, scan_status, "
                    "scan_reason, public_url, created_at) VALUES "
                    "('m1', 'o', 'a', 'u', 'video/mp4', 8, 'CLEAN', '', 'https://example.invalid/x', 't')"
                ))
        except Exception:
            failed = True
        assert failed is True
        module.downgrade()
        after = set(sa.inspect(connection).get_table_names())
        assert "nova_casting_invites" not in after
        assert "nova_casting_mock_attempts" not in after
        assert "nova_casting_mock_media" not in after
        assert "nova_casting_journey_audit" not in after
        assert "platform_users" in after
        assert "nova_casting_pilot_messages" in after


def test_journey_migration_reverses_on_sqlite(monkeypatch):
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(name, "disposable")
    engine = sa.create_engine("sqlite://")
    _assert_reversible(engine)


@pytest.mark.skipif(not POSTGRES, reason="Disposable PostgreSQL not configured")
def test_journey_migration_reverses_on_postgres(monkeypatch):
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(name, "disposable")
    admin = sa.create_engine(POSTGRES)
    with admin.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA IF EXISTS casting_journey CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA casting_journey"))
    engine = sa.create_engine(POSTGRES)

    @sa.event.listens_for(engine, "connect")
    def _schema(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET search_path TO casting_journey")
        cursor.close()

    try:
        _assert_reversible(engine)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.text("DROP SCHEMA IF EXISTS casting_journey CASCADE"))
        admin.dispose()
