"""Regression checks for spreadsheet-formula safety in Operations CSV exports.

Synthetic-only: no customer data, providers or external sends.
"""
import csv
import io

import pytest

from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text, SpreadsheetInputError


@pytest.mark.parametrize("header", ["=1+1", "+SUM(A1:A2)", "-1+2", "@SUM(A1:A2)", "  =HYPERLINK(A1)"])
def test_formula_like_column_header_is_escaped(header):
    source = io.StringIO(newline="")
    writer = csv.writer(source)
    writer.writerow([header, "Safe"])
    writer.writerow(["regular", "value"])

    result = clean_csv_text(source.getvalue())
    rows = list(csv.reader(io.StringIO(result.cleaned_csv, newline="")))
    assert rows[0][0] == "'" + header.strip()
    assert rows[0][1] == "Safe"
    assert rows[1] == ["regular", "value"]


@pytest.mark.parametrize("value", ["=1+1", "+1", "-2", "@name", "  =1+1"])
def test_formula_like_data_value_is_still_escaped(value):
    source = io.StringIO(newline="")
    writer = csv.writer(source)
    writer.writerow(["Name"])
    writer.writerow([value])
    result = clean_csv_text(source.getvalue())
    rows = list(csv.reader(io.StringIO(result.cleaned_csv, newline="")))
    assert rows[1][0] == "'" + value.strip()


def test_safe_csv_preserves_headers_and_deduplication():
    result = clean_csv_text("Name,Email\nAna,a@example.com\nAna,a@example.com\n")
    rows = list(csv.reader(io.StringIO(result.cleaned_csv, newline="")))
    assert rows == [["Name", "Email"], ["Ana", "a@example.com"]]
    assert result.duplicate_rows_removed == 1


def test_offline_runner_stores_escaped_header_for_owner_review(tmp_path):
    """Verify the durable *offline fixture* handoff never stores active formulas."""
    import sqlite3
    from app.core.nova.work_revenue.operations_job_queue import ensure_schema
    from app.core.nova.work_revenue.operations_csv_runner import prepare_csv_job
    from app.core.nova.work_revenue.operations_artifact_review import read_review_artifact

    db = sqlite3.connect(tmp_path / "header-security.sqlite")
    try:
        ensure_schema(db)
        prepared = prepare_csv_job(
            db, tenant_id="synthetic-tenant", request_id="header-security",
            raw_csv="=SUM(A1:A2),Name\n=2+2,Ana\n",
            now=100,
        )
        review_state, stored_csv = read_review_artifact(
            db, tenant_id="synthetic-tenant", job_id=prepared.job_id,
        )
        assert review_state == "awaiting_review"
        rows = list(csv.reader(io.StringIO(stored_csv, newline="")))
        assert rows == [["'=SUM(A1:A2)", "Name"], ["'=2+2", "Ana"]]
    finally:
        db.close()


def test_output_expansion_fails_before_artifact_storage():
    # Input fits its limit but formula escaping expands the exported CSV.
    with pytest.raises(SpreadsheetInputError, match="output size limit"):
        clean_csv_text("Name\n=1\n=2\n", max_bytes=11)


def test_output_exact_limit_allowed():
    result = clean_csv_text("Name\nAna\n", max_bytes=9)
    assert len(result.cleaned_csv.encode("utf-8")) == 9
