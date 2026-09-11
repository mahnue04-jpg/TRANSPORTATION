"""Additive connected-health tables. No frozen-product tables."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class LifesaverConnectedDevice(Base):
    __tablename__ = "lifesaver_connected_devices"
    __table_args__ = (
        Index("ix_ls_cdev_org_profile", "organization_id", "profile_id"),
        UniqueConstraint("organization_id", "profile_id", "client_request_id", name="uq_ls_cdev_client_req"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_type: Mapped[str] = mapped_column(String(64), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(80), nullable=False, default="unspecified")
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="simulated")
    device_alias: Mapped[str] = mapped_column(String(80), nullable=False, default="Simulated device")
    connection_method: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    integration_status: Mapped[str] = mapped_column(String(32), nullable=False, default="SIMULATED")
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="approved_simulated")
    serial_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    battery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    data_quality: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    real_connection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverConnectedReading(Base):
    __tablename__ = "lifesaver_connected_readings"
    __table_args__ = (Index("ix_ls_cread_org_profile_device", "organization_id", "profile_id", "device_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reading_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value_primary: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_secondary: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data_quality: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_services_contacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    diagnosis_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverHomeTestKit(Base):
    __tablename__ = "lifesaver_home_test_kits"
    __table_args__ = (
        Index("ix_ls_kit_org_profile", "organization_id", "profile_id"),
        UniqueConstraint("organization_id", "profile_id", "client_request_id", name="uq_ls_kit_client_req"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    test_category: Mapped[str] = mapped_column(String(64), nullable=False)
    manufacturer_or_lab: Mapped[str] = mapped_column(String(80), nullable=False, default="unspecified")
    kit_id_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ORDERED")
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    result_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ordering_source: Mapped[str] = mapped_column(String(40), nullable=False, default="user_simulated")
    provider_share_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    circle_share_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    notes: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    diagnosis_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_services_contacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverResultDocument(Base):
    __tablename__ = "lifesaver_result_documents"
    __table_args__ = (Index("ix_ls_res_org_profile", "organization_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kit_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="user_uploaded")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    document_reference: Mapped[str] = mapped_column(String(80), nullable=False, default="ref-redacted")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED")
    provider_review_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_share_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    circle_share_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    informational_note: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        default="Informational coordination record only. Not a diagnosis.",
    )
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    diagnosis_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_services_contacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


CONNECTED_HEALTH_MODELS = (
    LifesaverConnectedDevice,
    LifesaverConnectedReading,
    LifesaverHomeTestKit,
    LifesaverResultDocument,
)
