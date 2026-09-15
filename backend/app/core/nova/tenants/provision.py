"""Create one isolated Nova tenant with an owner/admin. Never seeds Health/Delivery/Freight."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    DEFAULT_ORGANIZATION_NAME,
    ROLE_ADMIN,
    ROLE_DEFAULT_AUTHORIZED,
    SEED_USERS,
    _build_org_code_base,
    _serialize_authorized_roles,
    _validate_email,
    _validate_password,
    active_seed_emails,
    hash_password,
    normalize_role,
)
from app.core.nova.autonomy.ledger import ensure_autonomy_schema
from app.core.nova.autonomy.models import (
    NovaAutonomyJob,
    NovaAutonomyLedger,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
)
from app.core.nova.autonomy.v2_worker import WORKER_ENABLED_ENV, env_flag_enabled
from app.core.nova.freight.models import NovaFreightShipment
from app.core.nova.today.schema_ensure import ensure_nova_today_schema
from app.db.models import User as UserModel
from app.db.session import engine
from app.helpers import now
from app.modules.health_isf.models import (
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFVehicle,
    HealthISFWorkflowExecution,
    ensure_health_isf_schema,
)
from app.modules.health_isf.service import DEFAULT_ORGANIZATION, LEGACY_ORG_CODES

logger = logging.getLogger(__name__)

DEMO_ORGANIZATION_NAME = "AMICOR Nova Demo"
DEMO_OWNER_DISPLAY_NAME = "Nova Demo Owner"
DEMO_OWNER_EMAIL = "nova.demo.owner@amicor.local"

_BLOCKED_ORG_NAMES = frozenset(
    {
        DEFAULT_ORGANIZATION_NAME.strip().lower(),
        str(DEFAULT_ORGANIZATION.get("name") or "").strip().lower(),
        "amicor health",
        "amicor health isf",
    }
)
_BLOCKED_ORG_CODES = frozenset(code.strip().upper() for code in LEGACY_ORG_CODES)


class TenantProvisionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class IsolatedNovaTenant:
    organization_id: str
    organization_name: str
    organization_code: str
    owner_user_id: str
    owner_email: str
    owner_display_name: str
    owner_role: str
    created: bool
    phase2_enabled: bool
    emergency_stop: bool
    worker_enabled: bool


@dataclass
class TenantCleanliness:
    organization_id: str
    health_rides: int = 0
    health_drivers: int = 0
    health_vehicles: int = 0
    health_providers: int = 0
    health_workflows: int = 0
    freight_shipments: int = 0
    today_actions: int = 0
    autonomy_ledger: int = 0
    autonomy_jobs: int = 0
    autonomy_workflows: int = 0
    phase2_enabled: bool = False
    emergency_stop: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def is_clean(self) -> bool:
        return (
            self.health_rides == 0
            and self.health_drivers == 0
            and self.health_vehicles == 0
            and self.health_providers == 0
            and self.health_workflows == 0
            and self.freight_shipments == 0
            and self.today_actions == 0
            and self.autonomy_ledger == 0
            and self.autonomy_jobs == 0
            and self.autonomy_workflows == 0
            and self.phase2_enabled is False
        )


def _norm_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _is_blocked_org_name(name: str) -> bool:
    return _norm_name(name).lower() in _BLOCKED_ORG_NAMES


def _is_blocked_org_code(code: str | None) -> bool:
    return str(code or "").strip().upper() in _BLOCKED_ORG_CODES


def _seed_emails() -> set[str]:
    emails = {item["email"].strip().lower() for item in SEED_USERS}
    emails.update(active_seed_emails())
    return emails


def _require_isolated_name(organization_name: str) -> str:
    cleaned = _norm_name(organization_name)
    if not cleaned:
        raise TenantProvisionError("Organization name is required", status_code=422)
    if _is_blocked_org_name(cleaned):
        raise TenantProvisionError("Default Amicor Health tenant cannot be reused", status_code=400)
    if _is_blocked_org_code(_build_org_code_base(cleaned)):
        raise TenantProvisionError("Default Amicor Health tenant cannot be reused", status_code=400)
    return cleaned


def _allocate_org_code(db: Session, organization_name: str) -> str:
    code_base = _build_org_code_base(organization_name)
    if _is_blocked_org_code(code_base):
        raise TenantProvisionError("Default Amicor Health tenant cannot be reused", status_code=400)
    candidate = code_base
    suffix = 1
    while db.query(HealthISFOrganization).filter(HealthISFOrganization.code == candidate).first() is not None:
        if _is_blocked_org_code(candidate):
            raise TenantProvisionError("Default Amicor Health tenant cannot be reused", status_code=400)
        candidate = f"{code_base[:52]}-{suffix:03d}"
        suffix += 1
    return candidate


def _existing_default_org(db: Session) -> HealthISFOrganization | None:
    return (
        db.query(HealthISFOrganization)
        .filter(HealthISFOrganization.code.in_(tuple(_BLOCKED_ORG_CODES)))
        .first()
    )


def _today_action_count(db: Session, organization_id: str) -> int:
    from app.core.nova.today.models import NovaV2CommandAction

    return int(
        db.query(func.count(NovaV2CommandAction.id))
        .filter(NovaV2CommandAction.organization_id == organization_id)
        .scalar()
        or 0
    )


def inspect_tenant_cleanliness(db: Session, organization_id: str) -> TenantCleanliness:
    flag = db.get(NovaAutonomyOrgFlag, organization_id)
    return TenantCleanliness(
        organization_id=organization_id,
        health_rides=int(
            db.query(func.count(HealthISFRide.id)).filter(HealthISFRide.organization_id == organization_id).scalar() or 0
        ),
        health_drivers=int(
            db.query(func.count(HealthISFDriver.id)).filter(HealthISFDriver.organization_id == organization_id).scalar()
            or 0
        ),
        health_vehicles=int(
            db.query(func.count(HealthISFVehicle.id)).filter(HealthISFVehicle.organization_id == organization_id).scalar()
            or 0
        ),
        health_providers=int(
            db.query(func.count(HealthISFProvider.id))
            .filter(HealthISFProvider.organization_id == organization_id)
            .scalar()
            or 0
        ),
        health_workflows=int(
            db.query(func.count(HealthISFWorkflowExecution.id))
            .filter(HealthISFWorkflowExecution.organization_id == organization_id)
            .scalar()
            or 0
        ),
        freight_shipments=int(
            db.query(func.count(NovaFreightShipment.id))
            .filter(NovaFreightShipment.organization_id == organization_id)
            .scalar()
            or 0
        ),
        today_actions=_today_action_count(db, organization_id),
        autonomy_ledger=int(
            db.query(func.count(NovaAutonomyLedger.id))
            .filter(NovaAutonomyLedger.organization_id == organization_id)
            .scalar()
            or 0
        ),
        autonomy_jobs=int(
            db.query(func.count(NovaAutonomyJob.job_id))
            .filter(NovaAutonomyJob.organization_id == organization_id)
            .scalar()
            or 0
        ),
        autonomy_workflows=int(
            db.query(func.count(NovaAutonomyWorkflow.workflow_id))
            .filter(NovaAutonomyWorkflow.organization_id == organization_id)
            .scalar()
            or 0
        ),
        phase2_enabled=bool(flag.phase2_enabled) if flag is not None else False,
        emergency_stop=bool(flag.emergency_stop) if flag is not None else False,
    )


def _ensure_phase2_off(db: Session, organization_id: str) -> NovaAutonomyOrgFlag:
    flag = db.get(NovaAutonomyOrgFlag, organization_id)
    stamp = now()
    if flag is None:
        flag = NovaAutonomyOrgFlag(
            organization_id=organization_id,
            phase2_enabled=False,
            emergency_stop=False,
            updated_at=stamp,
        )
        db.add(flag)
        return flag
    if flag.phase2_enabled or flag.emergency_stop:
        flag.phase2_enabled = False
        flag.emergency_stop = False
        flag.updated_at = stamp
    return flag


def _to_result(
    *,
    org: HealthISFOrganization,
    owner: UserModel,
    created: bool,
    flag: NovaAutonomyOrgFlag,
) -> IsolatedNovaTenant:
    return IsolatedNovaTenant(
        organization_id=str(org.id),
        organization_name=str(org.name),
        organization_code=str(org.code),
        owner_user_id=str(owner.id),
        owner_email=str(owner.email),
        owner_display_name=str(owner.display_name or ""),
        owner_role=normalize_role(owner.role),
        created=created,
        phase2_enabled=bool(flag.phase2_enabled),
        emergency_stop=bool(flag.emergency_stop),
        worker_enabled=env_flag_enabled(WORKER_ENABLED_ENV),
    )


def provision_isolated_nova_tenant(
    db: Session,
    *,
    organization_name: str = DEMO_ORGANIZATION_NAME,
    owner_email: str = DEMO_OWNER_EMAIL,
    owner_display_name: str = DEMO_OWNER_DISPLAY_NAME,
    owner_password: str,
    actor_user_id: str | None = None,
) -> IsolatedNovaTenant:
    """Create or return one isolated Nova tenant. Password is never logged or returned."""
    ensure_health_isf_schema()
    ensure_autonomy_schema(engine)
    ensure_nova_today_schema(engine)

    organization_name = _require_isolated_name(organization_name)
    owner_email = _validate_email(owner_email)
    owner_display_name = _norm_name(owner_display_name) or DEMO_OWNER_DISPLAY_NAME
    _validate_password(owner_password)

    if owner_email in _seed_emails():
        raise TenantProvisionError("Seed/operator emails cannot be used for a customer tenant", status_code=400)

    default_org = _existing_default_org(db)
    existing_user = db.query(UserModel).filter(func.lower(UserModel.email) == owner_email).first()
    existing_org = (
        db.query(HealthISFOrganization)
        .filter(func.lower(HealthISFOrganization.name) == organization_name.lower())
        .first()
    )

    if existing_org is not None:
        if default_org is not None and str(existing_org.id) == str(default_org.id):
            raise TenantProvisionError("Default Amicor Health tenant cannot be reused", status_code=400)
        if _is_blocked_org_code(existing_org.code) or _is_blocked_org_name(existing_org.name):
            raise TenantProvisionError("Default Amicor Health tenant cannot be reused", status_code=400)
        if existing_user is None:
            raise TenantProvisionError("Organization already exists with a different owner", status_code=409)
        if str(existing_user.organization_id or "") != str(existing_org.id):
            raise TenantProvisionError("Email already belongs to another organization", status_code=409)
        if normalize_role(existing_user.role) != ROLE_ADMIN:
            raise TenantProvisionError("Existing user is not the tenant owner/admin", status_code=409)
        flag = _ensure_phase2_off(db, str(existing_org.id))
        db.commit()
        logger.info(
            "Nova tenant provision idempotent actor_id=%s org_id=%s owner_email=%s",
            actor_user_id or "unknown",
            existing_org.id,
            owner_email,
        )
        return _to_result(org=existing_org, owner=existing_user, created=False, flag=flag)

    if existing_user is not None:
        raise TenantProvisionError("Email already registered", status_code=409)

    org = HealthISFOrganization(
        name=organization_name,
        code=_allocate_org_code(db, organization_name),
        is_active=True,
    )
    db.add(org)
    db.flush()

    if default_org is not None and str(org.id) == str(default_org.id):
        raise TenantProvisionError("Default Amicor Health tenant cannot be reused", status_code=400)

    owner = UserModel(
        email=owner_email,
        hashed_password=hash_password(owner_password),
        display_name=owner_display_name,
        role=ROLE_ADMIN,
        authorized_roles=_serialize_authorized_roles(ROLE_DEFAULT_AUTHORIZED[ROLE_ADMIN]),
        session_role=ROLE_ADMIN,
        organization_name=organization_name,
        organization_id=str(org.id),
        is_active=True,
        is_verified=True,
    )
    db.add(owner)
    db.flush()

    flag = _ensure_phase2_off(db, str(org.id))
    db.commit()
    db.refresh(org)
    db.refresh(owner)

    logger.info(
        "Nova tenant provisioned actor_id=%s org_id=%s owner_user_id=%s owner_email=%s",
        actor_user_id or "unknown",
        org.id,
        owner.id,
        owner_email,
    )
    return _to_result(org=org, owner=owner, created=True, flag=flag)
