"""Controlled executor for owner-started Nova Work & Revenue engagements."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue import managed, ops, work_inputs
from app.core.nova.work_revenue.models import NovaWorkDeliverable, NovaWorkTask
from app.core.nova.work_revenue.schemas import DeliverableCreate, DeliverableUpdate, EngagementUpdate, TaskUpdate
from app.core.nova.work_revenue.service import (
    NovaWorkError,
    _record_audit,
    get_engagement,
    get_opportunity,
)

_SOURCE_DATA_TASK_TERMS = (
    "source data",
    "missing, duplicate",
    "invalid values",
    "clean and normalize",
    "calculations and transformations",
    "spreadsheet/report structure",
    "validate totals",
    "sample records",
)
_OUTLINE_TITLE = "Prepare internal work outline"
_OUTLINE_MARKER = "AUTONOMOUS_EXECUTOR_OUTLINE_V1"
_SOURCE_PROFILE_MARKER = "AUTONOMOUS_SOURCE_PROFILE_V1"
_TRANSFORM_REPORT_MARKER = "AUTONOMOUS_TRANSFORM_REPORT_V1"
_TRANSFORM_DATA_MARKER = "AUTONOMOUS_TRANSFORM_DATA_V1"


def _is_source_data_task(title: str) -> bool:
    value = str(title or "").strip().lower()
    return any(term in value for term in _SOURCE_DATA_TASK_TERMS)


def run_autonomous_engagement(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    engagement = get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    if str(engagement.get("source") or "") != "nova_autonomous":
        raise NovaWorkError("Autonomous executor is limited to Nova autonomous engagements", status_code=409)

    if str(engagement.get("status") or "") in {"ARCHIVED", "CLOSED", "CANCELLED", "COMPLETE"}:
        raise NovaWorkError("This engagement is not open for autonomous execution", status_code=409)

    if engagement.get("status") != "ACTIVE":
        managed.update_engagement(
            db,
            engagement_id,
            EngagementUpdate(status="ACTIVE"),
            organization_id=organization_id,
            user=user,
        )

    opportunity_id = engagement.get("opportunity_id")
    opportunity = (
        get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
        if opportunity_id
        else None
    )

    advanced: list[str] = []
    blocked: list[str] = []
    unblocked: list[str] = []
    deliverable_id: str | None = None
    source_profile_deliverable_id: str | None = None
    source_inspection = work_inputs.inspect_work_inputs(
        db,
        engagement_id,
        organization_id=organization_id,
        user=user,
    )
    source_data_available = bool(source_inspection.get("source_data_available"))
    source_inputs = list(source_inspection.get("inputs") or [])

    outline_task = (
        db.query(NovaWorkTask)
        .filter(
            NovaWorkTask.organization_id == organization_id,
            NovaWorkTask.engagement_id == engagement_id,
            NovaWorkTask.classification == "NOVA",
            NovaWorkTask.title == _OUTLINE_TITLE,
        )
        .first()
    )
    if outline_task is not None and outline_task.status in {"NOT_STARTED", "READY"}:
        ops.update_task(
            db,
            outline_task.task_id,
            TaskUpdate(status="IN_PROGRESS"),
            organization_id=organization_id,
            user=user,
        )
        existing_outline = (
            db.query(NovaWorkDeliverable)
            .filter(
                NovaWorkDeliverable.organization_id == organization_id,
                NovaWorkDeliverable.engagement_id == engagement_id,
                NovaWorkDeliverable.notes == _OUTLINE_MARKER,
            )
            .first()
        )
        if existing_outline is None:
            title = getattr(opportunity, "opportunity_title", None) or engagement.get("service") or "Internal work"
            description = getattr(opportunity, "description", None) or "No additional opportunity description was stored."
            deliverable = ops.create_deliverable(
                db,
                DeliverableCreate(
                    engagement_id=engagement_id,
                    deliverable_type="DOCUMENT",
                    description=(
                        f"Internal autonomous work outline for {title}. "
                        f"Scope basis: {description[:2500]} "
                        "This outline is derived only from stored opportunity scope. "
                        "No client/source dataset has been analyzed."
                    ),
                    notes=_OUTLINE_MARKER,
                ),
                organization_id=organization_id,
                user=user,
            )
            deliverable = ops.update_deliverable(
                db,
                deliverable.deliverable_id,
                DeliverableUpdate(review_status="READY_FOR_REVIEW"),
                organization_id=organization_id,
                user=user,
            )
            deliverable_id = deliverable.deliverable_id
        else:
            deliverable_id = existing_outline.deliverable_id
        ops.update_task(
            db,
            outline_task.task_id,
            TaskUpdate(
                status="OWNER_REVIEW",
                owner_notes="Internal work outline generated from stored opportunity scope. Owner review required before any external use.",
            ),
            organization_id=organization_id,
            user=user,
        )
        advanced.append(outline_task.task_id)

    if source_data_available:
        previously_blocked = (
            db.query(NovaWorkTask)
            .filter(
                NovaWorkTask.organization_id == organization_id,
                NovaWorkTask.engagement_id == engagement_id,
                NovaWorkTask.classification == "NOVA",
                NovaWorkTask.status == "BLOCKED",
            )
            .all()
        )
        for task in previously_blocked:
            if not _is_source_data_task(task.title):
                continue
            ops.update_task(
                db,
                task.task_id,
                TaskUpdate(
                    status="READY",
                    blocked_reason=None,
                    owner_notes="Source data is attached and parseable. Task reactivated for controlled Nova work.",
                ),
                organization_id=organization_id,
                user=user,
            )
            unblocked.append(task.task_id)

        profile_task = (
            db.query(NovaWorkTask)
            .filter(
                NovaWorkTask.organization_id == organization_id,
                NovaWorkTask.engagement_id == engagement_id,
                NovaWorkTask.classification == "NOVA",
                NovaWorkTask.title.ilike("%profile the source data%"),
                NovaWorkTask.status == "READY",
            )
            .first()
        )
        if profile_task is not None:
            ops.update_task(
                db,
                profile_task.task_id,
                TaskUpdate(status="IN_PROGRESS"),
                organization_id=organization_id,
                user=user,
            )
            profile_lines: list[str] = []
            for item in source_inputs:
                diagnostics = item.get("diagnostics") or {}
                line = (
                    f"{item.get('filename')}: parser={diagnostics.get('parser') or 'unknown'}"
                    f", rows={diagnostics.get('rows_detected', diagnostics.get('preview_rows', 'n/a'))}"
                    f", columns={diagnostics.get('columns_detected', 'n/a')}"
                    f", blank_cells_preview={diagnostics.get('blank_cells_in_preview', 'n/a')}"
                    f", duplicate_rows_preview={diagnostics.get('duplicate_rows_in_preview', 'n/a')}"
                )
                if item.get("parse_error"):
                    line += f", parse_error={item.get('parse_error')}"
                profile_lines.append(line)
            existing_profile = (
                db.query(NovaWorkDeliverable)
                .filter(
                    NovaWorkDeliverable.organization_id == organization_id,
                    NovaWorkDeliverable.engagement_id == engagement_id,
                    NovaWorkDeliverable.notes == _SOURCE_PROFILE_MARKER,
                )
                .first()
            )
            if existing_profile is None:
                profile_deliverable = ops.create_deliverable(
                    db,
                    DeliverableCreate(
                        engagement_id=engagement_id,
                        deliverable_type="ANALYSIS",
                        description=(
                            "Source Data Intake Analysis. "
                            + " ".join(profile_lines)
                            + " This analysis reflects uploaded source files only. "
                            "No external transmission occurred. Transformation and report-building tasks remain separately controlled."
                        )[:12000],
                        notes=_SOURCE_PROFILE_MARKER,
                    ),
                    organization_id=organization_id,
                    user=user,
                )
                profile_deliverable = ops.update_deliverable(
                    db,
                    profile_deliverable.deliverable_id,
                    DeliverableUpdate(review_status="READY_FOR_REVIEW"),
                    organization_id=organization_id,
                    user=user,
                )
                source_profile_deliverable_id = profile_deliverable.deliverable_id
            else:
                source_profile_deliverable_id = existing_profile.deliverable_id
            ops.update_task(
                db,
                profile_task.task_id,
                TaskUpdate(
                    status="OWNER_REVIEW",
                    owner_notes="Source data profile created from the attached work input. Owner review required.",
                ),
                organization_id=organization_id,
                user=user,
            )
            advanced.append(profile_task.task_id)

    transformation_report_id: str | None = None
    transformation_data_id: str | None = None
    generated_output_id: str | None = None

    transform_ready = (
        db.query(NovaWorkTask)
        .filter(
            NovaWorkTask.organization_id == organization_id,
            NovaWorkTask.engagement_id == engagement_id,
            NovaWorkTask.classification == "NOVA",
            NovaWorkTask.status == "READY",
        )
        .all()
    )
    transform_tasks = [
        task for task in transform_ready
        if any(
            term in str(task.title or "").lower()
            for term in (
                "identify missing, duplicate",
                "clean and normalize data",
                "calculations and transformations",
                "spreadsheet/report structure",
                "validate totals and sample records",
            )
        )
    ]
    if source_data_available and transform_tasks:
        source_rows = (
            db.query(work_inputs.NovaWorkInput)
            .filter(
                work_inputs.NovaWorkInput.organization_id == organization_id,
                work_inputs.NovaWorkInput.engagement_id == engagement_id,
                work_inputs.NovaWorkInput.input_kind == "SOURCE_DATA",
                work_inputs.NovaWorkInput.is_active.is_(True),
                work_inputs.NovaWorkInput.status == "AVAILABLE",
            )
            .order_by(work_inputs.NovaWorkInput.created_at.asc())
            .all()
        )
        tabular_source = next(
            (row for row in source_rows if str(row.original_filename).lower().endswith((".csv", ".xlsx"))),
            None,
        )
        if tabular_source is not None:
            existing_report = (
                db.query(NovaWorkDeliverable)
                .filter(
                    NovaWorkDeliverable.organization_id == organization_id,
                    NovaWorkDeliverable.engagement_id == engagement_id,
                    NovaWorkDeliverable.notes.like(f"{_TRANSFORM_REPORT_MARKER}%"),
                )
                .first()
            )
            if existing_report is None:
                result = work_inputs.process_tabular_source(tabular_source)
                validation = dict(result["validation"])
                stem = tabular_source.original_filename.rsplit(".", 1)[0]
                output_name = f"{stem}_nova_cleaned.csv"
                generated = work_inputs.create_generated_output(
                    db,
                    engagement_id,
                    organization_id=organization_id,
                    user=user,
                    filename=output_name,
                    content_type="text/csv",
                    content=result["content"],
                    notes=_TRANSFORM_DATA_MARKER,
                )
                generated_output_id = generated["input_id"]

                report_description = (
                    "Nova Tabular Transformation & QA Report. "
                    f"Source: {validation['source_filename']}. "
                    f"Rows before cleaning: {validation['source_data_rows']}. "
                    f"Columns: {validation['columns']}. "
                    f"Exact duplicate rows removed: {validation['duplicate_rows_removed']}. "
                    f"Rows after cleaning: {validation['cleaned_data_rows']}. "
                    f"Blank cells retained without imputation: {validation['blank_cells_retained']}. "
                    f"Inconsistent-width rows normalized: {validation['inconsistent_width_rows']}. "
                    f"Row reconciliation passed: {validation['row_count_reconciles']}. "
                    f"Column reconciliation passed: {validation['column_count_reconciles']}. "
                    "Missing values were not invented or imputed. "
                    "No domain-specific formulas were applied because none were provided in the engagement scope. "
                    f"Generated internal output: {output_name} ({generated_output_id}). "
                    "Owner review is required before external use."
                )
                report = ops.create_deliverable(
                    db,
                    DeliverableCreate(
                        engagement_id=engagement_id,
                        deliverable_type="REPORT",
                        description=report_description[:12000],
                        notes=f"{_TRANSFORM_REPORT_MARKER}:{generated_output_id}",
                    ),
                    organization_id=organization_id,
                    user=user,
                )
                report = ops.update_deliverable(
                    db,
                    report.deliverable_id,
                    DeliverableUpdate(review_status="READY_FOR_REVIEW"),
                    organization_id=organization_id,
                    user=user,
                )
                transformation_report_id = report.deliverable_id

                data_deliverable = ops.create_deliverable(
                    db,
                    DeliverableCreate(
                        engagement_id=engagement_id,
                        deliverable_type="DATA_FILE",
                        description=(
                            f"Cleaned internal data file {output_name}. "
                            f"Generated output id {generated_output_id}. "
                            "Exact duplicates removed; whitespace normalized; missing values preserved. "
                            "Not transmitted externally."
                        ),
                        notes=f"{_TRANSFORM_DATA_MARKER}:{generated_output_id}",
                    ),
                    organization_id=organization_id,
                    user=user,
                )
                data_deliverable = ops.update_deliverable(
                    db,
                    data_deliverable.deliverable_id,
                    DeliverableUpdate(review_status="READY_FOR_REVIEW"),
                    organization_id=organization_id,
                    user=user,
                )
                transformation_data_id = data_deliverable.deliverable_id

                if not validation.get("validated"):
                    raise NovaWorkError("Generated tabular output failed reconciliation validation", status_code=409)

                for task in transform_tasks:
                    ops.update_task(
                        db,
                        task.task_id,
                        TaskUpdate(status="IN_PROGRESS"),
                        organization_id=organization_id,
                        user=user,
                    )
                    note = (
                        f"Nova completed safe tabular processing using {tabular_source.original_filename}; "
                        f"generated {output_name}; exact duplicates removed={validation['duplicate_rows_removed']}; "
                        f"blank cells retained={validation['blank_cells_retained']}; "
                        "owner review required before external use."
                    )
                    ops.update_task(
                        db,
                        task.task_id,
                        TaskUpdate(status="OWNER_REVIEW", owner_notes=note),
                        organization_id=organization_id,
                        user=user,
                    )
                    advanced.append(task.task_id)
            else:
                transformation_report_id = existing_report.deliverable_id
                notes = str(existing_report.notes or "")
                if ":" in notes:
                    generated_output_id = notes.split(":", 1)[1] or None
                existing_data = (
                    db.query(NovaWorkDeliverable)
                    .filter(
                        NovaWorkDeliverable.organization_id == organization_id,
                        NovaWorkDeliverable.engagement_id == engagement_id,
                        NovaWorkDeliverable.notes.like(f"{_TRANSFORM_DATA_MARKER}%"),
                    )
                    .first()
                )
                if existing_data is not None:
                    transformation_data_id = existing_data.deliverable_id
        else:
            for task in transform_tasks:
                reason = (
                    "TABULAR SOURCE REQUIRED: this transformation phase currently supports CSV or XLSX source data. "
                    "The attached source input is not a supported tabular file for this executor."
                )
                ops.update_task(
                    db,
                    task.task_id,
                    TaskUpdate(status="BLOCKED", blocked_reason=reason, owner_notes=reason),
                    organization_id=organization_id,
                    user=user,
                )
                blocked.append(task.task_id)

    ready_tasks = (
        db.query(NovaWorkTask)
        .filter(
            NovaWorkTask.organization_id == organization_id,
            NovaWorkTask.engagement_id == engagement_id,
            NovaWorkTask.classification == "NOVA",
            NovaWorkTask.status == "READY",
        )
        .all()
    )
    for task in ready_tasks:
        if not _is_source_data_task(task.title):
            continue
        if source_data_available:
            continue
        input_present = bool(source_inputs)
        reason = (
            "SOURCE DATA PARSE REQUIRED: a source file is attached but Nova could not parse usable content. "
            "Replace the file with a supported readable source file."
            if input_present
            else
            "SOURCE DATA REQUIRED: this task depends on the client/source dataset. "
            "No engagement-level source dataset is available, so Nova did not invent or analyze data."
        )
        ops.update_task(
            db,
            task.task_id,
            TaskUpdate(status="BLOCKED", blocked_reason=reason, owner_notes=reason),
            organization_id=organization_id,
            user=user,
        )
        blocked.append(task.task_id)

    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="AUTONOMOUS_EXECUTOR_RUN",
        summary=(
            f"Nova internal executor ran: {len(advanced)} task(s) advanced; "
            f"{len(unblocked)} task(s) reactivated; {len(blocked)} task(s) blocked. "
            f"Source data available={source_data_available}. No external action."
        ),
        ref_id=engagement_id,
        entity_type="engagement",
        actor_category="NOVA",
        new_state="ACTIVE",
    )
    db.commit()

    return {
        "status": "AUTONOMOUS_EXECUTOR_RAN",
        "engagement_id": engagement_id,
        "engagement_status": "ACTIVE",
        "tasks_advanced": len(advanced),
        "tasks_blocked": len(blocked),
        "tasks_unblocked": len(unblocked),
        "advanced_task_ids": advanced,
        "blocked_task_ids": blocked,
        "unblocked_task_ids": unblocked,
        "deliverable_id": deliverable_id,
        "source_profile_deliverable_id": source_profile_deliverable_id,
        "transformation_report_deliverable_id": transformation_report_id,
        "transformation_data_deliverable_id": transformation_data_id,
        "generated_output_id": generated_output_id,
        "owner_review_required": True,
        "source_data_available": source_data_available,
        "source_data_input_count": len(source_inputs),
        "source_data_required": not source_data_available,
        "external_submission": False,
        "client_contact": False,
        "contract_acceptance": False,
        "financial_execution": False,
    }
