"""Owner-authorized one-time Operations payment-to-task binding.

No automatic DDL, task execution, Stripe calls, or customer delivery.
The dedicated binding table needs a separately approved migration.
"""
from __future__ import annotations

import os

from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, MetaData, String, Table, UniqueConstraint, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.marketing.models import MarketingWebsiteLead

# Define the intended schema without enrolling it in application startup create_all.
metadata = MetaData()
starter_bindings = Table(
    "nova_operations_starter_payment_bindings",
    metadata,
    Column("lead_id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("owner_user_id", String(36), nullable=False),
    Column("engagement_id", String(32), nullable=False),
    Column("task_id", String(32), nullable=False),
    Column("stripe_checkout_session_id", String(128), nullable=False, unique=True),
    UniqueConstraint("organization_id", "engagement_id", "task_id",
                     name="uq_nova_operations_starter_paid_task"),
)


def _require_ready() -> None:
    if os.getenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "").strip().lower() != "true":
        raise HTTPException(503, "Starter payment binding not enabled")


def _paid_lead(db: Session, lead_id: str) -> MarketingWebsiteLead:
    lead = db.get(MarketingWebsiteLead, lead_id)
    if (
        lead is None
        or lead.lead_type != "anonymous_operations"
        or lead.service_plan != "starter_49"
        or lead.payment_status != "paid"
        or not lead.consent
        or not lead.stripe_checkout_session_id
        or not lead.stripe_customer_id
    ):
        raise HTTPException(409, "No verified paid Starter Task checkout for this lead")
    return lead


def bind_paid_starter(
    db: Session, *, lead_id: str, organization_id: str, owner_user_id: str,
    engagement_id: str, task_id: str, client_name: str,
) -> None:
    """Bind one verified $49 checkout to precisely one saved owner task.

    Caller MUST first authenticate the owner and check eligibility of the
    saved engagement and task. Strict client comparison prevents arbitrary
    paid leads from being used to fund unrelated client work.
    """
    _require_ready()
    lead = _paid_lead(db, lead_id)
    expected_client = (lead.organization_name or lead.contact_name or "").strip().casefold()
    if not expected_client or expected_client != client_name.strip().casefold():
        raise HTTPException(409, "Paid lead does not match the saved engagement client")
    try:
        db.execute(starter_bindings.insert().values(
            lead_id=lead.id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            engagement_id=engagement_id,
            task_id=task_id,
            stripe_checkout_session_id=lead.stripe_checkout_session_id,
        ))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(409, "Starter payment binding unavailable or already assigned") from exc


def require_paid_starter(
    db: Session, *, organization_id: str, owner_user_id: str,
    engagement_id: str, task_id: str,
) -> None:
    """Fail closed without an exactly bound paid starter checkout."""
    _require_ready()
    try:
        matches = db.execute(select(starter_bindings.c.lead_id,
                                    starter_bindings.c.stripe_checkout_session_id).where(
            starter_bindings.c.organization_id == organization_id,
            starter_bindings.c.owner_user_id == owner_user_id,
            starter_bindings.c.engagement_id == engagement_id,
            starter_bindings.c.task_id == task_id,
        )).all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Starter payment records unavailable") from exc
    if len(matches) != 1:
        raise HTTPException(409, "A unique paid starter must be bound to this exact task")
    lead = _paid_lead(db, matches[0].lead_id)
    if lead.stripe_checkout_session_id != matches[0].stripe_checkout_session_id:
        raise HTTPException(409, "Paid checkout no longer matches task binding")
