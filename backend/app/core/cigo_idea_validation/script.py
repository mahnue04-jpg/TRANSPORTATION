"""Unrendered narration and the fictional worksheet it describes.

This module stores text only. It does not call a provider or create media.
"""
from __future__ import annotations

SCRIPT_ID = "cigo-consumer-idea-validation-script-v1"
SCRIPT_TEXT = (
    "This is a fictional consumer idea check. It is not a CIGO submission, "
    "and it is not a finished assessment video. "
    "The idea on this page is Lease Lens. It is a phone checklist for a first-time renter "
    "who wants to see add-on fees before signing a lease. "
    "The person in the worksheet is invented. The job is to compare the fees in one draft lease "
    "during a single sitting, without calling a lawyer. "
    "The riskiest assumption is that a renter will type those fees into a phone before signing, "
    "instead of skimming the lease and hoping the total is fine. "
    "The evidence card is invented too. Three fictional renters said they would try the checklist "
    "if it took under ten minutes and did not store the lease. That card is a worksheet example. "
    "It is not research and it is not a customer quote. "
    "The local result is reshape. The checklist still has to show that a renter will enter the fees. "
    "Nothing on this page creates a video, claims lip-sync, or marks the assessment ready."
)

WORKFLOW = (
    {"id": "consumer", "title": "Name the fictional consumer and the job to be done."},
    {"id": "idea", "title": "State the consumer idea in plain language."},
    {"id": "assumption", "title": "Name the riskiest assumption."},
    {"id": "evidence", "title": "Write an evidence card and mark it fictional."},
    {"id": "result", "title": "Choose a local worksheet result: continue, reshape, or pause."},
)

RESULTS = ("continue_locally", "reshape", "pause")

EXAMPLE = {
    "consumer": "Fictional first-time renter",
    "job": "Compare add-on fees in one draft lease during a single sitting, without calling a lawyer.",
    "idea": "Lease Lens, a phone checklist that lists add-on fees before a first-time renter signs.",
    "assumption": "A renter will type those fees into a phone before signing, instead of skimming the lease.",
    "evidence": "Three fictional renters said they would try the checklist if it took under ten minutes and did not store the lease.",
    "evidence_is_fictional": True,
    "result": "reshape",
    "consent": True,
}


def word_count(text: str) -> int:
    return len([part for part in text.split() if part])
