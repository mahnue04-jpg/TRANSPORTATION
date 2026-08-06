"""ORM model for public website lead capture — isolated from ride operations."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4

logger = logging.getLogger("amicor.marketing.models")


class MarketingWebsiteLead(Base):
    """Provider / contact interest submissions from the public marketing site."""

    __tablename__ = "marketing_website_leads"
    __table_args__ = (
        Index("ix_marketing_leads_type_created", "lead_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    lead_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    organization_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact_name: Mapped[str] = mapped_column(String(128), nullable=False)
    work_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    organization_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_monthly_rides: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_area: Mapped[str | None] = mapped_column(String(256), nullable=True)
    transportation_needs: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_contact_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


def ensure_marketing_schema() -> None:
    """Create marketing lead table when migrations have not run (bootstrap-safe)."""
    from sqlalchemy import inspect

    from app.db.session import SessionLocal, engine

    try:
        inspector = inspect(engine)
        if MarketingWebsiteLead.__tablename__ in set(inspector.get_table_names()):
            return
        Base.metadata.create_all(bind=engine, tables=[MarketingWebsiteLead.__table__])
        logger.info("marketing schema ensured via create_all")
    except Exception as exc:
        logger.warning("marketing schema ensure skipped: %s", exc)
    finally:
        try:
            SessionLocal().close()
        except Exception:
            pass
