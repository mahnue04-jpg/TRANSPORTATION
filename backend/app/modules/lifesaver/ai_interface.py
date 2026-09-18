"""Lifesaver AI conversation/orchestration interface.

This is a local, non-clinical orchestration layer. It does not import or
modify Nova internals. A future HTTP client to existing /api/nova routes
can be added later without coupling this product to Nova modules.
"""
from __future__ import annotations

import re

from app.modules.lifesaver.constants import AI_DISCLAIMER, PRODUCT_DISCLAIMER

_DIAGNOSIS_RE = re.compile(
    r"\b(diagnos\w*|treat\w*|prescription\w*|dose|dosage|should i take|"
    r"is this cancer|heart attack|stroke|emergency detection|life.?saving)\b",
    re.IGNORECASE,
)


def orchestrate_reply(message: str, *, reminder_count: int, consent_granted: int) -> dict[str, str]:
    text = (message or "").strip()
    if _DIAGNOSIS_RE.search(text):
        reply = (
            "I cannot diagnose conditions or recommend treatment. "
            "Please contact a licensed clinician for medical questions. "
            + AI_DISCLAIMER
        )
        return {
            "reply": reply,
            "mode": "safety_refusal",
            "disclaimer": AI_DISCLAIMER,
        }

    lowered = text.lower()
    if any(word in lowered for word in ("medication", "reminder", "pill")):
        reply = (
            f"You currently have {reminder_count} open reminder(s) in Lifesaver. "
            "Open Medications or Reminders to review or acknowledge them. "
            "I cannot tell you what to take or change."
        )
        mode = "reminder_navigation"
    elif any(word in lowered for word in ("appointment", "calendar", "schedule")):
        reply = "Use Appointments to add or review visits you entered. I can help you find that screen, not book clinical care."
        mode = "appointment_navigation"
    elif any(word in lowered for word in ("caregiver", "care circle", "family", "handoff")):
        reply = "Care Circle lets you invite authorized people and set permissions. Sharing stays off until you grant caregiver-sharing consent."
        mode = "care_circle_navigation"
    elif any(word in lowered for word in ("transport", "ride", "trip")):
        reply = (
            "Transportation is a connection/status interface only. "
            "It does not dispatch rides by itself and is not linked to production ride internals in V1."
        )
        mode = "transport_navigation"
    elif any(word in lowered for word in ("sos", "emergency", "911")):
        reply = (
            "The SOS screen is a demonstration workflow and does not contact emergency services. "
            "If you need help now, use local emergency services directly."
        )
        mode = "sos_safety"
    else:
        reply = (
            f"I can help you navigate Lifesaver. You have granted {consent_granted} consent(s). "
            "Try asking about reminders, appointments, Care Circle, or privacy. "
            + PRODUCT_DISCLAIMER
        )
        mode = "general_support"

    return {
        "reply": reply,
        "mode": mode,
        "disclaimer": AI_DISCLAIMER,
    }
