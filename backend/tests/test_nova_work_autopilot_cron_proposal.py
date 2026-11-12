"""Checks only the proposed Render staging cron Blueprint; does not deploy."""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.core.nova.v3.autopilot_staging_guard import inspect_configuration

ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = ROOT / "render.nova-work-autopilot-cron.proposed.yaml"
LIVE = ROOT / "render.yaml"
CENTRAL = ZoneInfo("America/Chicago")

def cron_proposal():
    return yaml.safe_load(PROPOSAL.read_text(encoding="utf-8"))

def test_proposal_is_one_isolated_default_disabled_cron():
    assert PROPOSAL != LIVE
    proposal = cron_proposal()
    assert "databases" not in proposal
    assert len(proposal["services"]) == 1
    service = proposal["services"][0]
    assert service["type"] == "cron"
    assert service["name"] == "amicor-nova-work-revenue-discovery-staging"
    assert service["region"] == "virginia"
    assert service["plan"] == "0.5c-512mb"
    assert service["autoDeployTrigger"] == "off"
    assert service["rootDir"] == "backend"
    assert service["branch"] == "cursor/wr-first-client-pipeline-931c"
    assert "scripts/nova_work_autopilot_staging.py" in service["startCommand"]
    assert service["schedule"] == "0 10,11 * * *"
    assert "releaseCommand" not in service
    assert "preDeployCommand" not in service
    assert "disk" not in service
    production = yaml.safe_load(LIVE.read_text(encoding="utf-8"))
    assert all(row.get("name") != service["name"] for row in production["services"])

def test_cron_has_no_authorization_or_live_payment():
    service = cron_proposal()["services"][0]
    env = {item["key"]: item for item in service["envVars"]}
    assert env["APP_ENV"]["value"] == "staging"
    assert env["AMICOR_ENVIRONMENT"]["value"] == "staging"
    assert env["NOVA_WORK_AUTOPILOT_STAGING_ENABLED"]["value"] == "false"
    assert env["NOVA_BOOKKEEPING_DURABLE_ENABLED"]["value"] == "false"
    assert env["NOVA_OPERATIONS_DURABLE_CSV_ENABLED"]["value"] == "false"
    assert env["HEALTH_ISF_STRIPE_ENABLED"]["value"] == "false"
    assert env["NOVA_STRIPE_LIVE_ENABLED"]["value"] == "false"
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == "amicor-nova-accounting-staging-db"
    assert env["NOVA_WORK_AUTOPILOT_APPROVED_DATABASE"]["value"] == "nova_accounting_staging"
    for name in ("NOVA_WORK_AUTOPILOT_OWNER_ORG_ID", "NOVA_WORK_AUTOPILOT_OWNER_USER_ID",
                 "SAM_GOV_API_KEY"):
        assert env[name]["sync"] is False
        assert "value" not in env[name]
    for name in ("SECRET_KEY", "JWT_SECRET"):
        assert env[name]["generateValue"] is True
        assert "value" not in env[name]

def test_utc_schedule_matches_five_am_central_in_winter_and_summer():
    for utc_hour, utc_day in ((11, "2026-11-12"), (10, "2026-07-15")):
        now = datetime.fromisoformat(utc_day).replace(
            hour=utc_hour, tzinfo=timezone.utc
        )
        assert now.astimezone(CENTRAL).hour == 5
        other_hour = 10 if utc_hour == 11 else 11
        other = now.replace(hour=other_hour)
        assert other.astimezone(CENTRAL).hour != 5

def test_proposed_flags_never_activate_scheduled_search_without_owner_ids():
    env = {row["key"]: row for row in cron_proposal()["services"][0]["envVars"]}
    config = {key: row.get("value", "") for key, row in env.items()}
    planned = inspect_configuration(
        config,
        at=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
    )
    assert planned["status"] == "BLOCKED"
    assert planned["external_submission_allowed"] is False
    assert planned["production_release_authorized"] is False
    assert "staging_autopilot_not_enabled" in planned["blockers"]
    assert "owner_identity_not_approved" in planned["blockers"]
