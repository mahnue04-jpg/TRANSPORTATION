"""Authorization adapter stub for customer ride intake.

Sprint A Day 1 scope:
- Normalize intake payload for future eligibility/authorization integrations.
- Return non-blocking advisory decision so existing flows remain operational.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AuthorizationDecision:
    status: str
    reason: str
    decision_source: str
    reviewed_at: datetime
    hard_block: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "decision_source": self.decision_source,
            "reviewed_at": self.reviewed_at.isoformat(),
            "hard_block": self.hard_block,
        }


def evaluate_customer_request_authorization(
    *,
    organization_id: str,
    rider_name: str,
    ride_type: str,
    scheduled_time: datetime | None,
    recurring: bool,
) -> AuthorizationDecision:
    """Return a non-blocking authorization advisory decision.

    This stub keeps transport workflow creation available while producing a
    stable contract for later external authorization policy engines.
    """
    reason = "Authorization adapter stub: pending provider review"
    if ride_type == "healthcare" and recurring:
        reason = "Authorization adapter stub: recurring healthcare trip flagged for provider review"
    elif scheduled_time is None:
        reason = "Authorization adapter stub: missing schedule defaults to pending review"

    return AuthorizationDecision(
        status="pending",
        reason=reason,
        decision_source="authorization_adapter_stub_v1",
        reviewed_at=datetime.now(timezone.utc),
        hard_block=False,
    )
