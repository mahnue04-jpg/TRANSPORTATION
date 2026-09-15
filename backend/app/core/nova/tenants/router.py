"""Platform-support Nova tenant provision API. Not public registration. No billing.

POST /provision is ROLE_SUPER_ADMIN_SUPPORT only. A customer ROLE_ADMIN cannot
mint another tenant. Health ISF list/read scope also requires platform support
to select another organization_id; customer ROLE_ADMIN stays in its own org.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
    _RATE_LIMIT_AUTH,
    _EMAIL_RE,
    _MAX_PASSWORD_LEN,
    _MIN_PASSWORD_LEN,
    check_rate_limit,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.tenants.provision import (
    DEMO_ORGANIZATION_NAME,
    DEMO_OWNER_DISPLAY_NAME,
    DEMO_OWNER_EMAIL,
    TenantProvisionError,
    inspect_tenant_cleanliness,
    provision_isolated_nova_tenant,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/nova/tenants", tags=["nova-tenants"])

require_platform_provisioner = require_any_role(ROLE_SUPER_ADMIN_SUPPORT)
require_tenant_inspector = require_any_role(ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT)


class ProvisionNovaTenantRequest(BaseModel):
    organization_name: str = Field(default=DEMO_ORGANIZATION_NAME, min_length=3, max_length=128)
    owner_display_name: str = Field(default=DEMO_OWNER_DISPLAY_NAME, min_length=2, max_length=128)
    owner_email: str = Field(default=DEMO_OWNER_EMAIL)
    owner_password: str

    @field_validator("owner_email")
    @classmethod
    def email_format(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not _EMAIL_RE.match(cleaned):
            raise ValueError("Invalid email address")
        return cleaned

    @field_validator("owner_password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if len(value) < _MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be ≥{_MIN_PASSWORD_LEN} characters")
        if len(value) > _MAX_PASSWORD_LEN:
            raise ValueError(f"Password must be ≤{_MAX_PASSWORD_LEN} characters")
        return value


class ProvisionNovaTenantResponse(BaseModel):
    status: str
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
    public_registration: bool = False
    billing_enabled: bool = False
    trial_timer_enabled: bool = False


class TenantCleanlinessResponse(BaseModel):
    organization_id: str
    is_clean: bool
    health_rides: int
    health_drivers: int
    health_vehicles: int
    health_providers: int
    health_workflows: int
    freight_shipments: int
    today_actions: int
    autonomy_ledger: int
    autonomy_jobs: int
    autonomy_workflows: int
    phase2_enabled: bool
    emergency_stop: bool


def _raise(exc: Exception) -> None:
    if isinstance(exc, TenantProvisionError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.post("/provision", response_model=ProvisionNovaTenantResponse)
def provision_nova_tenant(
    req: ProvisionNovaTenantRequest,
    request: Request,
    admin: UserContext = Depends(get_current_user_context),
    _: object = Depends(require_platform_provisioner),
    db: Session = Depends(get_db),
):
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"nova-tenant-provision:{admin.user_id}:{ip}", limit=_RATE_LIMIT_AUTH)
    try:
        result = provision_isolated_nova_tenant(
            db,
            organization_name=req.organization_name,
            owner_email=req.owner_email,
            owner_display_name=req.owner_display_name,
            owner_password=req.owner_password,
            actor_user_id=admin.user_id,
        )
    except Exception as exc:
        _raise(exc)
        raise
    return ProvisionNovaTenantResponse(
        status="created" if result.created else "already_exists",
        organization_id=result.organization_id,
        organization_name=result.organization_name,
        organization_code=result.organization_code,
        owner_user_id=result.owner_user_id,
        owner_email=result.owner_email,
        owner_display_name=result.owner_display_name,
        owner_role=result.owner_role,
        created=result.created,
        phase2_enabled=result.phase2_enabled,
        emergency_stop=result.emergency_stop,
        worker_enabled=result.worker_enabled,
    )


@router.get("/{organization_id}/cleanliness", response_model=TenantCleanlinessResponse)
def tenant_cleanliness(
    organization_id: str,
    admin: UserContext = Depends(get_current_user_context),
    _: object = Depends(require_tenant_inspector),
    db: Session = Depends(get_db),
):
    if admin.organization_id and organization_id != admin.organization_id:
        if admin.role != ROLE_SUPER_ADMIN_SUPPORT:
            raise HTTPException(status_code=403, detail="Cross-tenant Nova access denied")
    snapshot = inspect_tenant_cleanliness(db, organization_id)
    return TenantCleanlinessResponse(
        organization_id=snapshot.organization_id,
        is_clean=snapshot.is_clean,
        health_rides=snapshot.health_rides,
        health_drivers=snapshot.health_drivers,
        health_vehicles=snapshot.health_vehicles,
        health_providers=snapshot.health_providers,
        health_workflows=snapshot.health_workflows,
        freight_shipments=snapshot.freight_shipments,
        today_actions=snapshot.today_actions,
        autonomy_ledger=snapshot.autonomy_ledger,
        autonomy_jobs=snapshot.autonomy_jobs,
        autonomy_workflows=snapshot.autonomy_workflows,
        phase2_enabled=snapshot.phase2_enabled,
        emergency_stop=snapshot.emergency_stop,
    )
