"""Fail-closed bookkeeping assignment router for staged Nova Work & Revenue integration.

This code does not authenticate callers or persist customer files: the future
HTTP and job layer MUST resolve ownership, contract permissions and storage.
No client data may be used until those release gates are proven in staging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bookkeeping_receivables import build_receivables_aging
from .bookkeeping_payables import build_payables_workpaper
from .bookkeeping_workpaper import build_bookkeeping_workpaper


SUPPORTED_WORK_TYPES = frozenset({"transaction_workpaper", "receivables_aging", "payables_aging"})
DISALLOWED = frozenset({
    "payroll", "tax_filing", "1099_filing", "general_ledger_posting",
    "payment_execution", "full_cycle_bookkeeping", "bank_reconciliation_final",
})


class AssignmentNotAuthorized(ValueError):
    pass


@dataclass(frozen=True)
class BookkeepingAssignment:
    organization_id: str
    owner_user_id: str
    engagement_id: str
    task_id: str
    work_type: str
    ai_assistance_permitted: bool
    data_processing_authorized: bool
    human_review_required: bool
    contracted_work_types: frozenset[str]


def authorize_assignment(assignment: BookkeepingAssignment) -> None:
    """Structured scope gate, avoiding fuzzy title/keyword authorization."""
    if not isinstance(assignment, BookkeepingAssignment):
        raise AssignmentNotAuthorized("Structured assignment required")
    identifiers = (
        assignment.organization_id, assignment.owner_user_id,
        assignment.engagement_id, assignment.task_id,
    )
    if any(not isinstance(x, str) or not x.strip() or len(x) > 120 for x in identifiers):
        raise AssignmentNotAuthorized("Complete scoped assignment identity required")
    if assignment.work_type not in SUPPORTED_WORK_TYPES:
        raise AssignmentNotAuthorized("Work type not implemented")
    if assignment.work_type not in assignment.contracted_work_types:
        raise AssignmentNotAuthorized("Contract does not authorize work type")
    if DISALLOWED.intersection(assignment.contracted_work_types):
        raise AssignmentNotAuthorized("Contract scope includes unsupported financial duties")
    if not all((
        assignment.ai_assistance_permitted is True,
        assignment.data_processing_authorized is True,
        assignment.human_review_required is True,
    )):
        raise AssignmentNotAuthorized("AI authorization, data consent and human review required")


def prepare_assignment_draft(
    assignment: BookkeepingAssignment, *,
    primary_csv: str, secondary_csv: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Prepare a human-only review result after checking structured permission.

    Caller must separately verify current active/unblocked engagement and task,
    authenticated tenancy, secure storage and idempotency. A returned draft is
    never a completed client job or proof of production readiness.
    """
    authorize_assignment(assignment)
    if not isinstance(primary_csv, str):
        raise AssignmentNotAuthorized("CSV text required")
    if assignment.work_type == "transaction_workpaper":
        if as_of is not None:
            raise AssignmentNotAuthorized("Unexpected as_of for transaction workpaper")
        draft = build_bookkeeping_workpaper(primary_csv, secondary_csv)
    elif assignment.work_type == "payables_aging":
        if secondary_csv is not None or not isinstance(as_of, str):
            raise AssignmentNotAuthorized("Payables requires as_of and one CSV")
        draft = build_payables_workpaper(primary_csv, as_of=as_of)
    elif assignment.work_type == "receivables_aging":
        if secondary_csv is not None or not isinstance(as_of, str):
            raise AssignmentNotAuthorized("Receivables requires as_of and one CSV")
        draft = build_receivables_aging(primary_csv, as_of=as_of)
    else:
        raise AssignmentNotAuthorized("Unrecognized work type")
    return {
        "organization_id": assignment.organization_id,
        "engagement_id": assignment.engagement_id,
        "task_id": assignment.task_id,
        "work_type": assignment.work_type,
        "status": "AWAITING_HUMAN_REVIEW",
        "delivery_allowed": False,
        "financial_execution": False,
        "draft": draft,
    }
