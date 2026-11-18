"""Read-only S3-compatible object-prefix adapter for Operations orphan audits.

Caller supplies credentials/client scoped to an isolated private bucket and
must independently enforce the authenticated owner/organization identity.
No bucket discovery, broad listing, deletion, download, public link or retry.
Never call from an unauthenticated route or production without separate approval.
"""
from __future__ import annotations

import re


class PrivateListingBlocked(ValueError):
    pass


_SCOPED_PREFIX = re.compile(r"^[A-Za-z0-9_-]{1,36}/[A-Za-z0-9_-]{1,36}/$")


def list_scoped_s3_keys(
    client, *, bucket: str, prefix: str, max_objects: int = 1000,
) -> list[str]:
    """Read at most a bounded owner-authorized job prefix from private S3.

    The caller MUST verify that prefix belongs to the authenticated job before
    invoking this helper. All returned keys are passed to the audit only,
    never to a deletion operation.
    """
    if not isinstance(bucket, str) or not bucket or len(bucket) > 255:
        raise PrivateListingBlocked("Configured private bucket required")
    if not isinstance(prefix, str) or not _SCOPED_PREFIX.fullmatch(prefix):
        raise PrivateListingBlocked("Exact organization and job prefix required")
    if type(max_objects) is not int or not 1 <= max_objects <= 1000:
        raise PrivateListingBlocked("Invalid private listing limit")
    if not callable(getattr(client, "list_objects_v2", None)):
        raise PrivateListingBlocked("Read-only private S3 client required")

    observed = []
    token = None
    for _page in range(20):
        request = dict(Bucket=bucket, Prefix=prefix,
                       MaxKeys=min(1000, max_objects - len(observed) + 1))
        if token is not None:
            request["ContinuationToken"] = token
        try:
            page = client.list_objects_v2(**request)
        except Exception as exc:
            raise PrivateListingBlocked("Private S3 listing unavailable") from exc
        if not isinstance(page, dict) or not isinstance(page.get("Contents", []), list):
            raise PrivateListingBlocked("Invalid private S3 listing response")
        for obj in page.get("Contents", []):
            key = obj.get("Key") if isinstance(obj, dict) else None
            if not isinstance(key, str) or not key.startswith(prefix):
                raise PrivateListingBlocked("S3 returned an object outside job scope")
            if key in observed:
                raise PrivateListingBlocked("S3 returned a duplicate object")
            observed.append(key)
            if len(observed) > max_objects:
                raise PrivateListingBlocked("Private listing exceeds audit limit")
        if not page.get("IsTruncated", False):
            return observed
        token = page.get("NextContinuationToken")
        if not isinstance(token, str) or not token:
            raise PrivateListingBlocked("Incomplete private S3 pagination")
    raise PrivateListingBlocked("Private S3 audit page limit exceeded")
