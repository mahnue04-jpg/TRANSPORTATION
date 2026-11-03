"""Pure, offline upload preflight for a future authenticated CSV endpoint.

Does not accept requests, access customer storage, or activate API routes.
The caller must authenticate and derive tenant identity from the session.
"""
from __future__ import annotations

from dataclasses import dataclass


class CSVUploadRejected(ValueError):
    """An upload does not satisfy the CSV preflight contract."""


@dataclass(frozen=True)
class CSVUpload:
    filename: str
    csv_text: str
    byte_count: int


def validate_csv_upload(
    *, filename: str, content_type: str | None, payload: bytes,
    max_bytes: int = 1_000_000,
) -> CSVUpload:
    if not isinstance(filename, str) or not filename.lower().endswith(".csv"):
        raise CSVUploadRejected("A .csv filename is required")
    if "/" in filename or "\\" in filename or len(filename) > 128:
        raise CSVUploadRejected("Unsafe CSV filename")
    if content_type not in ("text/csv", "application/vnd.ms-excel", "application/octet-stream"):
        raise CSVUploadRejected("Unsupported CSV content type")
    if not isinstance(payload, bytes) or not payload or len(payload) > max_bytes:
        raise CSVUploadRejected("Empty or oversized CSV")
    if b"\x00" in payload:
        raise CSVUploadRejected("Binary content is not CSV")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CSVUploadRejected("CSV must use UTF-8") from exc
    if not decoded.strip():
        raise CSVUploadRejected("Empty CSV")
    return CSVUpload(filename=filename, csv_text=decoded, byte_count=len(payload))
