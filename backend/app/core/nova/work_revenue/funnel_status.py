"""Owner-facing stage for one opportunity or application.

The label describes the record that is already stored. It never treats
approval, a draft, or a queue entry as an external send.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nova.work_revenue.funnel_status")

STAGE_DISCOVERY = "discovery"
STAGE_QUALIFICATION = "qualification"
STAGE_NOT_QUALIFIED = "not_qualified"
STAGE_SAVED_LEAD = "saved_lead"
STAGE_APPLICATION_DRAFT = "application_draft"
STAGE_OWNER_REVIEW = "owner_review"
STAGE_APPROVED_NOT_SENT = "approved_not_sent"
STAGE_EXTERNAL_SEND = "external_send"
STAGE_UNCONFIRMED = "unconfirmed"

LABEL_DISCOVERED = "Discovered. Not yet a saved lead."
LABEL_QUALIFIED_UNSAVED = "Qualified. Not saved yet."
LABEL_NEEDS_REVIEW_UNSAVED = "Qualification needs owner review. Not saved yet."
LABEL_NOT_QUALIFIED = "Not qualified. Closed."
LABEL_CLOSED = "Closed. Not sent."
LABEL_SAVED_PENDING = "Saved lead. Qualification pending. Not sent."
LABEL_SAVED_QUALIFIED = "Qualified saved lead. Not sent."
LABEL_DRAFT = "Application draft. Not sent."
LABEL_OWNER_REVIEW = "In the owner-review queue. Not sent."
LABEL_APPROVED = "Approved for future submission. Not sent."
LABEL_SENT = "Sent externally."
LABEL_UNCONFIRMED = "Stage not confirmed. Not sent."

FUNNEL_STAGE_LABELS = (
    LABEL_DISCOVERED,
    LABEL_QUALIFIED_UNSAVED,
    LABEL_NEEDS_REVIEW_UNSAVED,
    LABEL_NOT_QUALIFIED,
    LABEL_CLOSED,
    LABEL_SAVED_PENDING,
    LABEL_SAVED_QUALIFIED,
    LABEL_DRAFT,
    LABEL_OWNER_REVIEW,
    LABEL_APPROVED,
    LABEL_SENT,
    LABEL_UNCONFIRMED,
)


def _qual(record: dict[str, Any]) -> dict[str, Any]:
    nested = record.get("live_qualification") or record.get("qualification") or {}
    return nested if isinstance(nested, dict) else {}


def _status(record: dict[str, Any]) -> dict[str, Any]:
    stage = str(record.get("funnel_stage") or "")
    label = str(record.get("funnel_stage_label") or "")
    external_send = bool(record.get("external_send"))
    if not stage or not label:
        return {
            "funnel_stage": STAGE_UNCONFIRMED,
            "funnel_stage_label": LABEL_UNCONFIRMED,
            "external_send": False,
        }
    result = {
        "funnel_stage": stage,
        "funnel_stage_label": label,
        "external_send": external_send,
    }
    logger.info(
        "funnel_stage=%s external_send=%s",
        result["funnel_stage"],
        "true" if result["external_send"] else "false",
    )
    return result


def funnel_stage_status(record: dict[str, Any] | None) -> dict[str, Any]:
    """Return the single stage label for this record.

    External send is true only when a submission was actually recorded.
    """
    source = dict(record or {})
    qual = _qual(source)
    approval = str(source.get("approval_state") or "")
    application_state = str(source.get("application_state") or "")
    status = str(source.get("status") or "")
    outcome = str(
        source.get("qualification_outcome")
        or source.get("outcome")
        or qual.get("outcome")
        or qual.get("qualification_status")
        or source.get("qualification_status")
        or ""
    )
    eligibility = str(
        source.get("eligibility_decision")
        or qual.get("eligibility_decision")
        or ""
    )
    saved = bool(
        source.get("opportunity_id")
        or source.get("work_opportunity_id")
        or source.get("persisted") is True
    )
    sent = bool(
        source.get("externally_submitted")
        or source.get("manual_submission_recorded")
        or application_state == "submitted_externally_recorded"
    )
    if sent:
        return _status(
            {
                "funnel_stage": STAGE_EXTERNAL_SEND,
                "funnel_stage_label": LABEL_SENT,
                "external_send": True,
            }
        )

    approved = bool(
        source.get("approved_for_future_submission")
        or approval == "APPROVED"
        or application_state == "approved_for_future_submission"
    )
    if approved:
        return _status(
            {
                "funnel_stage": STAGE_APPROVED_NOT_SENT,
                "funnel_stage_label": LABEL_APPROVED,
                "external_send": False,
            },
        )

    if approval == "REJECTED" or status in {"REJECTED", "CLOSED"}:
        return _status(
            {
                "funnel_stage": STAGE_NOT_QUALIFIED,
                "funnel_stage_label": LABEL_CLOSED,
                "external_send": False,
            },
        )

    if approval == "READY_FOR_OWNER_REVIEW" or application_state == "READY_FOR_OWNER_REVIEW":
        return _status(
            {
                "funnel_stage": STAGE_OWNER_REVIEW,
                "funnel_stage_label": LABEL_OWNER_REVIEW,
                "external_send": False,
            },
        )

    if approval in {"DRAFT", "NEEDS_CHANGES"} or application_state in {"DRAFT", "NEEDS_CHANGES"} or status == "APPLICATION_PREPARED":
        return _status(
            {
                "funnel_stage": STAGE_APPLICATION_DRAFT,
                "funnel_stage_label": LABEL_DRAFT,
                "external_send": False,
            },
        )

    closed = (
        status == "NOT_QUALIFIED"
        or outcome in {"NOT_SUITABLE", "NOT_QUALIFIED", "PROHIBITED"}
        or str(source.get("qualification_status") or qual.get("qualification_status") or "") == "NOT_QUALIFIED"
        or str(source.get("discovery_band") or qual.get("discovery_band") or "") == "REJECT"
        or eligibility == "fail_closed"
    )
    if closed:
        return _status(
            {
                "funnel_stage": STAGE_NOT_QUALIFIED,
                "funnel_stage_label": LABEL_NOT_QUALIFIED,
                "external_send": False,
            },
        )

    qualified = status in {"QUALIFIED", "OWNER_REVIEW"} or outcome in {"NOVA_CAN_PERFORM", "QUALIFIED", "NOVA_WITH_OWNER_REVIEW"}
    if qualified and saved:
        return _status(
            {
                "funnel_stage": STAGE_SAVED_LEAD,
                "funnel_stage_label": LABEL_SAVED_QUALIFIED,
                "external_send": False,
            },
        )
    if qualified:
        return _status(
            {
                "funnel_stage": STAGE_QUALIFICATION,
                "funnel_stage_label": LABEL_QUALIFIED_UNSAVED,
                "external_send": False,
            },
        )

    live_status = str(source.get("qualification_status") or qual.get("qualification_status") or "")
    if not saved and live_status == "NEEDS_OWNER_REVIEW":
        return _status(
            {
                "funnel_stage": STAGE_QUALIFICATION,
                "funnel_stage_label": LABEL_NEEDS_REVIEW_UNSAVED,
                "external_send": False,
            },
        )

    if status == "DISCOVERED" and saved:
        return _status(
            {
                "funnel_stage": STAGE_SAVED_LEAD,
                "funnel_stage_label": LABEL_SAVED_PENDING,
                "external_send": False,
            },
        )
    if status == "DISCOVERED" or source.get("title") or source.get("opportunity_title"):
        return _status(
            {
                "funnel_stage": STAGE_DISCOVERY,
                "funnel_stage_label": LABEL_DISCOVERED,
                "external_send": False,
            },
        )
    return _status({})
