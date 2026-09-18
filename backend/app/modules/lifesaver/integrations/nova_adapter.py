"""Lifesaver-owned Nova orchestration adapter.

This module does not import Nova Core, does not write Nova tables, and
does not create Nova actions. It uses the local Lifesaver orchestrator only.
"""
from __future__ import annotations

import re

from app.modules.lifesaver.constants import AI_DISCLAIMER, PRODUCT_DISCLAIMER
from app.modules.lifesaver.ai_interface import orchestrate_reply

_CLINICAL_RE = re.compile(
    r"\b(diagnos\w*|treat\w*|prescription\w*|dose|dosage|should i (take|stop)|"
    r"stop taking|is this\b.*\b(cancer|dangerous)|heart attack|stroke|"
    r"blood pressure dangerous|emergency determination|life.?saving)\b",
    re.IGNORECASE,
)


def refuses_clinical(message: str) -> bool:
    return bool(_CLINICAL_RE.search(message or ""))


def _safe_refusal() -> dict:
    return {
        "reply": (
            "I cannot diagnose conditions, change medication, recommend treatment, "
            "or decide whether something is an emergency. If you need medical or "
            "emergency help, contact a licensed clinician or local emergency services. "
            "Lifesaver did not contact anyone."
        ),
        "mode": "safety_refusal",
        "disclaimer": AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def summarize_today(*, reminder_count: int, appointment_count: int, task_count: int) -> dict:
    return {
        "reply": (
            f"Today has {reminder_count} open reminder(s), {appointment_count} upcoming "
            f"appointment(s), and {task_count} open task(s). This is an organizational "
            f"summary, not a clinical assessment. {PRODUCT_DISCLAIMER}"
        ),
        "mode": "summarize_today",
        "disclaimer": AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def summarize_care_coordination(*, high: int, medium: int, low: int, needs_review: int) -> dict:
    return {
        "reply": (
            f"Care Coordination currently shows {high} high, {medium} medium, and {low} low "
            f"organizational items. {needs_review} item(s) need human review. "
            "Priorities are operational, not medical risk scores."
        ),
        "mode": "summarize_care_coordination",
        "disclaimer": AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def suggest_next_actions(*, pending_handoffs: int, open_alerts: int, transport_open: int) -> dict:
    actions = []
    if pending_handoffs:
        actions.append("review pending caregiver handoffs")
    if open_alerts:
        actions.append("acknowledge open Care Circle alerts")
    if transport_open:
        actions.append("review transportation coordination requests")
    if not actions:
        actions.append("review Today and confirm upcoming reminders")
    return {
        "reply": "Suggested next administrative actions: " + "; ".join(actions) + ".",
        "mode": "suggest_next_actions",
        "disclaimer": AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def explain_reminder(*, status: str, kind: str) -> dict:
    return {
        "reply": (
            f"This is a {kind} reminder with status {status}. I can help you find or "
            "acknowledge it. I cannot tell you whether to take, skip, or change medication."
        ),
        "mode": "explain_reminder",
        "disclaimer": AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def explain_transport_status(*, status: str) -> dict:
    return {
        "reply": (
            f"Transportation coordination status is {status}. This does not dispatch a ride "
            "and is not connected to Health ISF internals."
        ),
        "mode": "explain_transport_status",
        "disclaimer": AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def summarize_pending_handoffs(*, count: int) -> dict:
    return {
        "reply": f"There are {count} pending caregiver handoff(s) waiting for the intended recipient.",
        "mode": "summarize_pending_handoffs",
        "disclaimer": AI_DISCLAIMER,
        "uses_nova_engine": False,
        "writes_nova_tables": False,
    }


def ask(message: str, *, context: dict | None = None) -> dict:
    context = context or {}
    if refuses_clinical(message):
        return _safe_refusal()
    lowered = (message or "").lower()
    if "coordination" in lowered or "priority" in lowered:
        return summarize_care_coordination(
            high=int(context.get("high") or 0),
            medium=int(context.get("medium") or 0),
            low=int(context.get("low") or 0),
            needs_review=int(context.get("needs_review") or 0),
        )
    if "today" in lowered and "summar" in lowered:
        return summarize_today(
            reminder_count=int(context.get("reminder_count") or 0),
            appointment_count=int(context.get("appointment_count") or 0),
            task_count=int(context.get("task_count") or 0),
        )
    if "handoff" in lowered:
        return summarize_pending_handoffs(count=int(context.get("pending_handoffs") or 0))
    if "transport" in lowered:
        return explain_transport_status(status=str(context.get("transport_status") or "not_connected"))
    if "next" in lowered or "suggest" in lowered:
        return suggest_next_actions(
            pending_handoffs=int(context.get("pending_handoffs") or 0),
            open_alerts=int(context.get("open_alerts") or 0),
            transport_open=int(context.get("transport_open") or 0),
        )
    local = orchestrate_reply(
        message,
        reminder_count=int(context.get("reminder_count") or 0),
        consent_granted=int(context.get("consent_granted") or 0),
    )
    local["uses_nova_engine"] = False
    local["writes_nova_tables"] = False
    return local
