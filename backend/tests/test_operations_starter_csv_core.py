"""Pure offline CSV cleanup release-candidate regressions (no payment/storage)."""
import hashlib
import pytest

from app.core.nova.work_revenue.operations_csv_cleanup import (
    SpreadsheetInputError, clean_csv_text,
)


def test_deduplicate_and_remove_blank_rows():
    result = clean_csv_text("Name,Status\nAlice,Active\nAlice,Active\n,\nBob,Pending\n")
    assert result.cleaned_csv == "Name,Status\nAlice,Active\nBob,Pending\n"
    assert (result.input_rows, result.output_rows) == (4, 2)
    assert (result.duplicate_rows_removed, result.blank_rows_removed) == (1, 1)
    assert result.output_sha256 == hashlib.sha256(result.cleaned_csv.encode()).hexdigest()


@pytest.mark.parametrize("value", [
    "=1+1", "+SUM(A1:A2)", "-1+2", "@HYPERLINK(\"https://example.invalid\")",
])
def test_formula_injection_is_escaped(value):
    result = clean_csv_text("Formula\n" + value + "\n")
    assert result.cleaned_csv.splitlines()[1].startswith("'")
    assert value in result.cleaned_csv


@pytest.mark.parametrize("text", [
    "", "Bad,\n1,2\n", "A,a\n1,2\n", "A,B\n1\n",
    "A\nhi\x00there\n", "A\n1\n2\n3\n",
])
def test_invalid_inputs_fail_closed(text):
    with pytest.raises(SpreadsheetInputError):
        clean_csv_text(text, max_rows=2)


def test_limit_prevents_oversized_data():
    with pytest.raises(SpreadsheetInputError):
        clean_csv_text("Name\nlonger-than-limit\n", max_bytes=8)


def test_output_stable_for_same_input():
    raw = "Name,Status\nAlice,Active\nAlice,Active\n"
    a, b = clean_csv_text(raw), clean_csv_text(raw)
    assert a == b
