"""Draft-only persistence schema for Nova Casting in existing Creative Studio.

Not imported by application startup or schema ensure until access-control review.
No actual applicant intake, video storage, or public endpoints are enabled.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class NovaCastingCampaign(Base):
    __tablename__ = "nova_casting_campaigns"
    __table_args__ = (
        Index("ix_nova_casting_campaign_owner", "owner_id", "created_at"),
        CheckConstraint("category IN ('reality', 'beauty', 'film')", name="ck_nova_casting_category"),
        CheckConstraint("status IN ('DRAFT', 'CLOSED')", name="ck_nova_casting_campaign_status"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingApplication(Base):
    __tablename__ = "nova_casting_applications"
    __table_args__ = (
        UniqueConstraint("campaign_id", "applicant_id", name="uq_nova_casting_campaign_applicant"),
        Index("ix_nova_casting_application_owner", "owner_id", "campaign_id"),
        CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'WITHDRAWN')", name="ck_nova_casting_application_status"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_campaigns.id"), nullable=False)
    applicant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT")
    consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingReview(Base):
    __tablename__ = "nova_casting_reviews"
    __table_args__ = (
        UniqueConstraint("application_id", "reviewer_id", name="uq_nova_casting_application_reviewer"),
        Index("ix_nova_casting_review_owner", "owner_id", "application_id"),
        CheckConstraint("score IS NULL OR (score >= 1 AND score <= 5)", name="ck_nova_casting_review_score"),
        CheckConstraint("stage IN ('New', 'In review', 'Callback', 'Closed')", name="ck_nova_casting_review_stage"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_applications.id"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="New")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
