"""Owner-only synthetic website inquiry preview. No Cloudflare or CRM access.

This module is a staged user-interface contract only. Production KV reading and
historical lead matching require separate owner approval and backend design.
"""
from __future__ import annotations

from app.core.nova.growth_agent.flags import demo_mode_enabled


def synthetic_website_inquiry_preview() -> dict:
    if not demo_mode_enabled():
        return {
            "status": "unavailable",
            "reason": "synthetic_preview_disabled",
            "source": "synthetic_fixture_only",
            "inquiries": None,
            "count": None,
            "external_actions_performed": False,
            "production_kv_connected": False,
        }
    return {
        "status": "synthetic_preview",
        "source": "synthetic_fixture_only",
        "count": 1,
        "inquiries": [{
            "source_system": "amicor_cloudflare_kv",
            "source_key": "lead:AMQ-DEMO0001",
            "reference_id": "AMQ-DEMO0001",
            "received_at": "2026-11-14T21:00:00Z",
            "company": "Fictional Example Company",
            "name": "Synthetic QA Contact",
            "product": "Business Services",
            "status": "needs_owner_review",
            "is_synthetic": True,
        }],
        "external_actions_performed": False,
        "production_kv_connected": False,
    }
