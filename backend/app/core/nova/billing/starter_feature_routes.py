"""Isolated Starter self-service rehearsal API. No legacy route changes."""
from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.db.session import get_db
from .starter_authenticated_access import authenticated_starter_access

router = APIRouter(prefix="/api/nova/starter", tags=["nova-starter-staging"])


class PlanningRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500)


def require_feature(db, user, feature):
    if not authenticated_starter_access(db, authenticated_user=user, feature=feature):
        raise HTTPException(status_code=403, detail="Verified Starter staging subscription required")


@router.get("/workspace")
def workspace(response: Response, user: UserContext = Depends(get_current_user_context),
              db: Session = Depends(get_db)):
    require_feature(db, user, "basic_workspace")
    response.headers["Cache-Control"] = "no-store"
    return {"plan": "starter", "monthly_usd_cents": 999, "managed_tasks": 0,
            "features": ["basic_workspace", "task_planning", "templates", "self_service_assistance"],
            "staging_only": True}


@router.post("/plan")
def plan(body: PlanningRequest, response: Response,
         user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    require_feature(db, user, "task_planning")
    response.headers["Cache-Control"] = "no-store"
    return {"goal": body.goal, "steps": ["Define the expected result",
        "Identify required information", "Set a deadline", "Complete and review your own work"],
        "execution": "customer_self_service", "saved": False}


@router.get("/templates")
def templates(response: Response, user: UserContext = Depends(get_current_user_context),
              db: Session = Depends(get_db)):
    require_feature(db, user, "templates")
    response.headers["Cache-Control"] = "no-store"
    return {"templates": [
        {"name": "Task brief", "fields": ["Objective", "Inputs", "Deliverable", "Deadline"]},
        {"name": "Weekly business review", "fields": ["Results", "Open work", "Risks", "Next steps"]},
        {"name": "Customer follow-up", "fields": ["Contact", "Context", "Next action", "Due date"]},
    ]}


@router.get("/assistance")
def assistance(response: Response, user: UserContext = Depends(get_current_user_context),
               db: Session = Depends(get_db)):
    require_feature(db, user, "self_service_assistance")
    response.headers["Cache-Control"] = "no-store"
    return {"guidance": ["Use the planning checklist to scope your work",
        "Choose a template and fill in your information",
        "Review your output before using it",
        "Request a separately scoped managed task if you need AMICOR to execute work"],
        "mode": "static_guidance", "external_ai": False, "managed_execution": False}


def starter_routes_enabled():
    return (
        os.getenv("APP_ENV") == "staging"
        and os.getenv("AMICOR_ENVIRONMENT") == "staging"
        and os.getenv("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED") == "true"
        and os.getenv("NOVA_STRIPE_LIVE_ENABLED") == "false"
        and os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") == "false"
    )


@router.get("/interface", response_class=HTMLResponse, include_in_schema=False)
def interface(user: UserContext = Depends(get_current_user_context),
              db: Session = Depends(get_db)):
    require_feature(db, user, "basic_workspace")
    return HTMLResponse(Path(__file__).with_name("starter_ui.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                 "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})
