"""Nova freight shipment table. Not a HealthISFRide and not a Delivery job."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaFreightShipment(Base):
    __tablename__ = "nova_freight_shipments"
    __table_args__ = (
        Index("ix_nova_freight_shipments_shipment_id", "shipment_id", unique=True),
        Index("ix_nova_freight_shipments_org_id", "organization_id"),
        Index("ix_nova_freight_shipments_status", "status"),
        Index("ix_nova_freight_shipments_created_at", "created_at"),
        Index("ix_nova_freight_shipments_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    shipment_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    shipper_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready_for_dispatch")

    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    pickup_address: Mapped[str] = mapped_column(String(300), nullable=False)
    pickup_city: Mapped[str] = mapped_column(String(120), nullable=False)
    pickup_state: Mapped[str] = mapped_column(String(32), nullable=False)
    pickup_zip: Mapped[str] = mapped_column(String(16), nullable=False)
    pickup_contact: Mapped[str | None] = mapped_column(String(160), nullable=True)
    pickup_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pickup_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    delivery_address: Mapped[str] = mapped_column(String(300), nullable=False)
    delivery_city: Mapped[str] = mapped_column(String(120), nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_zip: Mapped[str] = mapped_column(String(16), nullable=False)
    delivery_contact: Mapped[str | None] = mapped_column(String(160), nullable=True)
    delivery_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivery_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    commodity: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    weight_unit: Mapped[str] = mapped_column(String(8), nullable=False, default="lb")
    piece_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pallet_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    length_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    width_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    height_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    special_handling_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    hazardous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temperature_controlled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fragile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    equipment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="cargo_van")

    quoted_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    carrier_payout_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    amicor_margin: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    proof_of_pickup_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proof_of_delivery_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_refs_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_carrier_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assigned_offer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaFreightCarrier(Base):
    __tablename__ = "nova_freight_carriers"
    __table_args__ = (
        Index("ix_nova_freight_carriers_carrier_id", "carrier_id", unique=True),
        Index("ix_nova_freight_carriers_org_id", "organization_id"),
        Index("ix_nova_freight_carriers_user_id", "user_id"),
        Index("ix_nova_freight_carriers_active", "organization_id", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    carrier_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    equipment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="cargo_van")
    service_area: Mapped[str | None] = mapped_column(String(240), nullable=True)
    availability: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    authority_status: Mapped[str] = mapped_column(String(32), nullable=False, default="placeholder")
    insurance_status: Mapped[str] = mapped_column(String(32), nullable=False, default="placeholder")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaFreightOffer(Base):
    __tablename__ = "nova_freight_offers"
    __table_args__ = (
        Index("ix_nova_freight_offers_offer_id", "offer_id", unique=True),
        Index("ix_nova_freight_offers_shipment_id", "shipment_id"),
        Index("ix_nova_freight_offers_carrier_id", "carrier_id"),
        Index("ix_nova_freight_offers_org_status", "organization_id", "status"),
        Index("ix_nova_freight_offers_shipment_status", "shipment_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    offer_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    shipment_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    carrier_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    offered_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaFreightShipmentEvent(Base):
    __tablename__ = "nova_freight_shipment_events"
    __table_args__ = (
        Index("ix_nova_freight_events_event_id", "event_id", unique=True),
        Index("ix_nova_freight_events_shipment_id", "shipment_id"),
        Index("ix_nova_freight_events_org_id", "organization_id"),
        Index("ix_nova_freight_events_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    event_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    shipment_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status_before: Mapped[str] = mapped_column(String(32), nullable=False)
    status_after: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, default="status_transition")
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_carrier_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proof_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaFreightProof(Base):
    __tablename__ = "nova_freight_proofs"
    __table_args__ = (
        Index("ix_nova_freight_proofs_proof_id", "proof_id", unique=True),
        Index("ix_nova_freight_proofs_shipment_id", "shipment_id"),
        Index("ix_nova_freight_proofs_org_id", "organization_id"),
        Index("ix_nova_freight_proofs_doc_ref", "shipment_id", "document_ref"),
        Index("ix_nova_freight_proofs_active", "shipment_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    proof_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    shipment_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proof_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_by_carrier_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uploader_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    signer_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
