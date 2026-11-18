"""No-network tests for read-only, bounded S3 orphan inventory."""
import pytest

from app.core.nova.work_revenue.operations_orphan_s3_listing import (
    PrivateListingBlocked, list_scoped_s3_keys,
)


class FakePagedS3:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(kwargs)
        cursor = kwargs.get("ContinuationToken", "start")
        return self.pages[cursor]


def test_private_s3_listing_is_prefix_bound_and_paged():
    prefix = "synthetic-org/synthetic-job/"
    client = FakePagedS3({
        "start": {
            "Contents": [{"Key": prefix + "input/a.csv"}],
            "IsTruncated": True, "NextContinuationToken": "next",
        },
        "next": {
            "Contents": [{"Key": prefix + "output/b.csv"}],
            "IsTruncated": False,
        },
    })
    found = list_scoped_s3_keys(
        client, bucket="synthetic-private-bucket", prefix=prefix)
    assert found == [prefix + "input/a.csv", prefix + "output/b.csv"]
    assert len(client.calls) == 2
    assert all(call["Prefix"] == prefix
               and call["Bucket"] == "synthetic-private-bucket"
               for call in client.calls)
    assert client.calls[1]["ContinuationToken"] == "next"
    assert all("Delete" not in str(call) and "public" not in str(call)
               for call in client.calls)


def test_private_s3_listing_rejects_bucket_wide_and_foreign_key():
    prefix = "synthetic-org/synthetic-job/"
    client = FakePagedS3({"start": {
        "Contents": [{"Key": "other-org/job-a/secret.csv"}],
        "IsTruncated": False,
    }})
    with pytest.raises(PrivateListingBlocked, match="Exact organization"):
        list_scoped_s3_keys(client, bucket="synthetic-private", prefix="")
    assert client.calls == []
    with pytest.raises(PrivateListingBlocked, match="outside job scope"):
        list_scoped_s3_keys(client, bucket="synthetic-private", prefix=prefix)


def test_private_s3_listing_rejects_overflow_and_bad_pagination():
    prefix = "synthetic-org/synthetic-job/"
    client = FakePagedS3({"start": {
        "Contents": [{"Key": prefix + "first"}, {"Key": prefix + "second"}],
        "IsTruncated": False,
    }})
    with pytest.raises(PrivateListingBlocked, match="audit limit"):
        list_scoped_s3_keys(client, bucket="synthetic-private",
                            prefix=prefix, max_objects=1)
    malformed = FakePagedS3({"start": {
        "Contents": [], "IsTruncated": True,
    }})
    with pytest.raises(PrivateListingBlocked, match="pagination"):
        list_scoped_s3_keys(malformed, bucket="synthetic-private",
                            prefix=prefix)


def test_private_s3_listing_blocks_duplicate_and_provider_error():
    prefix = "synthetic-org/synthetic-job/"
    duplicate = FakePagedS3({"start": {
        "Contents": [{"Key": prefix + "same"}, {"Key": prefix + "same"}],
        "IsTruncated": False,
    }})
    with pytest.raises(PrivateListingBlocked, match="duplicate"):
        list_scoped_s3_keys(duplicate, bucket="synthetic-private", prefix=prefix)

    class Offline:
        def list_objects_v2(self, **kwargs):
            raise RuntimeError("synthetic provider outage")

    with pytest.raises(PrivateListingBlocked, match="unavailable"):
        list_scoped_s3_keys(Offline(), bucket="synthetic-private",
                            prefix=prefix)
