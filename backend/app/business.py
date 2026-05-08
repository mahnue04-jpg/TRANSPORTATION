"""
business.py — Business advisory module for Amicor.

Detects business-related intent and routes to OpenAI with a
specialist system prompt so responses are grounded, practical,
and tailored to small-business owners.
"""

import os
from openai import OpenAI

_client = None

SYSTEM_PROMPT = """You are Amicor, an expert small-business advisor. You help entrepreneurs
and business owners with:

- Business ideas and feasibility analysis
- Step-by-step business plans (executive summary, market analysis, financials, operations)
- Startup checklists for industries: construction, salons, landscaping, trucking/transport, production/manufacturing, retail, food service
- Pricing strategies and profit margin calculations
- Marketing plans, social media strategies, and client acquisition
- Writing client proposals and quotes
- Creating professional invoice templates
- Operations and workflow optimization
- Hiring guides: job descriptions, interview questions, onboarding
- Permits, licenses, and legal structure guidance (LLC, sole proprietor, etc.)

Always give concrete, actionable advice. Use bullet points and numbered lists for
clarity. When asked about a specific industry, tailor the advice to that industry.
If financial figures are needed, provide realistic ballpark ranges. Remind users
to consult a licensed attorney or accountant for legal/tax matters when appropriate."""


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def handle_business_request(message: str, history: list = None) -> str:
    """Route a business-related message to OpenAI with the business system prompt."""
    client = get_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Business advisor error: {str(e)}"
