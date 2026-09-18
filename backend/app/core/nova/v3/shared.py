"""Shared V2 primitives reused by V3. Do not fork a second isolation/idempotency stack."""
from __future__ import annotations

from app.core.nova.work_revenue.v2_freeze import FROZEN_ENGAGEMENT, FROZEN_OPPORTUNITY, FROZEN_REVENUE
from app.core.nova.work_revenue.v2_idempotency import (
    WEBHOOK_REUSE_CONTRACT,
    lookup_canonical,
    redact_secrets,
    replay_without_mutation,
    secrets_rejected,
)

__all__ = [
    "FROZEN_ENGAGEMENT",
    "FROZEN_OPPORTUNITY",
    "FROZEN_REVENUE",
    "WEBHOOK_REUSE_CONTRACT",
    "lookup_canonical",
    "redact_secrets",
    "replay_without_mutation",
    "secrets_rejected",
]
