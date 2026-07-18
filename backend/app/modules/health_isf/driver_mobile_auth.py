"""Driver mobile session auth: platform JWT or X-Driver-Session-Token."""
from __future__ import annotations

from typing import NamedTuple

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_SUPERVISOR,
    UserContext,
    _bearer,
    _jwt_verify,
    resolve_session_role,
)
from app.db.session import get_db
from app.modules.health_isf import service

HEALTH_ISF_PLATFORM_ROLES = frozenset(
    {
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN_SUPPORT,
        ROLE_DISPATCHER,
        ROLE_STAFF,
        ROLE_SUPERVISOR,
        ROLE_DRIVER,
        ROLE_PROVIDER,
        ROLE_RIDER,
        ROLE_ANALYTICS_READONLY,
    }
)

DRIVER_WORKFLOW_PLATFORM_ROLES = frozenset(
    {
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN_SUPPORT,
        ROLE_DISPATCHER,
        ROLE_DRIVER,
    }
)


class DriverEndpointAuth(NamedTuple):
    user: UserContext
    # Platform user id when authenticated via JWT; None for driver mobile session tokens.
    actor_user_id: str | None


def _driver_session_token(request: Request) -> str | None:
    token = request.headers.get("X-Driver-Session-Token") or request.headers.get("x-driver-session-token")
    if not token:
        return None
    cleaned = str(token).strip()
    return cleaned or None


def _platform_user_context(
    creds: HTTPAuthorizationCredentials,
    db: Session,
    *,
    allowed_roles: frozenset[str],
) -> DriverEndpointAuth | None:
    from app.db.models import User as UserModel

    payload = _jwt_verify(creds.credentials)
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user or not user.is_active:
        return None
    session_role = resolve_session_role(user, payload)
    if session_role not in allowed_roles:
        return None
    ctx = UserContext(
        user_id=user.id,
        email=user.email,
        role=session_role,
        organization_name=getattr(user, "organization_name", None),
        organization_id=getattr(user, "organization_id", None),
    )
    return DriverEndpointAuth(user=ctx, actor_user_id=str(user.id))


def _driver_session_context(
    driver_id: str,
    session_token: str,
    db: Session,
) -> DriverEndpointAuth | None:
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        return None
    if not service.validate_driver_session_token(db, driver_id=driver_id, session_token=session_token):
        return None
    ctx = UserContext(
        user_id=str(driver.id),
        email=str(getattr(driver, "email", "") or ""),
        role=ROLE_DRIVER,
        organization_name=None,
        organization_id=driver.organization_id,
    )
    return DriverEndpointAuth(user=ctx, actor_user_id=None)


def require_driver_mobile_or_platform(*, workflow_only: bool = False):
    allowed_roles = DRIVER_WORKFLOW_PLATFORM_ROLES if workflow_only else HEALTH_ISF_PLATFORM_ROLES

    def _dependency(
        driver_id: str,
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> DriverEndpointAuth:
        session_token = _driver_session_token(request)
        if session_token:
            driver_auth = _driver_session_context(driver_id, session_token, db)
            if driver_auth:
                return driver_auth

        if creds:
            try:
                platform_auth = _platform_user_context(creds, db, allowed_roles=allowed_roles)
                if platform_auth:
                    return platform_auth
            except HTTPException:
                pass

        raise HTTPException(status_code=401, detail="Authentication required")

    return _dependency


def require_driver_accept_auth():
    """Driver workflow auth: session token wins over stale URL driver_id; platform JWT is fallback."""
    return require_driver_workflow_auth()


def require_driver_workflow_auth():
    """Session-first auth for accept/route-progress and other driver workflow mutations."""

    def _dependency(
        driver_id: str,
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> DriverEndpointAuth:
        session_token = _driver_session_token(request)
        if session_token:
            session_row = service.resolve_active_driver_session_from_token(
                db,
                session_token=session_token,
            )
            if session_row:
                session_driver_id = str(session_row.driver_id)
                driver_auth = _driver_session_context(session_driver_id, session_token, db)
                if driver_auth:
                    return driver_auth

            driver_auth = _driver_session_context(driver_id, session_token, db)
            if driver_auth:
                return driver_auth

        if creds:
            try:
                platform_auth = _platform_user_context(
                    creds,
                    db,
                    allowed_roles=DRIVER_WORKFLOW_PLATFORM_ROLES,
                )
                if platform_auth:
                    return platform_auth
            except HTTPException:
                pass

        raise HTTPException(status_code=401, detail="Authentication required")

    return _dependency


def require_ride_mobile_or_platform():
    def _dependency(
        ride_id: str,
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> DriverEndpointAuth:
        if creds:
            try:
                platform_auth = _platform_user_context(creds, db, allowed_roles=HEALTH_ISF_PLATFORM_ROLES)
                if platform_auth:
                    return platform_auth
            except HTTPException:
                pass

        session_token = _driver_session_token(request)
        if session_token:
            ride = service.get_ride_by_id(db, ride_id)
            if ride and ride.driver_id:
                driver_auth = _driver_session_context(str(ride.driver_id), session_token, db)
                if driver_auth:
                    return driver_auth

        raise HTTPException(status_code=401, detail="Authentication required")

    return _dependency
