"""Role and tenant actor resolution for Stay360. Unknown roles are denied."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth import UserContext

from .constants import GUEST_ROLE, HOTEL_ROLES
from .errors import Stay360Error
from .store import STORE


@dataclass(frozen=True)
class Stay360Actor:
    user_id: str
    role: str
    tenant_id: str
    kind: str
    email: str


def actor_from_user(user: UserContext) -> Stay360Actor:
    role = str(user.role or "").strip().lower()
    tenant_id = str(user.organization_id or "").strip()
    if role in HOTEL_ROLES:
        kind = "hotel"
    elif role == GUEST_ROLE:
        kind = "guest"
    else:
        raise Stay360Error(
            403,
            "role_not_permitted",
            "Stay360 hotel operations are limited to hotel staff and the bound guest.",
        )
    if tenant_id not in STORE.tenant_ids():
        raise Stay360Error(
            403,
            "tenant_not_enrolled",
            "This organization is not enrolled in Stay360.",
        )
    return Stay360Actor(
        user_id=str(user.user_id or "").strip(),
        role=role,
        tenant_id=tenant_id,
        kind=kind,
        email=str(user.email or ""),
    )
