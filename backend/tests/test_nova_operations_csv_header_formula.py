"""Regression checks for spreadsheet-formula safety in Operations CSV exports.

Synthetic-only: no customer data, providers or external sends.
"""
import csv
import io

import pytest

from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text


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
