"""Explicit, staging-only private object storage write/read/delete canary.

This is an operator-only verification against the configured staging bucket.
Default is dry-run, which does not contact S3. The --apply mode creates a
random, non-customer test object, checks remote bytes and metadata, and
deletes only that exact object. It never interacts with video providers,
production, user media, or application database records.

Do not run in CI against a real bucket. Use an authorized staging shell with
secrets supplied privately by the service environment, not command arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys

from app.core.nova.creative_studio import private_object_storage as storage


class CanaryBlocked(RuntimeError):
    pass


def _assert_staging() -> None:
    if os.environ.get("APP_ENV", "").strip().lower() not in {"stage", "staging"}:
        raise CanaryBlocked("STAGING_ONLY")
    if not storage.enabled():
        raise CanaryBlocked("PRIVATE_STORAGE_DISABLED")


def _is_missing_object(exc: Exception) -> bool:
    try:
        code = str(exc.response["Error"]["Code"])
        status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        return code in {"404", "NoSuchKey", "NotFound"} and status in {0, 404}
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _must_be_absent(client, bucket: str, key: str) -> None:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if _is_missing_object(exc):
            return
        raise CanaryBlocked("CANNOT_VERIFY_CANARY_ABSENCE") from exc
    raise CanaryBlocked("CANARY_OBJECT_ALREADY_PRESENT")


def run_canary(*, client=None, bucket: str | None = None,
               random_hex=None) -> dict:
    """Write and verify one unpredictable canary; clean it up on every path."""
    _assert_staging()
    client = client or storage._client()
    bucket = bucket or storage._bucket()
    random_hex = random_hex or secrets.token_hex
    key = "studio-readiness-canary/" + random_hex(24) + ".bin"
    payload = secrets.token_bytes(4096)
    sha = hashlib.sha256(payload).hexdigest()
    _must_be_absent(client, bucket, key)
    created = False
    failure = None
    try:
        # A conditional put avoids overwriting any unrelated key even in
        # the negligible event of a random identifier collision.
        client.put_object(
            Bucket=bucket, Key=key, Body=payload,
            ContentType="application/octet-stream",
            Metadata={"sha256": sha}, IfNoneMatch="*",
        )
        created = True
        head = client.head_object(Bucket=bucket, Key=key)
        if (int(head.get("ContentLength", -1)) != len(payload) or
                head.get("Metadata", {}).get("sha256") != sha):
            raise CanaryBlocked("CANARY_HEAD_VERIFICATION_FAILED")
        response = client.get_object(Bucket=bucket, Key=key)
        body = response.get("Body")
        if body is None:
            raise CanaryBlocked("CANARY_READ_FAILED")
        try:
            data = body.read(len(payload) + 1)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if data != payload or hashlib.sha256(data).hexdigest() != sha:
            raise CanaryBlocked("CANARY_BYTE_INTEGRITY_FAILED")
    except Exception as exc:
        failure = exc
    finally:
        if created:
            try:
                client.delete_object(Bucket=bucket, Key=key)
                _must_be_absent(client, bucket, key)
            except Exception as exc:
                # Never call this successful: a probe object might remain.
                raise CanaryBlocked("CANARY_CLEANUP_UNVERIFIED") from exc
    if failure is not None:
        raise CanaryBlocked(
            str(failure) if isinstance(failure, CanaryBlocked)
            else "CANARY_STORAGE_OPERATION_FAILED"
        ) from failure
    return {
        "canary": "passed",
        "write_verified": True,
        "head_verified": True,
        "full_byte_read_verified": True,
        "cleanup_verified": True,
        "test_object_bytes": len(payload),
        "production_touched": False,
        "real_video_verified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-staging-test-object", action="store_true")
    args = parser.parse_args(argv)
    try:
        _assert_staging()
        if not args.apply:
            print(json.dumps({"status": "dry_run", "writes": False,
                              "message": "No bucket request was made."}))
            return 0
        if not args.acknowledge_staging_test_object:
            raise CanaryBlocked("EXPLICIT_STAGING_TEST_ACK_REQUIRED")
        print(json.dumps({"status": "passed", "checks": run_canary()}, sort_keys=True))
        return 0
    except CanaryBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 1
    except Exception:
        # Do not echo exceptions containing endpoint URLs or credentials.
        print(json.dumps({"status": "blocked", "reason": "STORAGE_OPERATION_FAILED"}),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
