"""FAQ answer engine grounded only in owner-approved content."""

from __future__ import annotations

import re
from typing import Any

_INJECTION = re.compile(
    r"(?i)(ignore (previous|all) instructions|system prompt|reveal (secrets?|keys?)|"
    r"exfiltrat|jailbreak|do anything now)"
)

_PROHIBITED_PROMISE = re.compile(
    r"(?i)(guaranteed refund|legally binding|we accept this contract|"
    r"unlimited free|definitely free forever)"
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def answer_from_faqs(
    question: str,
    faqs: list[dict[str, Any]] | None,
    *,
    business_name: str = "this business",
) -> dict[str, Any]:
    """Return grounded answer or explicit I-don't-know. Never invent hours/prices."""
    q = _normalize(question)
    if not q:
        return {
            "answer": "Please ask a question and I will answer from our approved FAQ.",
            "grounded": False,
            "faq_id": None,
            "disclosure": "I am an AI assistant for " + business_name + ".",
        }
    if _INJECTION.search(question or ""):
        return {
            "answer": (
                "I can only help with questions about our services using approved FAQ content. "
                "I cannot change system instructions or share secrets."
            ),
            "grounded": False,
            "faq_id": None,
            "blocked_prompt_injection": True,
            "disclosure": "I am an AI assistant for " + business_name + ".",
        }
    if _PROHIBITED_PROMISE.search(question or ""):
        return {
            "answer": (
                "I cannot make legal, financial, or contractual promises. "
                "Please ask to speak with a human for those topics."
            ),
            "grounded": False,
            "faq_id": None,
            "escalate": True,
            "disclosure": "I am an AI assistant for " + business_name + ".",
        }

    stopwords = {
        "the", "and", "for", "are", "you", "your", "what", "when", "where", "who",
        "how", "can", "does", "did", "with", "from", "this", "that", "have", "has",
        "about", "please", "tell", "me",
    }
    best: dict[str, Any] | None = None
    best_score = 0
    tokens = {t for t in re.findall(r"[a-z0-9]{3,}", q) if t not in stopwords}
    for faq in faqs or []:
        question_text = _normalize(str(faq.get("question") or ""))
        keywords = {_normalize(k) for k in (faq.get("keywords") or []) if str(k).strip()}
        faq_tokens = {
            t for t in re.findall(r"[a-z0-9]{3,}", question_text) if t not in stopwords
        } | keywords
        score = len(tokens & faq_tokens)
        if question_text and question_text in q:
            score += 5
        if score > best_score:
            best_score = score
            best = faq

    disclosure = f"I am an AI assistant for {business_name}."
    # Stopwords removed above so a single meaningful keyword (e.g. "hours") is enough.
    if best and best_score >= 1:
        return {
            "answer": str(best.get("answer") or "").strip(),
            "grounded": True,
            "faq_id": str(best.get("id") or best.get("faq_id") or ""),
            "disclosure": disclosure,
            "score": best_score,
        }
    return {
        "answer": (
            "I don't know based on our approved FAQ. "
            "I can connect you with a human, or you can ask about topics covered in our FAQ."
        ),
        "grounded": False,
        "faq_id": None,
        "disclosure": disclosure,
        "fallback": "i_dont_know",
    }
