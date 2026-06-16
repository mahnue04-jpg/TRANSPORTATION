"""Email drafting capability module."""

import re
from typing import Any

from app.database import get_email_draft, save_email_draft

TRIGGERS = [
    "email",
    "draft an email",
    "write an email",
    "compose an email",
    "subject line",
    "follow up email",
    "send this email",
]

_TONES = {
    "formal": "formal",
    "friendly": "friendly",
    "concise": "concise",
    "urgent": "urgent",
    "apologetic": "apologetic",
}


def _detect_tone(message: str) -> str:
    lower = message.lower()
    for token, tone in _TONES.items():
        if token in lower:
            return tone
    return "professional"


def _extract_recipient(message: str) -> str:
    match = re.search(r"to ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*)", message)
    if match:
        return match.group(1)
    return "there"


def _extract_goal(message: str) -> str:
    cleaned = re.sub(r"\b(write|draft|compose|send)\b", "", message, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(email|subject line)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "follow up on the conversation"


def _subject_from_goal(goal: str) -> str:
    subject = goal[:1].upper() + goal[1:] if goal else "Quick follow-up"
    if len(subject) > 72:
        subject = subject[:69].rstrip() + "..."
    return subject


TONE_GUIDANCE = {
    "formal": "Keep the language polished and direct.",
    "friendly": "Sound warm, approachable, and positive.",
    "concise": "Keep it brief while preserving the key ask.",
    "urgent": "Make the time sensitivity clear without sounding aggressive.",
    "apologetic": "Lead with accountability and a repair-oriented tone.",
    "professional": "Keep it clear, respectful, and business-ready.",
}


def _compose_body(recipient: str, goal: str, tone: str) -> str:
    return (
        f"Hi {recipient},\n\n"
        f"I wanted to reach out regarding {goal}. "
        f"{TONE_GUIDANCE.get(tone, TONE_GUIDANCE['professional'])} "
        "Please let me know if you have any questions or if there is a convenient time to discuss next steps.\n\n"
        "Best,\n"
        "[Your Name]"
    )


def handle(message: str, history: list[dict[str, Any]] | None = None, user_id: str = "default") -> dict:
    lower = message.lower()
    if "send this email" in lower or lower.strip().startswith("send email"):
        draft = get_email_draft(user_id)
        if not draft:
            return {
                "response": "There is no saved draft yet. Ask me to draft an email first.",
                "sources": [],
                "status": "error",
                "meta": {"action": "send-simulated"},
            }
        save_email_draft(user_id, draft["subject"], draft["body"], draft["tone"], "simulated-send")
        return {
            "response": (
                "Send simulation complete. I did not send a real email, but the current draft is marked ready to review.\n\n"
                f"Subject: {draft['subject']}\n\n{draft['body']}"
            ),
            "sources": [],
            "status": "success",
            "meta": {"action": "send-simulated", "draft_status": "simulated-send"},
        }

    tone = _detect_tone(message)
    recipient = _extract_recipient(message)
    goal = _extract_goal(message)
    subject = _subject_from_goal(goal)
    body = _compose_body(recipient, goal, tone)
    save_email_draft(user_id, subject, body, tone, "drafted")

    return {
        "response": (
            "Email draft ready.\n\n"
            f"Subject: {subject}\n\n"
            f"{body}\n\n"
            f"Tone: {tone}\n"
            "You can ask me to revise the tone, shorten it, or simulate sending it."
        ),
        "sources": [],
        "status": "success",
        "meta": {
            "draft": {
                "subject": subject,
                "body": body,
                "tone": tone,
                "status": "drafted",
            }
        },
    }
