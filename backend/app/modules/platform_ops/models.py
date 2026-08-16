"""ORM models for platform business-operations (driver onboarding)."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.helpers import now, uuid4

logger = logging.getLogger("amicor.platform_ops.models")

APPLICATION_STATUSES = frozenset(
    {
        "draft",
        "submitted",
        "under_review",
        "documents_pending",
        "background_review",
        "approved",
        "rejected",
        "suspended",
        "activated",
    }
)

DOCUMENT_REVIEW_STATUSES = frozenset({"pending", "accepted", "rejected", "correction_requested"})

DOCUMENT_CATEGORIES = (
    "drivers_license_front",
    "drivers_license_back",
    "proof_of_auto_insurance",
    "vehicle_registration",
    "vehicle_inspection_record",
    "driver_profile_photo",
    "ssn_tax_verification_status",
    "w9_status",
    "background_check_consent",
    "motor_vehicle_record_consent",
    "independent_contractor_agreement",
    "training_certificates",
    "cpr_first_aid_certificate",
)

STATUS_ONLY_DOCUMENT_CATEGORIES = frozenset({"ssn_tax_verification_status", "w9_status"})


class PlatformDriverOnboardingApplication(Base):
    __tablename__ = "platform_driver_onboarding_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    status_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    legal_first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    legal_middle_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    legal_last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    home_address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(64), nullable=True)

    drivers_license_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_issuing_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    license_expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    years_driving_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    availability_days_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability_start_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    availability_end_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    willing_weekends: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    willing_wheelchair: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    service_area_counties: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Vehicle details collected on the simplified driver application (optional VIN).
    vehicle_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vehicle_make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle_license_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vehicle_vin: Mapped[str | None] = mapped_column(String(64), nullable=True)

    insurance_carrier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    insurance_policy_ref_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    insurance_effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    insurance_expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    insurance_vehicle_association: Mapped[str | None] = mapped_column(String(128), nullable=True)
    insurance_review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    insurance_reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    insurance_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    insurance_review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    insurance_evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    agreement_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agreement_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agreement_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agreement_evidence_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    w9_workflow_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    w9_workflow_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    w9_external_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    w9_external_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)

    declaration_valid_license: Mapped[bool] = mapped_column(Boolean, default=False)
    declaration_mvr_authorization: Mapped[bool] = mapped_column(Boolean, default=False)
    declaration_background_authorization: Mapped[bool] = mapped_column(Boolean, default=False)
    declaration_drug_alcohol_policy: Mapped[bool] = mapped_column(Boolean, default=False)
    declaration_truthful_information: Mapped[bool] = mapped_column(Boolean, default=False)
    electronic_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    signed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    assigned_reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    applicant_access_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    activated_driver_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    onboarding_gate_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    documents: Mapped[list["PlatformDriverOnboardingDocument"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["PlatformDriverOnboardingAuditEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
    )
    internal_notes: Mapped[list["PlatformDriverOnboardingInternalNote"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_platform_driver_onboarding_org_status", "organization_id", "status"),
    )


class PlatformDriverOnboardingDocument(Base):
    __tablename__ = "platform_driver_onboarding_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("platform_driver_onboarding_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="local_dev")
    storage_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_only_value: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    application: Mapped["PlatformDriverOnboardingApplication"] = relationship(back_populates="documents")

    __table_args__ = (
        Index("ix_platform_driver_onboarding_doc_app_cat", "application_id", "category"),
    )


class PlatformDriverOnboardingAuditEvent(Base):
    __tablename__ = "platform_driver_onboarding_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("platform_driver_onboarding_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    application: Mapped["PlatformDriverOnboardingApplication"] = relationship(back_populates="audit_events")


class PlatformDriverOnboardingInternalNote(Base):
    __tablename__ = "platform_driver_onboarding_internal_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("platform_driver_onboarding_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    application: Mapped["PlatformDriverOnboardingApplication"] = relationship(back_populates="internal_notes")


def _platform_ops_datetime_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "TIMESTAMP WITH TIME ZONE"
    return "DATETIME"


def _ensure_platform_ops_columns(inspector) -> None:
    from sqlalchemy import text

    from app.db.session import engine

    datetime_sql = _platform_ops_datetime_sql(engine.dialect.name)
    application_cols = {
        "vehicle_year": "INTEGER",
        "vehicle_make": "VARCHAR(64)",
        "vehicle_model": "VARCHAR(64)",
        "vehicle_license_plate": "VARCHAR(32)",
        "vehicle_vin": "VARCHAR(64)",
        "insurance_carrier": "VARCHAR(128)",
        "insurance_policy_ref_masked": "VARCHAR(64)",
        "insurance_effective_date": "DATE",
        "insurance_expiration_date": "DATE",
        "insurance_vehicle_association": "VARCHAR(128)",
        "insurance_review_status": "VARCHAR(32)",
        "insurance_reviewed_by": "VARCHAR(36)",
        "insurance_reviewed_at": datetime_sql,
        "insurance_review_notes": "TEXT",
        "insurance_evidence_ref": "VARCHAR(512)",
        "agreement_version": "VARCHAR(64)",
        "agreement_status": "VARCHAR(32)",
        "agreement_accepted_at": datetime_sql,
        "agreement_evidence_document_id": "VARCHAR(36)",
        "w9_workflow_status": "VARCHAR(32)",
        "w9_workflow_updated_at": datetime_sql,
        "w9_external_reference": "VARCHAR(128)",
        "w9_external_provider": "VARCHAR(128)",
    }
    note_cols = {
        "category": "VARCHAR(64)",
    }
    try:
        existing = {
            c["name"] for c in inspector.get_columns("platform_driver_onboarding_applications")
        }
    except Exception:
        return
    statements = [
        f"ALTER TABLE platform_driver_onboarding_applications ADD COLUMN {name} {ddl}"
        for name, ddl in application_cols.items()
        if name not in existing
    ]
    try:
        existing_notes = {
            c["name"] for c in inspector.get_columns("platform_driver_onboarding_internal_notes")
        }
        statements.extend(
            f"ALTER TABLE platform_driver_onboarding_internal_notes ADD COLUMN {name} {ddl}"
            for name, ddl in note_cols.items()
            if name not in existing_notes
        )
    except Exception:
        pass
    if not statements:
        return
    try:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        logger.info("platform_ops phase2b columns ensured (%s)", len(statements))
    except Exception as exc:
        logger.warning("platform_ops column ensure skipped: %s", exc)


def ensure_platform_ops_schema() -> None:
    """Create platform_ops tables when migrations have not run (dev/test bootstrap)."""
    from sqlalchemy import inspect

    from app.db.session import SessionLocal, engine

    try:
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        needed = {
            PlatformDriverOnboardingApplication.__tablename__,
            PlatformDriverOnboardingDocument.__tablename__,
            PlatformDriverOnboardingAuditEvent.__tablename__,
            PlatformDriverOnboardingInternalNote.__tablename__,
        }
        if not needed.issubset(existing):
            Base.metadata.create_all(bind=engine, tables=[
                PlatformDriverOnboardingApplication.__table__,
                PlatformDriverOnboardingDocument.__table__,
                PlatformDriverOnboardingAuditEvent.__table__,
                PlatformDriverOnboardingInternalNote.__table__,
            ])
            logger.info("platform_ops schema ensured via create_all")
            inspector = inspect(engine)
        _ensure_platform_ops_columns(inspector)
    except Exception as exc:
        logger.warning("platform_ops schema ensure skipped: %s", exc)
    finally:
        try:
            SessionLocal().close()
        except Exception:
            pass
