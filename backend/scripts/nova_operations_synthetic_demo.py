"""Generate a real, LOCAL synthetic Operations Agent acceptance deliverable.

Run from backend/: python -m scripts.nova_operations_synthetic_demo --output-dir /tmp/nova-demo

This is a deliberately offline demonstration, not authenticated customer
upload/release. The reviewer and tenant are synthetic fixture identities.
No live API, production database, provider, payment, or customer data is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from app.core.nova.work_revenue.operations_artifact_review import (
    complete_and_store_review_artifact,
    ensure_artifact_schema,
    read_review_artifact,
    review_artifact,
)
from app.core.nova.work_revenue.operations_assignment_handoff import (
    claim_approved_assignment,
    ensure_handoff_schema,
    handoff_approved_opportunity,
    record_verified_owner_approval,
)
from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text
from app.core.nova.work_revenue.operations_job_queue import JobConflict, ensure_schema
from app.core.nova.work_revenue.operations_release_gate import check_offline_release_eligibility

TENANT = "synthetic-tenant"
ACTOR = "synthetic-reviewer"
OPPORTUNITY = "synthetic-csv-cleanup-assignment"
APPROVAL = "synthetic-fixture-approval"
RAW_CSV = "Name,Department\nAda,Operations\nAda,Operations\n,\nMina,Research\n"


def run(output_dir: Path) -> dict[str, object]:
    """Exercise the existing offline queue, approval, artifact, review, and gate."""
    cleaned = clean_csv_text(RAW_CSV)
    if cleaned.input_rows != 4 or cleaned.output_rows != 2:
        raise AssertionError("Unexpected cleanup result: synthetic fixture changed")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nova-operations-synthetic-") as private:
        db_path = Path(private) / "offline.sqlite"
        db = sqlite3.connect(db_path)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            ensure_schema(db)
            ensure_handoff_schema(db)
            ensure_artifact_schema(db)
            # Fixture-only approval. No real authentication or owner authorization.
            record_verified_owner_approval(
                db, acting_tenant_id=TENANT, record_tenant_id=TENANT,
                opportunity_id=OPPORTUNITY, approval_reference=APPROVAL,
                input_sha256=cleaned.input_sha256, reviewer_id=ACTOR,
                reviewer_authorized=True,
            )
            link = handoff_approved_opportunity(
                db, acting_tenant_id=TENANT, record_tenant_id=TENANT,
                opportunity_id=OPPORTUNITY, approval_reference=APPROVAL,
                input_sha256=cleaned.input_sha256,
            )
            job = claim_approved_assignment(
                db, acting_tenant_id=TENANT, opportunity_id=OPPORTUNITY, now=100,
            )
            if job is None or job.job_id != link.job_id:
                raise AssertionError("Approved synthetic job not claimable")
            if job.input_sha256 != cleaned.input_sha256:
                raise AssertionError("Input integrity mismatch")
            complete_and_store_review_artifact(
                db, job=job, csv_text=cleaned.cleaned_csv,
                output_sha256=cleaned.output_sha256, now=101,
            )
            # The release must be blocked until explicit fixture review.
            try:
                check_offline_release_eligibility(
                    db, acting_tenant_id=TENANT, opportunity_id=OPPORTUNITY,
                )
            except JobConflict:
                pass
            else:
                raise AssertionError("Unreviewed CSV was marked releasable")
            if review_artifact(
                db, tenant_id=TENANT, job_id=job.job_id,
                reviewer_id=ACTOR, approve=True,
            ) != "approved":
                raise AssertionError("Fixture reviewer did not approve output")
        finally:
            db.close()

        # Reopen the actual SQLite file to demonstrate durable reviewed state.
        db = sqlite3.connect(db_path)
        try:
            eligible = check_offline_release_eligibility(
                db, acting_tenant_id=TENANT, opportunity_id=OPPORTUNITY,
            )
            record = read_review_artifact(db, tenant_id=TENANT, job_id=link.job_id)
            if record is None or record[0] != "approved":
                raise AssertionError("Reviewed artifact missing after reopen")
            approved_csv = record[1]
            digest = hashlib.sha256(approved_csv.encode("utf-8")).hexdigest()
            if digest != eligible.output_sha256 or digest != cleaned.output_sha256:
                raise AssertionError("Approved output checksum mismatch")
            if eligible.reviewer_id != ACTOR:
                raise AssertionError("Unexpected fixture reviewer")
        finally:
            db.close()

    # Output only fixture data, never a production or real customer upload.
    csv_path = output_dir / "nova_synthetic_cleaned.csv"
    report_path = output_dir / "nova_synthetic_acceptance.json"
    csv_path.write_text(approved_csv, encoding="utf-8", newline="")
    report: dict[str, object] = {
        "mode": "OFFLINE_SYNTHETIC_ONLY",
        "customer_upload_enabled": False,
        "real_owner_authentication_verified": False,
        "external_delivery_performed": False,
        "review_state": "approved_by_synthetic_fixture",
        "source_rows": cleaned.input_rows,
        "cleaned_rows": cleaned.output_rows,
        "duplicates_removed": cleaned.duplicate_rows_removed,
        "blank_rows_removed": cleaned.blank_rows_removed,
        "sha256": cleaned.output_sha256,
        "csv_output": csv_path.name,
        "notes": "An offline acceptance artifact only; NOT production or HTTP acceptance.",
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Directory for synthetic cleaned CSV and its offline acceptance report.",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
