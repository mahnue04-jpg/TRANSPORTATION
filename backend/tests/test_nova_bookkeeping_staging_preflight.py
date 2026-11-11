"""Read-only staging gate: synthetic configuration tests, no Render changes."""
import pytest
from app.core.nova.work_revenue.bookkeeping_staging_preflight import inspect_staging_readiness


def by_name(report):
    return {item["check"]: item["passed"] for item in report["checks"]}


def test_default_configuration_is_blocked():
    result = inspect_staging_readiness(config={})
    assert result["status"] == "BLOCKED"
    assert result["production_release_authorized"] is False
    assert result["customer_data_allowed"] is False
    assert result["deployment_performed"] is False
    assert by_name(result)["bookkeeping_disabled_until_release"] is True
    assert by_name(result)["operations_csv_disabled_until_release"] is True
    assert by_name(result)["environment_isolated_staging"] is False
    assert by_name(result)["postgres_tables_verified"] is False


def test_production_label_prevents_all_resource_inspection():
    class Poison:
        def connect(self):
            raise AssertionError("Must never query production database")
        def get_public_access_block(self, **kwargs):
            raise AssertionError("Must never contact production bucket")
    for config in (
        {"AMICOR_ENVIRONMENT": "production"},
        {"APP_ENV": "staging", "AMICOR_ENVIRONMENT": "production"},
        {"APP_ENV": "development"},
    ):
        report = inspect_staging_readiness(
            config=config, engine=Poison(), s3_client=Poison(),
            bucket="synthetic", verified_staging_identity=True,
            signed_consent_process_reviewed=True,
        )
        assert report["status"] == "BLOCKED"
        assert "postgres_tables_verified" in report["blockers"]
        assert "s3_public_access_block" in report["blockers"]


def test_enabled_features_fail_inspection_safely():
    report = inspect_staging_readiness(config={
        "APP_ENV": "staging",
        "NOVA_BOOKKEEPING_DURABLE_ENABLED": "true",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED": "true",
        "PLATFORM_OPS_DOCUMENT_STORAGE": "s3_private",
    })
    assert not by_name(report)["bookkeeping_disabled_until_release"]
    assert not by_name(report)["operations_csv_disabled_until_release"]
    assert report["production_release_authorized"] is False


def test_staging_without_operator_confirmation_never_queries():
    class Poison:
        def connect(self):
            raise AssertionError("Unverified DB query")
        def get_public_access_block(self, **kwargs):
            raise AssertionError("Unverified bucket query")
    report = inspect_staging_readiness(
        config={"APP_ENV": "staging", "PLATFORM_OPS_DOCUMENT_STORAGE": "s3_private"},
        engine=Poison(), s3_client=Poison(), bucket="fake",
        verified_staging_identity=False,
        signed_consent_process_reviewed=True,
    )
    assert report["status"] == "BLOCKED"
    assert not by_name(report)["operator_verified_staging_identity"]
    assert not by_name(report)["signed_client_ai_consent_workflow_reviewed"]


def test_no_bucket_or_db_cannot_pass_even_with_operator_confirmation():
    report = inspect_staging_readiness(
        config={"APP_ENV": "staging", "PLATFORM_OPS_DOCUMENT_STORAGE": "s3_private"},
        verified_staging_identity=True, signed_consent_process_reviewed=True,
    )
    assert report["status"] == "BLOCKED"
    assert "postgres_tables_verified" in report["blockers"]
    assert "s3_default_encryption" in report["blockers"]
    assert by_name(report)["signed_client_ai_consent_workflow_reviewed"] is True
