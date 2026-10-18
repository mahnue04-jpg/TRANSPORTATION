"""Database lookups for staging-only casting reads.

Routes must pass the Nova user id and tenant from the authenticated session.
Never accept membership, tenant, or user id fields from the client.
"""
from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.db.models import User as NovaUser

from .casting_access import CastingAccessDenied, read_application
from .casting_db_models import (
    NovaCastingApplication, NovaCastingCampaign, NovaCastingMembership,
    NovaCastingOrganization,
)
from .casting_identity import applicant_from_verified_session
from .casting_read_service import read_organizer_application, read_organizer_campaign


def _active_account(db: Session, user_id: str, tenant_id: str):
    try:
        return db.query(NovaUser).filter(
            NovaUser.id == user_id,
            NovaUser.is_active.is_(True),
            NovaUser.organization_id == tenant_id,
        ).first()
    except SQLAlchemyError as exc:
        raise CastingAccessDenied("Application unavailable") from exc


def _organization_in_tenant(db: Session, organization_id: str, tenant_id: str) -> bool:
    try:
        org = db.query(NovaCastingOrganization).filter(
            NovaCastingOrganization.id == organization_id,
            NovaCastingOrganization.nova_tenant_id == tenant_id,
        ).first()
    except SQLAlchemyError as exc:
        raise LookupError("organization unavailable") from exc
    return org is not None


def _membership_lookup(db: Session, tenant_id: str):
    def membership_lookup(member_user_id: str, member_org_id: str):
        try:
            row = (
                db.query(NovaCastingMembership, NovaCastingOrganization)
                .join(NovaCastingOrganization,
                      NovaCastingMembership.organization_id == NovaCastingOrganization.id)
                .filter(
                    NovaCastingMembership.user_id == member_user_id,
                    NovaCastingMembership.organization_id == member_org_id,
                    NovaCastingMembership.nova_tenant_id == tenant_id,
                    NovaCastingOrganization.nova_tenant_id == tenant_id,
                ).first()
            )
        except SQLAlchemyError as exc:
            raise LookupError("membership unavailable") from exc
        if row is None:
            return None
        membership, organization = row
        return dict(
            user_id=membership.user_id, organization_id=membership.organization_id,
            nova_tenant_id=membership.nova_tenant_id, active=membership.active,
            organization_verified=organization.verification_status == "VERIFIED",
            casting_role=membership.casting_role,
        )
    return membership_lookup


def _application_lookup(db: Session, organization_id: str):
    def application_lookup(key: str):
        try:
            row = db.query(NovaCastingApplication).filter(
                NovaCastingApplication.id == key,
                NovaCastingApplication.owner_id == organization_id,
            ).first()
        except SQLAlchemyError as exc:
            raise LookupError("application unavailable") from exc
        if row is None:
            return None
        return dict(id=row.id, campaign_id=row.campaign_id, owner_id=row.owner_id,
                    applicant_id=row.applicant_id, status=row.status, created_at=row.created_at)
    return application_lookup


def _campaign_lookup(db: Session, organization_id: str):
    def campaign_lookup(key: str):
        try:
            row = db.query(NovaCastingCampaign).filter(
                NovaCastingCampaign.id == key,
                NovaCastingCampaign.owner_id == organization_id,
            ).first()
        except SQLAlchemyError as exc:
            raise LookupError("campaign unavailable") from exc
        if row is None:
            return None
        return dict(
            id=row.id, owner_id=row.owner_id, title=row.title, category=row.category,
            status=row.status, created_at=row.created_at, minimum_age=row.minimum_age,
        )
    return campaign_lookup


def read_casting_application_for_nova_user(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str,
) -> dict:
    # A revoked or moved Nova account must not retain casting access.
    if _active_account(db, user_id, tenant_id) is None:
        raise CastingAccessDenied("Application unavailable")
    try:
        in_tenant = _organization_in_tenant(db, organization_id, tenant_id)
    except (LookupError, ConnectionError, TimeoutError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if not in_tenant:
        raise CastingAccessDenied("Application unavailable")
    application_lookup = _application_lookup(db, organization_id)
    campaign_lookup = _campaign_lookup(db, organization_id)
    try:
        application = application_lookup(application_id)
    except (LookupError, ConnectionError, TimeoutError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc
    if application and application.get("applicant_id") == user_id:
        actor = applicant_from_verified_session(session_user_id=user_id)
        if actor is None:
            raise CastingAccessDenied("Application unavailable")
        try:
            campaign = campaign_lookup(str(application.get("campaign_id") or ""))
        except (LookupError, ConnectionError, TimeoutError) as exc:
            raise CastingAccessDenied("Application unavailable") from exc
        return read_application(actor=actor, application=application, campaign=campaign or {})
    try:
        return read_organizer_application(
            session_user_id=user_id, session_tenant_id=tenant_id,
            casting_organization_id=organization_id, application_id=application_id,
            membership_lookup=_membership_lookup(db, tenant_id),
            application_lookup=application_lookup,
            campaign_lookup=campaign_lookup,
        )
    except (LookupError, ConnectionError, TimeoutError) as exc:
        raise CastingAccessDenied("Application unavailable") from exc


def read_casting_campaign_for_nova_user(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    campaign_id: str,
) -> dict:
    """Verified organizer or reviewer read. Applicants are not campaign members."""
    if _active_account(db, user_id, tenant_id) is None:
        raise CastingAccessDenied("Campaign unavailable")
    try:
        in_tenant = _organization_in_tenant(db, organization_id, tenant_id)
    except (LookupError, ConnectionError, TimeoutError) as exc:
        raise CastingAccessDenied("Campaign unavailable") from exc
    if not in_tenant:
        raise CastingAccessDenied("Campaign unavailable")
    return read_organizer_campaign(
        session_user_id=user_id, session_tenant_id=tenant_id,
        casting_organization_id=organization_id, campaign_id=campaign_id,
        membership_lookup=_membership_lookup(db, tenant_id),
        campaign_lookup=_campaign_lookup(db, organization_id),
    )
