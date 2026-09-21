"""Secure engagement-level source inputs for Nova Work & Revenue."""
from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.models import NovaWorkInput
from app.core.nova.work_revenue.service import NovaWorkError, _record_audit, get_engagement
from app.helpers import now, uuid4

MAX_WORK_INPUT_BYTES = 20 * 1024 * 1024
_ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".txt", ".json", ".pdf", ".docx"}
_ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "text/plain",
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}


def _safe_token(value: str, limit: int = 120) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", value or "")[:limit]


def work_input_root() -> Path:
    configured = (os.getenv("NOVA_WORK_INPUT_DIR") or "").strip()
    if configured:
        root = Path(configured)
    else:
        persistent_parent = Path("/data/onboarding_docs")
        root = (
            persistent_parent / "nova_work_inputs"
            if persistent_parent.exists()
            else Path("/tmp/amicor/nova-work-inputs")
        )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path_for(organization_id: str, engagement_id: str, input_id: str, filename: str) -> Path:
    org = _safe_token(organization_id, 64) or "org"
    eng = _safe_token(engagement_id, 64) or "engagement"
    item = _safe_token(input_id, 64) or "input"
    ext = Path(filename).suffix.lower()
    dest = work_input_root() / org / eng
    dest.mkdir(parents=True, exist_ok=True)
    return dest / f"{item}{ext}"


def _validate_file(filename: str, content_type: str, content: bytes) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise NovaWorkError("Unsupported work input file type", status_code=415)
    normalized_type = str(content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if normalized_type not in _ALLOWED_CONTENT_TYPES:
        raise NovaWorkError("Unsupported work input content type", status_code=415)
    if not content:
        raise NovaWorkError("Work input file is empty", status_code=400)
    if len(content) > MAX_WORK_INPUT_BYTES:
        raise NovaWorkError("Work input exceeds the 20 MB limit", status_code=413)


def _extract_text(filename: str, content_type: str, content: bytes) -> tuple[str, dict[str, Any]]:
    ext = Path(filename).suffix.lower()
    diagnostics: dict[str, Any] = {"filename": filename, "content_type": content_type, "parser": None}
    if ext == ".txt":
        diagnostics["parser"] = "utf-8"
        return content.decode("utf-8", errors="replace"), diagnostics
    if ext == ".csv":
        diagnostics["parser"] = "csv"
        text = content.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        preview_rows = rows[:500]
        preview = "\n".join("\t".join(str(cell) for cell in row) for row in preview_rows)
        width = max((len(row) for row in preview_rows), default=0)
        blank_cells = sum(1 for row in preview_rows for cell in row if str(cell).strip() == "")
        normalized_rows = [tuple(str(cell) for cell in row) for row in preview_rows]
        duplicate_rows = max(0, len(normalized_rows) - len(set(normalized_rows)))
        diagnostics.update({
            "rows_detected": len(rows),
            "preview_rows": len(preview_rows),
            "columns_detected": width,
            "blank_cells_in_preview": blank_cells,
            "duplicate_rows_in_preview": duplicate_rows,
        })
        return preview, diagnostics
    if ext == ".json":
        diagnostics["parser"] = "json"
        parsed = json.loads(content.decode("utf-8-sig", errors="strict"))
        if isinstance(parsed, list):
            diagnostics["records_detected"] = len(parsed)
        return json.dumps(parsed, ensure_ascii=False, indent=2)[:250000], diagnostics
    if ext == ".xlsx":
        diagnostics["parser"] = "openpyxl"
        openpyxl = importlib.import_module("openpyxl")
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        lines: list[str] = []
        sheet_count = 0
        row_count = 0
        max_columns = 0
        blank_cells = 0
        normalized_rows: list[tuple[str, ...]] = []
        for sheet in workbook.worksheets:
            sheet_count += 1
            lines.append(f"[SHEET] {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                row_count += 1
                values = tuple("" if cell is None else str(cell) for cell in row)
                max_columns = max(max_columns, len(values))
                blank_cells += sum(1 for value in values if value.strip() == "")
                normalized_rows.append(values)
                lines.append("\t".join(values))
                if row_count >= 500:
                    break
            if row_count >= 500:
                break
        duplicate_rows = max(0, len(normalized_rows) - len(set(normalized_rows)))
        diagnostics.update({
            "sheets_detected": sheet_count,
            "preview_rows": row_count,
            "columns_detected": max_columns,
            "blank_cells_in_preview": blank_cells,
            "duplicate_rows_in_preview": duplicate_rows,
        })
        return "\n".join(lines), diagnostics
    if ext == ".docx":
        diagnostics["parser"] = "python-docx"
        docx = importlib.import_module("docx")
        document = docx.Document(io.BytesIO(content))
        paragraphs = [str(p.text) for p in document.paragraphs if str(p.text).strip()]
        return "\n".join(paragraphs)[:250000], diagnostics
    if ext == ".pdf":
        diagnostics["parser"] = "pypdf"
        pypdf = importlib.import_module("pypdf")
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages: list[str] = []
        for page in reader.pages[:100]:
            pages.append(page.extract_text() or "")
        diagnostics["pages_detected"] = len(reader.pages)
        return "\n".join(pages)[:250000], diagnostics
    return "", diagnostics


def create_work_input(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
    filename: str,
    content_type: str,
    content: bytes,
    notes: str | None = None,
) -> dict[str, Any]:
    get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    _validate_file(filename, content_type, content)
    input_id = "NWI-" + uuid4().replace("-", "")[:12].upper()
    digest = hashlib.sha256(content).hexdigest()
    dest = _path_for(organization_id, engagement_id, input_id, filename)
    dest.write_bytes(content)
    row = NovaWorkInput(
        input_id=input_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        engagement_id=engagement_id,
        original_filename=Path(filename).name[:255],
        content_type=str(content_type or "application/octet-stream")[:120],
        file_size=len(content),
        sha256=digest,
        storage_ref=str(dest),
        status="AVAILABLE",
        notes=(notes or None),
        is_active=True,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="WORK_INPUT_UPLOADED",
        summary=f"Work input uploaded for engagement {engagement_id}: {row.original_filename}. Internal use only.",
        ref_id=input_id,
        entity_type="work_input",
        actor_category="OWNER",
        new_state="AVAILABLE",
    )
    db.commit()
    db.refresh(row)
    return work_input_out(row)


def create_generated_output(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
    filename: str,
    content_type: str,
    content: bytes,
    notes: str | None = None,
) -> dict[str, Any]:
    get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    if not content:
        raise NovaWorkError("Generated output is empty", status_code=400)
    input_id = "NWO-" + uuid4().replace("-", "")[:12].upper()
    digest = hashlib.sha256(content).hexdigest()
    dest = _path_for(organization_id, engagement_id, input_id, filename)
    dest.write_bytes(content)
    row = NovaWorkInput(
        input_id=input_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        engagement_id=engagement_id,
        input_kind="GENERATED_OUTPUT",
        original_filename=Path(filename).name[:255],
        content_type=str(content_type or "application/octet-stream")[:120],
        file_size=len(content),
        sha256=digest,
        storage_ref=str(dest),
        status="AVAILABLE",
        notes=(notes or None),
        is_active=True,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="WORK_OUTPUT_GENERATED",
        summary=f"Nova generated internal work output for engagement {engagement_id}: {row.original_filename}.",
        ref_id=input_id,
        entity_type="work_output",
        actor_category="NOVA",
        new_state="AVAILABLE",
    )
    db.commit()
    db.refresh(row)
    return work_input_out(row)


def process_tabular_source(row: NovaWorkInput) -> dict[str, Any]:
    path = input_file_path(row)
    if path is None:
        raise NovaWorkError("Source file is not stored", status_code=404)
    ext = Path(row.original_filename).suffix.lower()
    if ext not in {".csv", ".xlsx"}:
        raise NovaWorkError("Tabular transformation currently supports CSV and XLSX", status_code=409)

    raw_rows: list[list[str]] = []
    if ext == ".csv":
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        raw_rows = [[str(cell) for cell in record] for record in csv.reader(io.StringIO(text))]
    else:
        openpyxl = importlib.import_module("openpyxl")
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        raw_rows = [
            ["" if cell is None else str(cell) for cell in values]
            for values in sheet.iter_rows(values_only=True)
        ]

    if not raw_rows:
        raise NovaWorkError("Tabular source has no rows", status_code=409)

    width = max(len(record) for record in raw_rows)
    normalized: list[list[str]] = []
    for record in raw_rows:
        padded = list(record) + [""] * (width - len(record))
        normalized.append([str(cell).strip() for cell in padded])

    header = normalized[0]
    for index, value in enumerate(header):
        if not value:
            header[index] = f"column_{index + 1}"

    data_rows = normalized[1:]
    seen: set[tuple[str, ...]] = set()
    cleaned_rows: list[list[str]] = []
    duplicate_rows_removed = 0
    for record in data_rows:
        key = tuple(record)
        if key in seen:
            duplicate_rows_removed += 1
            continue
        seen.add(key)
        cleaned_rows.append(record)

    blank_cells = sum(1 for record in cleaned_rows for cell in record if cell == "")
    inconsistent_rows = sum(1 for record in raw_rows if len(record) != width)

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(cleaned_rows)
    content = output.getvalue().encode("utf-8")

    validation = {
        "source_filename": row.original_filename,
        "source_format": ext.lstrip("."),
        "source_rows_including_header": len(raw_rows),
        "source_data_rows": len(data_rows),
        "columns": width,
        "duplicate_rows_removed": duplicate_rows_removed,
        "cleaned_data_rows": len(cleaned_rows),
        "blank_cells_retained": blank_cells,
        "inconsistent_width_rows": inconsistent_rows,
        "header_columns": header,
        "row_count_reconciles": len(cleaned_rows) == len(data_rows) - duplicate_rows_removed,
        "column_count_reconciles": all(len(record) == width for record in cleaned_rows),
        "missing_values_imputed": False,
        "domain_specific_formulas_applied": False,
    }
    validation["validated"] = bool(
        validation["row_count_reconciles"] and validation["column_count_reconciles"]
    )
    return {"content": content, "validation": validation}


def work_input_out(row: NovaWorkInput) -> dict[str, Any]:
    return {
        "input_id": row.input_id,
        "engagement_id": row.engagement_id,
        "input_kind": row.input_kind,
        "original_filename": row.original_filename,
        "content_type": row.content_type,
        "file_size": row.file_size,
        "sha256": row.sha256,
        "status": row.status,
        "notes": row.notes,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_work_inputs(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> list[dict[str, Any]]:
    get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    rows = (
        db.query(NovaWorkInput)
        .filter(
            NovaWorkInput.organization_id == organization_id,
            NovaWorkInput.engagement_id == engagement_id,
            NovaWorkInput.is_active.is_(True),
        )
        .order_by(NovaWorkInput.created_at.desc())
        .all()
    )
    return [work_input_out(row) for row in rows]


def get_work_input(
    db: Session,
    engagement_id: str,
    input_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkInput:
    get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    row = (
        db.query(NovaWorkInput)
        .filter(
            NovaWorkInput.organization_id == organization_id,
            NovaWorkInput.engagement_id == engagement_id,
            NovaWorkInput.input_id == input_id,
            NovaWorkInput.is_active.is_(True),
        )
        .first()
    )
    if row is None:
        raise NovaWorkError("Work input not found", status_code=404)
    return row


def input_file_path(row: NovaWorkInput) -> Path | None:
    path = Path(row.storage_ref)
    return path if path.is_file() else None


def inspect_work_inputs(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    rows = (
        db.query(NovaWorkInput)
        .filter(
            NovaWorkInput.organization_id == organization_id,
            NovaWorkInput.engagement_id == engagement_id,
            NovaWorkInput.input_kind == "SOURCE_DATA",
            NovaWorkInput.is_active.is_(True),
            NovaWorkInput.status == "AVAILABLE",
        )
        .order_by(NovaWorkInput.created_at.asc())
        .all()
    )
    parsed: list[dict[str, Any]] = []
    for row in rows:
        path = input_file_path(row)
        if path is None:
            parsed.append({"input_id": row.input_id, "filename": row.original_filename, "available": False})
            continue
        try:
            content = path.read_bytes()
            text, diagnostics = _extract_text(row.original_filename, row.content_type, content)
            parsed.append({
                "input_id": row.input_id,
                "filename": row.original_filename,
                "available": True,
                "text": text,
                "diagnostics": diagnostics,
            })
        except Exception as exc:
            parsed.append({
                "input_id": row.input_id,
                "filename": row.original_filename,
                "available": True,
                "parse_error": str(exc)[:400],
            })
    source_data_available = any(item.get("available") and item.get("text") for item in parsed)
    source_records_exist = bool(rows)
    missing_stored_files = [
        item for item in parsed
        if item.get("available") is False
    ]
    parse_failures = [
        item for item in parsed
        if item.get("parse_error")
    ]
    return {
        "engagement_id": engagement_id,
        "source_data_available": source_data_available,
        "source_records_exist": source_records_exist,
        "source_file_missing": bool(missing_stored_files),
        "source_parse_failed": bool(parse_failures),
        "inputs": parsed,
    }
