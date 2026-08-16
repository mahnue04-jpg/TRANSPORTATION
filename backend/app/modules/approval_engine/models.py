"""ORM models for the Amicor AI Approval Engine."""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.helpers import now, uuid4

logger = logging.getLogger("amicor.approval_engine.models")


class ApprovalCase(Base):
    """Generic approval case — drivers first; providers/grants/etc. later."""

    __tablename__ = "approval_engine_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="driver")
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    application_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    display_badge: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    legal_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    age_verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # License — number may be masked at rest for display; full value avoided when possible.
    license_number_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    license_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    license_verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")

    mvr_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    mvr_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    mvr_next_review_due: Mapped[date | None] = mapped_column(Date, nullable=True)

    background_study_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    fingerprint_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_REQUIRED")
    medical_qualification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    behind_wheel_eval_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    vehicle_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_registration_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vehicle_registration_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    insurance_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    insurance_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    inspection_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    inspection_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)

    approved_service_tiers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_service_tiers_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    contractor_agreement_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    w9_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    payout_setup_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")

    workflow_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    activation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_ACTIVE")
    suspension_restriction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    owner_approval_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    readiness_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    compliance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_ai_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_required_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    platform_ops_application_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    health_isf_driver_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    health_isf_application_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    requirements: Mapped[list["ApprovalRequirement"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    external_tasks: Mapped[list["ApprovalExternalTask"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    training_modules: Mapped[list["ApprovalTrainingModule"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    vehicles: Mapped[list["ApprovalVehicleRecord"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["ApprovalAuditEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_approval_cases_org_status", "organization_id", "workflow_status"),
        Index("ix_approval_cases_org_badge", "organization_id", "display_badge"),
    )


class ApprovalRequirement(Base):
    __tablename__ = "approval_engine_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requirement_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    service_tier: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timing: Mapped[str] = mapped_column(String(64), nullable=False, default="required_before_activation")
    traffic_light: Mapped[str] = mapped_column(String(16), nullable=False, default="red")
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_legal_block: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    external_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_STARTED")
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewer_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    case: Mapped["ApprovalCase"] = relationship(back_populates="requirements")

    __table_args__ = (
        Index("ix_approval_req_case_key", "case_id", "requirement_key"),
    )


class ApprovalExternalTask(Base):
    """Tasks that require outside systems or human consent — never auto-completed by AI."""

    __tablename__ = "approval_engine_external_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requirement_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    external_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_actor_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    result_actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evidence_source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    audit_history_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    case: Mapped["ApprovalCase"] = relationship(back_populates="external_tasks")


class ApprovalTrainingModule(Base):
    __tablename__ = "approval_engine_training_modules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    module_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="assigned")
    module_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    case: Mapped["ApprovalCase"] = relationship(back_populates="training_modules")

    __table_args__ = (
        Index("ix_approval_training_case_key", "case_id", "module_key"),
    )


class ApprovalVehicleRecord(Base):
    __tablename__ = "approval_engine_vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    health_isf_vehicle_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vin_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # secure/ref only
    registration_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    insurance_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    inspection_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    inspection_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    insurance_association_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    eligibility_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    dispatch_activated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    service_capability: Mapped[str] = mapped_column(String(64), nullable=False, default="AMBULATORY")
    ambulatory_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    wheelchair_capable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    wheelchair_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vehicle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    case: Mapped["ApprovalCase"] = relationship(back_populates="vehicles")


class ApprovalAuditEvent(Base):
    """Append-only material workflow audit trail."""

    __tablename__ = "approval_engine_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    case_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("approval_engine_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="SYSTEM")
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    case: Mapped["ApprovalCase | None"] = relationship(back_populates="audit_events")

    __table_args__ = (
        Index("ix_approval_audit_org_created", "organization_id", "created_at"),
        Index("ix_approval_audit_entity", "entity_type", "entity_id"),
    )


def _ensure_approval_engine_columns(inspector) -> None:
    """Add external-verification columns when tables already exist (dev/test)."""
    from sqlalchemy import text

    from app.db.session import engine

    requirement_cols = {
        "external_status": "VARCHAR(32) DEFAULT 'NOT_STARTED'",
        "verification_date": "DATE",
        "evidence_source": "VARCHAR(256)",
        "provider_key": "VARCHAR(64)",
        "provider_reference_id": "VARCHAR(128)",
        "reviewer_source": "VARCHAR(16)",
    }
    task_cols = {
        "requirement_key": "VARCHAR(64)",
        "external_status": "VARCHAR(32)",
        "evidence_source": "VARCHAR(256)",
        "provider_key": "VARCHAR(64)",
        "provider_reference_id": "VARCHAR(128)",
        "verification_date": "DATE",
        "expiration_date": "DATE",
        "audit_history_json": "TEXT",
    }
    training_cols = {
        "module_version": "VARCHAR(64)",
    }
    vehicle_cols = {
        "license_plate": "VARCHAR(32)",
        "inspection_status": "VARCHAR(32)",
        "insurance_association_ref": "VARCHAR(128)",
        "eligibility_status": "VARCHAR(32) DEFAULT 'PENDING'",
        "dispatch_activated": "BOOLEAN DEFAULT 0",
    }
    try:
        existing_req = {c["name"] for c in inspector.get_columns("approval_engine_requirements")}
        existing_task = {c["name"] for c in inspector.get_columns("approval_engine_external_tasks")}
    except Exception:
        return
    statements: list[str] = []
    for name, ddl in requirement_cols.items():
        if name not in existing_req:
            statements.append(
                f"ALTER TABLE approval_engine_requirements ADD COLUMN {name} {ddl}"
            )
    for name, ddl in task_cols.items():
        if name not in existing_task:
            statements.append(
                f"ALTER TABLE approval_engine_external_tasks ADD COLUMN {name} {ddl}"
            )
    try:
        existing_training = {c["name"] for c in inspector.get_columns("approval_engine_training_modules")}
        for name, ddl in training_cols.items():
            if name not in existing_training:
                statements.append(
                    f"ALTER TABLE approval_engine_training_modules ADD COLUMN {name} {ddl}"
                )
    except Exception:
        pass
    try:
        existing_vehicles = {c["name"] for c in inspector.get_columns("approval_engine_vehicles")}
        for name, ddl in vehicle_cols.items():
            if name not in existing_vehicles:
                statements.append(
                    f"ALTER TABLE approval_engine_vehicles ADD COLUMN {name} {ddl}"
                )
    except Exception:
        pass
    if not statements:
        return
    try:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        logger.info("approval_engine external verification columns ensured (%s)", len(statements))
    except Exception as exc:
        logger.warning("approval_engine column ensure skipped: %s", exc)


def ensure_approval_engine_schema() -> None:
    """Bootstrap tables when migrations have not run (dev/test)."""
    from sqlalchemy import inspect

    from app.db.session import engine

    tables = [
        ApprovalCase.__table__,
        ApprovalRequirement.__table__,
        ApprovalExternalTask.__table__,
        ApprovalTrainingModule.__table__,
        ApprovalVehicleRecord.__table__,
        ApprovalAuditEvent.__table__,
    ]
    try:
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        needed = {t.name for t in tables}
        if not needed.issubset(existing):
            Base.metadata.create_all(bind=engine, tables=tables)
            logger.info("approval_engine schema ensured via create_all")
            inspector = inspect(engine)
        _ensure_approval_engine_columns(inspector)
    except Exception as exc:
        logger.warning("approval_engine schema ensure skipped: %s", exc)
