"""Synthetic inbound website sales assistant. No contracts, no invented prices."""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.growth.catalog import APPROVED_FAQ, APPROVED_SERVICES, UNAVAILABLE_FEATURES, profile_for_industry

ESCALATE_TOKENS = ("legal", "indemnify", "hipaa ba", "baa", "contract now", "sign this")
SENSITIVE = ("ssn", "social security", "credit card", "bank account")


def turn(session: dict[str, Any], message: str) -> dict[str, Any]:
    text = (message or "").strip()
    lower = text.lower()
    session.setdefault("history", [])
    session["history"].append({"role": "visitor", "text": text})
    if any(token in lower for token in SENSITIVE):
        reply = "Nova will not collect prohibited sensitive information. An owner can continue if appropriate."
        return _finish(session, reply, "HANDOFF", escalate=True, reason="sensitive_data")
    if any(token in lower for token in ESCALATE_TOKENS):
        reply = "That is a legal or contractual request. Nova cannot enter contracts or make legal promises. Handing off to the owner."
        return _finish(session, reply, "HANDOFF", escalate=True, reason="legal_commitment")
    if any(token in lower for token in UNAVAILABLE_FEATURES):
        reply = "That capability is not available. Nova will not claim unsupported features."
        return _finish(session, reply, "ESCALATE", escalate=True, reason="unsupported_feature")
    if "price" in lower or "discount" in lower or "how much" in lower:
        reply = APPROVED_FAQ["pricing"]
        return _finish(session, reply, "ESCALATE", escalate=True, reason="pricing", owner_action="OWNER_ACTION_REQUIRED")
    if session.get("state") in {None, "GREETING"}:
        session["state"] = "NEED"
        reply = (
            "Hello. I am the AMICOR Nova website assistant (synthetic). "
            "What kind of business need are you exploring: delivery, operations automation, or health transportation?"
        )
        return _finish(session, reply, "NEED")
    if "delivery" in lower or "pharmacy" in lower or "courier" in lower:
        session["product"] = "delivery"
        session["state"] = "QUALIFY"
        reply = APPROVED_FAQ["what is delivery"] + " I can collect company name and a contact placeholder next."
        return _finish(session, reply, "QUALIFY")
    if "nova" in lower or "automat" in lower or "admin" in lower or "ai" in lower:
        session["product"] = "nova"
        session["state"] = "TRIAL"
        reply = APPROVED_FAQ["what is nova"] + " " + APPROVED_FAQ["trial"]
        return _finish(session, reply, "TRIAL")
    if "transport" in lower or "health" in lower or "clinic ride" in lower:
        session["product"] = "health"
        session["state"] = "QUALIFY"
        reply = APPROVED_FAQ["what is health"]
        return _finish(session, reply, "QUALIFY")
    if "demo" in lower or "schedule" in lower:
        session["state"] = "DEMO"
        reply = "I can prepare a demo scheduling request. I need company, timezone, and a requested window. This does not write a live calendar."
        return _finish(session, reply, "DEMO", offer_demo=True)
    if "trial" in lower:
        reply = APPROVED_FAQ["trial"]
        return _finish(session, reply, session.get("state") or "TRIAL")
    if session.get("state") in {"QUALIFY", "TRIAL", "COLLECT"} and len(text) > 2:
        session["collected"] = session.get("collected") or {}
        if "inc" in lower or "llc" in lower or "pharmacy" in lower or "clinic" in lower:
            session["collected"]["organization_name"] = text
        session["state"] = "COLLECT"
        reply = "Recorded internally. I can qualify this as a synthetic lead and offer a demo if the owner approves."
        profile = profile_for_industry(text, session.get("product"))
        return _finish(session, reply, "COLLECT", profile=None if profile is None else profile["label"])
    reply = "I can help with approved AMICOR product questions, collect a lead placeholder, or hand off to the owner. I will not invent discounts or sign anything."
    return _finish(session, reply, session.get("state") or "GREETING")


def _finish(session: dict[str, Any], reply: str, state: str, **extra: Any) -> dict[str, Any]:
    session["state"] = state
    session["history"].append({"role": "nova", "text": reply})
    priced = [sid for sid, row in APPROVED_SERVICES.items() if row.get("price") is not None]
    return {
        "reply": reply,
        "state": state,
        "session": session,
        "live": False,
        "contract": False,
        "invented_price": False,
        "catalog_services_with_price": priced,
        **extra,
    }
