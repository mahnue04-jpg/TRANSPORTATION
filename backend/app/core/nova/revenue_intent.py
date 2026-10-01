"""Route explicit discovery requests through the existing owner-only workflow."""
from __future__ import annotations

from sqlalchemy.orm import Session
from app.auth import UserContext


def route_revenue_request(db: Session, question: str, *, organization_id: str, user: UserContext):
    # Lazy imports keep module initialization independent of Today and its adapters.
    from app.core.nova.today import service as today
    from app.core.nova.today.schemas import NovaTodayBrainRequest
    from app.core.nova.work_revenue.router import require_work_revenue_owner

    if not (today._is_work_revenue_job_request(question) or today._is_nova_anonymous_client_request(question)):
        return None
    require_work_revenue_owner(user=user, db=db)
    return today.ask_today(db, NovaTodayBrainRequest(question=question), organization_id=organization_id, user=user)
