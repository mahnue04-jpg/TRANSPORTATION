"""Offline tests for deterministic, bounded CSV cleanup."""
import pytest
from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text, SpreadsheetInputError


def test_cleanup_report_and_stable_hashes():
    sample = "Name,Email\n Ana , a@example.com \nAna,a@example.com\n,\nBen,b@example.com\n"
    result = clean_csv_text(sample)
    assert result.input_rows == 4
    assert result.output_rows == 2
    assert result.duplicate_rows_removed == 1
    assert result.blank_rows_removed == 1
    assert result.cleaned_csv == "Name,Email\nAna,a@example.com\nBen,b@example.com\n"
    assert result.output_sha256 == clean_csv_text(sample).output_sha256


def test_formula_cells_are_escaped():
    result = clean_csv_text("Name,Value\nAna,=1+1\nBen,@SUM(1)\n")
    assert "'=1+1" in result.cleaned_csv
    assert "'@SUM(1)" in result.cleaned_csv


@pytest.mark.parametrize("text", [
    "", "Name,Name\na,b\n", "Name,\na,b\n",
    "Name,Email\nAna\n", "Name,Email\nAna,a,b\n",
    "Name,Email\nAna,a\nBen,b\n",
])
def test_invalid_or_limited_inputs(text):
    if text == "Name,Email\nAna,a\nBen,b\n":
        with pytest.raises(SpreadsheetInputError):
            clean_csv_text(text, max_rows=1)
    else:
        with pytest.raises(SpreadsheetInputError):
            clean_csv_text(text)
