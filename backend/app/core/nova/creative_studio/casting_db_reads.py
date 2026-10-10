"""Inactive DB-backed lookups for future authenticated casting read routes.

No route imports this module yet; casting migrations must be staged and reviewed.
Never accept membership fields from client requests.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .casting_db_models import (
    NovaCastingApplication, NovaCastingCampaign, NovaCastingMembership,
    NovaCastingOrganization,
)
from .casting_read_service import read_organizer_application


def read_casting_application_for_nova_user(
    *, db: Session, user_id: str, tenant_id: str, organization_id: str,
    application_id: str,
) -> dict:
    def membership_lookup(member_user_id: str, member_org_id: str):
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
        if row is None:
            return None
        membership, organization = row
        return dict(
            user_id=membership.user_id, organization_id=membership.organization_id,
            nova_tenant_id=membership.nova_tenant_id, active=membership.active,
            organization_verified=organization.verification_status == "VERIFIED",
            casting_role=membership.casting_role,
        )

    def application_lookup(key: str):
        row = db.query(NovaCastingApplication).filter(
            NovaCastingApplication.id == key,
            NovaCastingApplication.owner_id == organization_id,
        ).first()
        if row is None:
            return None
        return dict(id=row.id, campaign_id=row.campaign_id, owner_id=row.owner_id,
                    applicant_id=row.applicant_id, status=row.status, created_at=row.created_at)

    def campaign_lookup(key: str):
        row = db.query(NovaCastingCampaign).filter(
            NovaCastingCampaign.id == key,
            NovaCastingCampaign.owner_id == organization_id,
        ).first()
        if row is None:
            return None
        return dict(id=row.id, owner_id=row.owner_id)

    return read_organizer_application(
        session_user_id=user_id, session_tenant_id=tenant_id,
        casting_organization_id=organization_id, application_id=application_id,
        membership_lookup=membership_lookup, application_lookup=application_lookup,
        campaign_lookup=campaign_lookup,
    )
