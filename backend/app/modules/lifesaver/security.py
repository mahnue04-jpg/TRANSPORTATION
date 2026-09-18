"""Least-privilege tenant and Care Circle checks for Lifesaver."""
from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.modules.lifesaver.audit import write_audit
from app.modules.lifesaver.constants import CAREGIVER_PERMISSIONS
from app.modules.lifesaver.models import LifesaverCareCircleMember, LifesaverConsent, LifesaverProfile


def tenant_key(ctx: UserContext) -> str:
    org_id = (ctx.organization_id or "").strip()
    if org_id:
        return org_id
    org_name = (ctx.organization_name or "").strip()
    if org_name:
        return f"lifesaver-orgname:{org_name}"
    return f"lifesaver-personal:{ctx.user_id}"


def parse_permissions(raw: str | None) -> set[str]:
    try:
        values = json.loads(raw or "[]")
    except Exception:
        return set()
    if not isinstance(values, list):
        return set()
    return {str(item) for item in values if str(item) in CAREGIVER_PERMISSIONS}


def has_consent(db: Session, profile_id: str, consent_type: str) -> bool:
    row = (
        db.query(LifesaverConsent)
        .filter(
            LifesaverConsent.profile_id == profile_id,
            LifesaverConsent.consent_type == consent_type,
            LifesaverConsent.granted.is_(True),
        )
        .first()
    )
    return row is not None


def require_consent(
    db: Session,
    ctx: UserContext,
    profile: LifesaverProfile,
    consent_type: str,
    *,
    action: str,
    resource_type: str,
) -> None:
    if has_consent(db, profile.id, consent_type):
        return
    write_audit(
        db,
        organization_id=profile.organization_id,
        actor_user_id=ctx.user_id,
        actor_profile_id=profile.id,
        action=action,
        resource_type=resource_type,
        resource_id=profile.id,
        outcome="denied",
        metadata={"reason": "consent_required", "consent_type": consent_type},
    )
    db.commit()
    raise HTTPException(
        status_code=403,
        detail=f"Consent '{consent_type}' is required before this action.",
    )


def active_circle_link(
    db: Session,
    *,
    organization_id: str,
    member_profile_id: str,
    caregiver_profile_id: str,
) -> LifesaverCareCircleMember | None:
    return (
        db.query(LifesaverCareCircleMember)
        .filter(
            LifesaverCareCircleMember.organization_id == organization_id,
            LifesaverCareCircleMember.member_profile_id == member_profile_id,
            LifesaverCareCircleMember.caregiver_profile_id == caregiver_profile_id,
            LifesaverCareCircleMember.status == "active",
        )
        .first()
    )


def require_subject_access(
    db: Session,
    ctx: UserContext,
    actor: LifesaverProfile,
    member_profile_id: str | None,
    permission: str,
    *,
    action: str,
    resource_type: str,
) -> LifesaverProfile:
    if not member_profile_id or member_profile_id == actor.id:
        return actor

    subject = (
        db.query(LifesaverProfile)
        .filter(
            LifesaverProfile.id == member_profile_id,
            LifesaverProfile.organization_id == actor.organization_id,
        )
        .first()
    )
    if subject is None:
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=member_profile_id,
            outcome="denied",
            metadata={"reason": "not_found_or_cross_tenant"},
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Care record was not found.")

    if not has_consent(db, subject.id, "caregiver_sharing"):
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=subject.id,
            outcome="denied",
            metadata={"reason": "member_sharing_consent_missing"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="The member has not consented to Care Circle sharing.")

    link = active_circle_link(
        db,
        organization_id=actor.organization_id,
        member_profile_id=subject.id,
        caregiver_profile_id=actor.id,
    )
    if link is None or permission not in parse_permissions(link.permissions_json):
        write_audit(
            db,
            organization_id=actor.organization_id,
            actor_user_id=ctx.user_id,
            actor_profile_id=actor.id,
            action=action,
            resource_type=resource_type,
            resource_id=subject.id,
            outcome="denied",
            metadata={"reason": "caregiver_permission_missing", "permission": permission},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="Care Circle permission is missing for this action.")
    return subject
