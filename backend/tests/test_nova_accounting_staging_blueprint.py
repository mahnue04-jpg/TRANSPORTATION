"""Non-deploying safety checks for proposed isolated accounting staging Blueprint.

This only parses YAML. Never calls Render, creates resources, or reads secrets.
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = ROOT / "render.nova-accounting-staging.proposed.yaml"
PRODUCTION = ROOT / "render.yaml"


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_staging_proposal_is_separate_and_scoped_to_new_resources():
    assert PROPOSAL != PRODUCTION
    plan = read_yaml(PROPOSAL)
    assert len(plan["databases"]) == 1
    assert len(plan["services"]) == 1
    database = plan["databases"][0]
    service = plan["services"][0]
    assert database["name"] == "amicor-nova-accounting-staging-db"
    assert database["databaseName"] == "nova_accounting_staging"
    assert database["name"] not in {"amicor-prod", "amicor-casting-staging-db"}
    assert service["name"] == "amicor-nova-accounting-staging"
    assert service["branch"] == "nova/bookkeeping-durable-csv-integration-20261111"
    assert service["rootDir"] == "backend"
    assert service["autoDeployTrigger"] == "off"
    assert service["region"] == database["region"] == "virginia"
    assert "releaseCommand" not in service
    assert "preDeployCommand" not in service
    assert "disk" not in service


def test_processing_paid_services_and_schema_migrations_remain_disabled():
    service = read_yaml(PROPOSAL)["services"][0]
    env = {entry["key"]: entry for entry in service["envVars"]}
    for flag in (
        "NOVA_BOOKKEEPING_DURABLE_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "HEALTH_ISF_STRIPE_ENABLED",
        "NOVA_STRIPE_LIVE_ENABLED",
    ):
        assert env[flag]["value"] == "false", flag
    assert env["APP_ENV"]["value"] == "staging"
    assert env["AMICOR_ENVIRONMENT"]["value"] == "staging"
    assert env["PLATFORM_OPS_DOCUMENT_STORAGE"]["value"] == "s3_private"
    assert env["NOVA_OPERATIONS_CSV_SCHEMA_APPROVED"]["value"] != "staging-only"
    assert env["NOVA_BOOKKEEPING_CONSENT_SCHEMA_APPROVED"]["value"] != "staging-only"
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == (
        "amicor-nova-accounting-staging-db"
    )


def test_no_credentials_or_unapproved_external_customer_data_in_blueprint():
    service = read_yaml(PROPOSAL)["services"][0]
    env = {entry["key"]: entry for entry in service["envVars"]}
    for secret in (
        "SECRET_KEY", "JWT_SECRET",
    ):
        assert env[secret].get("generateValue") is True
        assert "value" not in env[secret]
    for key in (
        "AMICOR_DOCUMENT_S3_BUCKET", "AMICOR_DOCUMENT_S3_REGION",
        "AMICOR_DOCUMENT_S3_ACCESS_KEY", "AMICOR_DOCUMENT_S3_SECRET_KEY",
        "AMICOR_DOCUMENT_S3_ENDPOINT",
    ):
        assert env[key].get("sync") is False
        assert "value" not in env[key]
    assert all("Amicor123!" not in str(value) for value in env.values())


def test_root_production_blueprint_is_not_mistaken_for_staging():
    existing = read_yaml(PRODUCTION)
    assert any(s.get("name") == "amicor-health-isf" for s in existing["services"])
    proposed = read_yaml(PROPOSAL)
    assert all(
        s.get("name") != "amicor-health-isf" for s in proposed["services"]
    )
    assert all(
        d.get("name") != "amicor-health-isf-db" for d in proposed["databases"]
    )
