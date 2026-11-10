"""Read-only preflight for the isolated Nova Operations recovery staging stack.

This command never creates databases, migrations, buckets or files, and never
starts jobs. It prints only nonsecret check names and verdicts.
"""
from __future__ import annotations

import json
import os
import sys

import sqlalchemy as sa

from app.modules.platform_ops import secure_storage as storage
from .operations_customer_csv_jobs import CustomerCSVBlocked
from .operations_recovery_worker import _stage_only_config

def _check_bucket():
    bucket = storage.s3_bucket()
    if os.getenv("PLATFORM_OPS_DOCUMENT_STORAGE", "").lower() != "s3_private":
        raise CustomerCSVBlocked("S3 private storage is not selected", 503)
    if not bucket or "staging" not in bucket.lower() or any(
        reserved in bucket.lower() for reserved in ("production", "casting", "prod")
    ):
        raise CustomerCSVBlocked("Dedicated Operations staging bucket required", 503)
    if not any(marker in bucket.lower() for marker in ("nova", "operations")):
        raise CustomerCSVBlocked("Operations staging bucket name required", 503)
    if storage.s3_configuration_status()["status"] != "READY":
        raise CustomerCSVBlocked("Private S3 credentials unavailable", 503)
    client = storage.S3PrivateDocumentStorage()._client
    try:
        access = client.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        if not all(access.get(name) is True for name in (
            "BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )):
            raise CustomerCSVBlocked("All four S3 public-access safeguards required", 503)
        encryption = client.get_bucket_encryption(Bucket=bucket)
        rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
        if not any(rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") in
                   {"AES256", "aws:kms"} for rule in rules):
            raise CustomerCSVBlocked("Default server-side bucket encryption required", 503)
    except CustomerCSVBlocked:
        raise
    except Exception as exc:
        raise CustomerCSVBlocked(
            "Could not verify staging bucket public access and encryption", 503
        ) from exc


def run_preflight() -> dict:
    """Read-only evidence. Reports no secret values or customer records."""
    checks = {}
    try:
        url, _ = _stage_only_config()
        checks["staging_worker_configuration"] = "PASS"
    except CustomerCSVBlocked:
        checks["staging_worker_configuration"] = "BLOCKED"
        return {"ready": False, "checks": checks}
    engine = None
    try:
        engine = sa.create_engine(url, pool_pre_ping=True)
        if engine.dialect.name != "postgresql":
            raise CustomerCSVBlocked("PostgreSQL required", 503)
        with engine.connect() as connection:
            # Read metadata only; never run Alembic, DDL, or job processing.
            connection.execute(sa.text("SELECT 1")).scalar_one()
            names = set(sa.inspect(connection).get_table_names())
        if "nova_operations_csv_recovery_jobs" not in names:
            raise CustomerCSVBlocked("Recovery migration not present", 503)
        if "platform_users" not in names or "nova_work_engagements" not in names:
            raise CustomerCSVBlocked("Staging application schema incomplete", 503)
        checks["isolated_database_schema"] = "PASS"
    except Exception:
        checks["isolated_database_schema"] = "BLOCKED"
    finally:
        if engine is not None:
            engine.dispose()
    try:
        _check_bucket()
        checks["private_storage_policy"] = "PASS"
    except Exception:
        checks["private_storage_policy"] = "BLOCKED"
    return {"ready": all(value == "PASS" for value in checks.values()), "checks": checks}


def main() -> int:
    result = run_preflight()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
