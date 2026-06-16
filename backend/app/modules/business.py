"""Business advisory capability module.

Delegates to app.business.handle_business_request which carries
a specialist OpenAI system prompt for small-business owners.
"""
from typing import Any

from app.business import handle_business_request

TRIGGERS = [
    "business", "startup", "start a", "start my", "checklist",
    "business plan", "business idea", "business ideas",
    "construction", "salon", "landscaping", "trucking", "transport",
    "production", "manufacturing",
    "pricing", "price my", "how much should i charge",
    "marketing", "advertise", "promote",
    "proposal", "client proposal", "quote for",
    "invoice", "invoicing",
    "hire", "hiring", "job description", "onboarding",
    "permit", "license", "llc", "sole proprietor", "incorporate",
    "operations", "workflow", "profit margin",
]


def handle(message: str, history: list[dict[str, Any]] | None = None, user_id: str = "default") -> str:
    return handle_business_request(message, history=history or [])
