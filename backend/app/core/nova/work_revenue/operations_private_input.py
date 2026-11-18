"""Development-only private CSV input adapter for future durable worker use.

This module stores and reads bounded owner-scoped input using the existing
private object adapter. It DOES NOT persist an input_ref to PostgreSQL, enqueue
work, create an HTTP route, or enable a worker. A migration plus transactional
idempotency and orphan reconciliation are prerequisites for any real use.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from io import BytesIO



MAX_INPUT_BYTES = 1_000_000


class PrivateInputBlocked(ValueError):
    pass


@dataclass(frozen=True)
class PrivateInputReceipt:
    storage_ref: str
    sha256: str
    size: int


def _valid_identity(value: str, maximum: int = 36) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and value.isascii() and all(c.isalnum() or c in "-_" for c in value))


def persist_private_csv_input(
    *, organization_id: str, owner_user_id: str, job_id: str, raw: bytes,
    store,
) -> PrivateInputReceipt:
    """Write private input only; caller must persist returned ref atomically.

    Idempotent object naming and safe cleanup of ambiguous writes require a
    separate, reviewed transaction/reconciliation implementation.
    """
    if not all(_valid_identity(v) for v in
               (organization_id, owner_user_id, job_id)):
        raise PrivateInputBlocked("Invalid private input job scope")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise PrivateInputBlocked("Invalid CSV input size")
    digest = hashlib.sha256(raw).hexdigest()
    # An owner-separated job path prevents accidental reuse across owners.
    # The storage adapter must independently enforce private bucket access.
    saved = store.store(
        organization_id=organization_id,
        application_id=job_id,
        category="nova-csv-input-" + owner_user_id,
        filename="source.csv",
        content_type="text/csv",
        stream=BytesIO(raw),
    )
    if (not isinstance(saved, (tuple, list)) or len(saved) < 3
            or not isinstance(saved[1], str) or not saved[1]
            or saved[2] != len(raw)):
        raise PrivateInputBlocked("Private input write not confirmed")
    return PrivateInputReceipt(storage_ref=saved[1], sha256=digest, size=len(raw))


def load_private_csv_input(
    *, organization_id: str, owner_user_id: str, job_id: str,
    storage_ref: str, expected_sha256: str, store,
) -> bytes:
    """Read only DB-provenance private refs; verify scope and SHA before use.

    This function cannot itself prove storage_ref came from an authorized DB
    record; the future worker must fetch it from a scoped immutable job row,
    check current engagement approval, then invoke this adapter.
    """
    if not all(_valid_identity(v) for v in
               (organization_id, owner_user_id, job_id)):
        raise PrivateInputBlocked("Invalid private input job scope")
    if not isinstance(storage_ref, str) or not storage_ref:
        raise PrivateInputBlocked("Durable private input reference required")
    if not isinstance(expected_sha256, str):
        raise PrivateInputBlocked("Input fingerprint required")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef"
                                        for c in expected_sha256):
        raise PrivateInputBlocked("Invalid input fingerprint")
    try:
        raw, content_type = store.retrieve(storage_ref=storage_ref)
    except Exception as exc:
        raise PrivateInputBlocked("Private input cannot be retrieved") from exc
    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_INPUT_BYTES
            or content_type not in ("text/csv", "application/octet-stream")):
        raise PrivateInputBlocked("Private input content invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        raise PrivateInputBlocked("Private input fingerprint mismatch")
    return raw
