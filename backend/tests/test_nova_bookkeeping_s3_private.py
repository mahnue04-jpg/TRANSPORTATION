"""Synthetic bookkeeping output through the ACTUAL private S3 adapter.

Moto provides a fake AWS S3 service entirely inside this test process.
These tests use no real S3 credentials, remote networks, or client records.
"""
from __future__ import annotations

from io import BytesIO

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import bookkeeping_durable_jobs as finance
from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs
from app.core.nova.work_revenue.bookkeeping_assignment import BookkeepingAssignment
from app.modules.platform_ops.secure_storage import S3PrivateDocumentStorage

BUCKET = "nova-accounting-ci-private"
ORG = "synthetic-accounting-org"
OWNER = "synthetic-accounting-owner"
CSV = (
    b"invoice_id,customer,invoice_date,due_date,amount,paid\n"
    b"INV-101,Invented Client,2026-10-01,2026-10-31,100.00,25.00\n"
)


@pytest.fixture
def mock_private_s3(monkeypatch):
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_BUCKET", BUCKET)
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_REGION", "us-east-1")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_ACCESS_KEY", "synthetic-key")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_SECRET_KEY", "synthetic-secret")
    monkeypatch.delenv("AMICOR_DOCUMENT_S3_ENDPOINT", raising=False)
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "true")
    monkeypatch.setenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", "true")
    with mock_aws():
        resource = boto3.resource("s3", region_name="us-east-1")
        resource.create_bucket(Bucket=BUCKET)
        client = boto3.client("s3", region_name="us-east-1")
        # Block public ACLs/policies, as required in a real bucket setup.
        client.put_public_access_block(
            Bucket=BUCKET,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        store = S3PrivateDocumentStorage()
        yield store, client


def test_private_s3_adapter_encryption_and_delete(mock_private_s3):
    store, client = mock_private_s3
    _, ref, size = store.store(
        organization_id=ORG, application_id="synthetic-job-1",
        category="nova-bookkeeping-review", filename="review.csv",
        content_type="text/csv", stream=BytesIO(CSV),
    )
    assert size == len(CSV)
    metadata = client.head_object(Bucket=BUCKET, Key=ref)
    assert metadata["ServerSideEncryption"] == "AES256"
    assert metadata["Metadata"]["amicor-private"] == "true"
    assert metadata["Metadata"]["amicor-public"] == "never"
    assert metadata["ContentType"] == "text/csv"
    assert ref.startswith(f"{ORG}/synthetic-job-1/nova-bookkeeping-review/")
    assert store.retrieve(storage_ref=ref)[0] == CSV
    controls = client.get_public_access_block(Bucket=BUCKET)[
        "PublicAccessBlockConfiguration"
    ]
    assert all(controls.values())
    store.delete(storage_ref=ref)
    with pytest.raises(Exception):
        store.retrieve(storage_ref=ref)


def test_bookkeeping_job_lifecycle_through_real_s3_adapter(mock_private_s3, monkeypatch):
    store, client = mock_private_s3
    engine = create_engine("sqlite:///:memory:")
    jobs.metadata.create_all(engine)
    # Only DB runtime is simulated; object writes use S3PrivateDocumentStorage
    # and an actual boto3 client talking to Moto's isolated in-process S3.
    monkeypatch.setattr(jobs, "require_runtime", lambda session: None)
    monkeypatch.setattr(jobs, "_store", lambda: store)
    assignment = BookkeepingAssignment(
        organization_id=ORG, owner_user_id=OWNER,
        engagement_id="synthetic-engagement", task_id="synthetic-task",
        work_type="receivables_aging", ai_assistance_permitted=True,
        data_processing_authorized=True, human_review_required=True,
        contracted_work_types=frozenset({"receivables_aging"}),
    )
    with Session(engine) as db:
        result = finance.submit_bookkeeping_review(
            db, assignment=assignment, request_id="moto-s3-ci-1",
            primary=CSV, as_of="2026-11-11",
        )
        assert result["status"] == "AWAITING_REVIEW"
        assert result["delivered"] is False
        record = db.execute(jobs.sa.select(jobs.jobs)).mappings().one()
        metadata = client.head_object(Bucket=BUCKET, Key=record["output_ref"])
        assert metadata["ServerSideEncryption"] == "AES256"
        assert metadata["Metadata"]["amicor-public"] == "never"
        content = finance.download_bookkeeping(
            db, org=ORG, owner=OWNER, job_id=result["job_id"],
        )
        assert b"75.00" in content
        finance.review_bookkeeping(
            db, org=ORG, owner=OWNER, job_id=result["job_id"], approve=True,
        )
        assert finance.download_bookkeeping(
            db, org=ORG, owner=OWNER, job_id=result["job_id"],
        ) == content
        store.delete(storage_ref=record["output_ref"])
        with pytest.raises(finance.BookkeepingJobBlocked, match="unavailable"):
            finance.download_bookkeeping(
                db, org=ORG, owner=OWNER, job_id=result["job_id"],
            )
    engine.dispose()
