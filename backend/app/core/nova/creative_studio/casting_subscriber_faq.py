"""Fictional Harborlight subscriber FAQ.

Answers come from a fixed list. Billing, passwords, and account credentials are
not stored. Unlisted questions wait for a person. Nothing here sends a message.
"""
from __future__ import annotations

import re

_CARD_RUN = re.compile(r"\d(?:[ -]?\d){11,}")
_SECRET_WORDS = (
    "password",
    "passcode",
    "cvv",
    "cvc",
    "card number",
    "credit card",
    "debit card",
    "routing number",
    "account number",
    "social security",
    "api key",
    "secret key",
    "billing",
    "invoice",
    "login credential",
)
_CATALOG = (
    {
        "id": "support-hours",
        "needles": ("what are your hours", "are you open", "24/7", "24-7"),
        "answer": (
            "This is a fictional Harborlight subscriber demo. The saved answers are "
            "available whenever the sandbox is open. A person still has to take any "
            "question that is not on this list."
        ),
    },
    {
        "id": "callback-window",
        "needles": ("callback", "call time", "what time"),
        "answer": (
            "The fictional Harborlight callback is the time on the sandbox call sheet. "
            "A person confirms a schedule change before an applicant is expected to use it."
        ),
    },
    {
        "id": "self-tape",
        "needles": ("self-tape", "self tape", "how long"),
        "answer": "The fictional Harborlight role asks for a two-minute self-tape from an adult.",
    },
    {
        "id": "consent",
        "needles": ("revoke", "consent", "unsubscribe", "stop"),
        "answer": (
            "Revoke consent in the signed-in sandbox. That clears the test contact "
            "details and audition link from review. This demo does not email or text a confirmation."
        ),
    },
    {
        "id": "messages",
        "needles": ("did you email", "did you text", "was a message sent", "messages sent"),
        "answer": "No message is sent from this demo. Drafts stay unsent until a person uses a permitted channel.",
    },
    {
        "id": "age",
        "needles": ("minimum age", "how old", "under 18", "minors"),
        "answer": "The sandbox accepts adults only. It does not collect a minor's application.",
    },
)
_CREDENTIAL_ANSWER = (
    "Billing details, passwords, and account credentials are not collected here. "
    "A person has the question. Nothing was charged, emailed, or texted."
)
_UNKNOWN_ANSWER = (
    "This demo does not guess. A person will review the question. Nothing was sent."
)
_TICKET_ANSWER = (
    "There is no ticket cart and no merchandise checkout in this demo. "
    "A person reviews that question. Nothing was purchased."
)


def redact_subscriber_question(question: str) -> str:
    cleaned = " ".join(str(question or "").split())
    cleaned = _CARD_RUN.sub("[redacted]", cleaned)
    return cleaned[:500]


def classify_subscriber_question(question: str) -> dict:
    cleaned = redact_subscriber_question(question)
    lowered = cleaned.lower()
    if not cleaned:
        return {
            "topic": "empty",
            "answer": "",
            "status": "rejected",
            "human_required": False,
        }
    if "[redacted]" in cleaned or any(word in lowered for word in _SECRET_WORDS):
        return {
            "topic": "credentials",
            "answer": _CREDENTIAL_ANSWER,
            "status": "waiting_for_person",
            "human_required": True,
        }
    if any(word in lowered for word in ("ticket", "merchandise", "merch", "buy a shirt")):
        return {
            "topic": "ticket-inquiry",
            "answer": _TICKET_ANSWER,
            "status": "waiting_for_person",
            "human_required": True,
        }
    for item in _CATALOG:
        if any(needle in lowered for needle in item["needles"]):
            return {
                "topic": item["id"],
                "answer": item["answer"],
                "status": "answered",
                "human_required": False,
            }
    return {
        "topic": "unlisted",
        "answer": _UNKNOWN_ANSWER,
        "status": "waiting_for_person",
        "human_required": True,
    }
