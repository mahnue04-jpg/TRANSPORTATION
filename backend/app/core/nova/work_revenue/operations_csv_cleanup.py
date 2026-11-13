"""Offline CSV cleanup for Nova Operations Agent.

No customer uploads, external calls, background execution, or live integrations.
Operates on caller-supplied CSV text and returns reviewable output plus a report.
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass


class SpreadsheetInputError(ValueError):
    pass


@dataclass(frozen=True)
class CleanupResult:
    cleaned_csv: str
    input_sha256: str
    output_sha256: str
    input_rows: int
    output_rows: int
    duplicate_rows_removed: int
    blank_rows_removed: int
    columns: tuple[str, ...]


def clean_csv_text(
    raw_csv: str, *, max_bytes: int = 1_000_000, max_rows: int = 10_000
) -> CleanupResult:
    if not isinstance(raw_csv, str) or not 0 < max_bytes <= 10_000_000 or max_rows < 1:
        raise SpreadsheetInputError("Invalid CSV or processing limits")
    encoded = raw_csv.encode("utf-8")
    if not encoded or len(encoded) > max_bytes or "\x00" in raw_csv:
        raise SpreadsheetInputError("CSV empty, oversized or contains NUL")
    try:
        reader = csv.reader(io.StringIO(raw_csv, newline=""), strict=True)
        header = next(reader)
        if not header or any(not col.strip() for col in header):
            raise SpreadsheetInputError("CSV requires nonempty column names")
        columns = tuple(col.strip() for col in header)
        if len(set(c.casefold() for c in columns)) != len(columns):
            raise SpreadsheetInputError("Duplicate column names")
        rows: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        input_rows = duplicates = blanks = 0
        for raw in reader:
            input_rows += 1
            if input_rows > max_rows:
                raise SpreadsheetInputError("CSV exceeds row limit")
            if len(raw) != len(columns):
                raise SpreadsheetInputError(f"Column mismatch at row {input_rows + 1}")
            values = tuple(value.strip() for value in raw)
            if all(not value for value in values):
                blanks += 1
            elif values in seen:
                duplicates += 1
            else:
                seen.add(values)
                rows.append(values)
    except (csv.Error, StopIteration) as exc:
        raise SpreadsheetInputError("Invalid CSV structure") from exc
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    # Spreadsheet applications also evaluate formulas in the header row.
    # Escape headers and values consistently; CSV quoting alone is insufficient.
    def safe_spreadsheet_cell(value: str) -> str:
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    writer.writerow(tuple(safe_spreadsheet_cell(column) for column in columns))
    for row in rows:
        writer.writerow(tuple(safe_spreadsheet_cell(value) for value in row))
    cleaned = out.getvalue()
    return CleanupResult(
        cleaned_csv=cleaned,
        input_sha256=hashlib.sha256(encoded).hexdigest(),
        output_sha256=hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
        input_rows=input_rows,
        output_rows=len(rows),
        duplicate_rows_removed=duplicates,
        blank_rows_removed=blanks,
        columns=columns,
    )
