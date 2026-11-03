"""Offline CSV upload preflight contract tests."""
import pytest

from app.core.nova.work_revenue.operations_csv_preflight import (
    CSVUploadRejected, validate_csv_upload,
)


def test_valid_utf8_csv_and_bom():
    result = validate_csv_upload(
        filename="records.csv", content_type="text/csv",
        payload=b"\xef\xbb\xbfName\nAna\n",
    )
    assert result.csv_text == "Name\nAna\n"
    assert result.byte_count == len(b"\xef\xbb\xbfName\nAna\n")


@pytest.mark.parametrize("filename,content_type,payload", [
    ("records.txt", "text/csv", b"a,b\n1,2\n"),
    ("../records.csv", "text/csv", b"a,b\n1,2\n"),
    ("records.csv", "image/png", b"a,b\n1,2\n"),
    ("records.csv", "text/csv", b""),
    ("records.csv", "text/csv", b"\x00a,b"),
    ("records.csv", "text/csv", b"\xff"),
    ("records.csv", "text/csv", b"   "),
])
def test_rejects_invalid_upload(filename, content_type, payload):
    with pytest.raises(CSVUploadRejected):
        validate_csv_upload(filename=filename, content_type=content_type, payload=payload)


def test_rejects_oversize_before_decoding():
    with pytest.raises(CSVUploadRejected, match="oversized"):
        validate_csv_upload(
            filename="records.csv", content_type="text/csv",
            payload=b"x" * 9, max_bytes=8,
        )
