"""Read-only, fail-closed staging acceptance preflight for Nova bookkeeping.

This module does not deploy, migrate, activate any feature, provision consent,
read customer documents, or write private objects. Call only from an operator-
approved isolated staging environment. Diagnostics omit secrets and file data.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from . import operations_customer_csv_jobs as csv_jobs
from .bookkeeping_scope import consents

_STAGING = "staging"
_NEEDED_TABLES = frozenset({csv_jobs.jobs.name, consents.name})
_REQUIRED_COLUMNS = {
    csv_jobs.jobs.name: frozenset((
        "id", "organization_id", "owner_user_id", "engagement_id", "task_id",
        "request_key", "status", "input_sha256", "output_ref",
        "output_sha256", "created_at", "updated_at",
    )),
    consents.name: frozenset((
        "authorization_id", "organization_id", "owner_user_id",
        "engagement_id", "task_id", "work_type", "status",
        "contract_ref_sha256", "client_ai_consent_ref_sha256",
        "data_processing_ref_sha256", "verified_by_user_id",
        "verified_at", "valid_until", "revoked_at",
    )),
}
_NEEDED_ENVS = ("AMICOR_ENVIRONMENT", "APP_ENV", "ENVIRONMENT")
_TRUE = {"true", "1", "yes"}


def _env_of(config: Mapping[str, str], name: str) -> str:
    return str(config.get(name, "") or "").strip()


def _check(code: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": code, "passed": bool(passed), "detail": detail}


def inspect_staging_readiness(
    *, config: Mapping[str, str],
    engine: Engine | None = None,
    s3_client: Any | None = None,
    bucket: str | None = None,
    verified_staging_identity: bool = False,
    signed_consent_process_reviewed: bool = False,
    approved_database_name: str | None = None,
    approved_bucket_name: str | None = None,
) -> dict[str, Any]:
    """Report release blockers; never imply readiness from CI synthetic mocks.

    External database/S3 handles must be supplied by an approved staging
    operator and are inspected read-only. If handles are not supplied or
    readiness evidence is unknown, no pass is inferred.
    """
    environments = [
        _env_of(config, key).lower()
        for key in _NEEDED_ENVS if _env_of(config, key)
    ]
    isolated_staging = bool(environments) and all(v == _STAGING for v in environments)
    findings = [
        _check("environment_isolated_staging", isolated_staging,
               "Every configured environment label must be staging"),
        _check(
            "bookkeeping_disabled_until_release",
            _env_of(config, "NOVA_BOOKKEEPING_DURABLE_ENABLED").lower() not in _TRUE,
            "Bookkeeping must remain disabled during inspection",
        ),
        _check(
            "operations_csv_disabled_until_release",
            _env_of(config, "NOVA_OPERATIONS_DURABLE_CSV_ENABLED").lower() not in _TRUE,
            "Durable processing must remain disabled during inspection",
        ),
        _check(
            "private_storage_selected",
            _env_of(config, "PLATFORM_OPS_DOCUMENT_STORAGE").lower() == "s3_private",
            "Private object storage must be selected",
        ),
    ]

    # Independent approval of exact resource names is required.
    # Merely excluding two known production names is insufficient.
    forbidden = {"amicor-prod", "amicor-casting-staging-db"}
    def approved_name(value: str | None) -> bool:
        return (
            isinstance(value, str) and bool(value.strip())
            and value == value.strip() and len(value) <= 128
            and value.lower() not in forbidden
        )
    may_inspect = isolated_staging and verified_staging_identity
    db_identity_ok = may_inspect and approved_name(approved_database_name)
    bucket_name = bucket or _env_of(config, "AMICOR_DOCUMENT_S3_BUCKET")
    bucket_identity_ok = (
        may_inspect and approved_name(approved_bucket_name)
        and approved_bucket_name == bucket_name
    )
    findings.append(_check(
        "approved_accounting_database_identity", db_identity_ok,
        "Exact independently approved accounting staging database required",
    ))
    findings.append(_check(
        "approved_private_bucket_identity", bucket_identity_ok,
        "Exact independently approved private accounting bucket required",
    ))
    findings.append(_check(
        "operator_verified_staging_identity", verified_staging_identity and isolated_staging,
        "Independent operator confirmation of isolated staging required",
    ))

    if engine is None or not db_identity_ok:
        findings.append(_check("postgres_tables_verified", False,
                               "No approved isolated staging DB inspection"))
    else:
        try:
            with engine.connect() as connection:
                db_name = connection.execute(sa.text("select current_database()")).scalar_one()
                dialect_ok = engine.dialect.name == "postgresql"
                inspector = sa.inspect(connection)
                names = set(inspector.get_table_names()) if dialect_ok else set()
                schema_ok = dialect_ok and _NEEDED_TABLES.issubset(names)
                if schema_ok:
                    for table_name, columns in _REQUIRED_COLUMNS.items():
                        seen = {col["name"] for col in inspector.get_columns(table_name)}
                        if not columns.issubset(seen):
                            schema_ok = False
                            break
                if schema_ok:
                    consent_uniques = {
                        item.get("name") for item in
                        inspector.get_unique_constraints(consents.name)
                    }
                    job_uniques = {
                        item.get("name") for item in
                        inspector.get_unique_constraints(csv_jobs.jobs.name)
                    }
                    schema_ok = (
                        "uq_nova_bookkeeping_consent_scope" in consent_uniques
                        and "uq_nova_customer_csv_request" in job_uniques
                    )
            valid_db_name = db_name == approved_database_name
            findings.append(_check(
                "postgres_tables_verified",
                dialect_ok and valid_db_name and schema_ok,
                "Approved PostgreSQL database with required columns and consent uniqueness",
            ))
        except Exception:
            findings.append(_check("postgres_tables_verified", False,
                                   "Unable to verify isolated staging PostgreSQL schema"))

    if not bucket_identity_ok or s3_client is None:
        findings.extend([
            _check("s3_public_access_block", False, "Approved staging bucket inspection missing"),
            _check("s3_default_encryption", False, "Approved staging bucket encryption inspection missing"),
        ])
    else:
        try:
            controls = s3_client.get_public_access_block(Bucket=bucket_name)[
                "PublicAccessBlockConfiguration"
            ]
            public_blocked = all(
                controls.get(name) is True for name in (
                    "BlockPublicAcls", "IgnorePublicAcls",
                    "BlockPublicPolicy", "RestrictPublicBuckets",
                )
            )
        except Exception:
            public_blocked = False
        findings.append(_check(
            "s3_public_access_block", public_blocked,
            "All four S3 public-access protections required",
        ))
        try:
            config_response = s3_client.get_bucket_encryption(Bucket=bucket_name)[
                "ServerSideEncryptionConfiguration"]["Rules"]
            encryption_ok = bool(config_response) and all(
                rule.get("ApplyServerSideEncryptionByDefault", {}).get(
                    "SSEAlgorithm"
                ) in {"AES256", "aws:kms"} for rule in config_response
            )
        except Exception:
            encryption_ok = False
        findings.append(_check(
            "s3_default_encryption", encryption_ok,
            "Bucket default SSE-S3 or SSE-KMS encryption must be configured",
        ))

    findings.append(_check(
        "signed_client_ai_consent_workflow_reviewed",
        signed_consent_process_reviewed and may_inspect,
        "Independent contract verification and revocation workflow required",
    ))
    failures = [entry["check"] for entry in findings if not entry["passed"]]
    return {
        "status": "INSPECTION_ONLY" if not failures else "BLOCKED",
        "production_release_authorized": False,
        "customer_data_allowed": False,
        "deployment_performed": False,
        "checks": findings,
        "blockers": failures,
    }
