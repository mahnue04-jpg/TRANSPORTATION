"""Approved AMICOR marketplace digital deliverables.

The SHA-256 values pin the exact customer-ready PDFs approved during migration.
Binary files are intentionally not stored in GitHub. They must be uploaded through
the owner-only marketplace admin endpoint into AMICOR-controlled private storage.
"""
from __future__ import annotations

PRODUCT_FILES = {
    "ai-income-starter-kit": {
        "filename": "AI_Income_Starter_Kit_AMICOR.pdf",
        "sha256": "8c2a49d0c865d0570a4e31a64ed103da5244c3fce2fb2c87d9cc00050e591643",
        "bytes": 181212,
        "price_cents": 900,
        "access": "paid",
    },
    "ai-side-income-checklist": {
        "filename": "AI_Side_Income_Checklist_AMICOR.pdf",
        "sha256": "26be99103153ebebd24b1da6a4cc7d75dc5306b03ffb0e05ba3dc64200fa14b2",
        "bytes": 162137,
        "price_cents": 0,
        "access": "free",
    },
    "ai-prompt-library": {
        "filename": "AI_Prompt_Library_AMICOR.pdf",
        "sha256": "18a5ff5a6f96c10ac41997d93ba9883bd7975e3e7e45b95506aecf9711a9354d",
        "bytes": 159212,
        "price_cents": 1200,
        "access": "paid",
    },
    "ai-workflow-starter-kit": {
        "filename": "AI_Workflow_Starter_Kit_AMICOR.pdf",
        "sha256": "2fe22cb5c1595c935215090b9a65ad0aa8ec0b1743a60648d5eb2b5cab442573",
        "bytes": 184588,
        "price_cents": 1900,
        "access": "paid",
    },
    "ai-automation-blueprint": {
        "filename": "AI_Automation_Blueprint_AMICOR.pdf",
        "sha256": "cfdf521887dc3e9472cc2978478a5e9b4a92e622020a399853d63575d25ba490",
        "bytes": 16122,
        "price_cents": 2900,
        "access": "paid",
    },
}

BUNDLE = {
    "slug": "amicor-ai-starter-bundle",
    "price_cents": 4900,
    "products": [
        "ai-income-starter-kit",
        "ai-prompt-library",
        "ai-workflow-starter-kit",
        "ai-automation-blueprint",
    ],
    "bonus": "ai-side-income-checklist",
}
