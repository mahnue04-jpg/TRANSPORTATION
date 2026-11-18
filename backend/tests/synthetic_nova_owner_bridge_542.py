"""Draft read-only Workspace auth boundary; NO API or production integration.

Authentication MUST be performed by the supplied trusted server-side resolver.
Never accept role or organization directly from a browser request. The resolver
used in tests is synthetic and does not establish live session verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from synthetic_nova_workspace_542 import JourneyView, read_synthetic_journey
from synthetic_nova_replay_542 import SyntheticReplayLedger


@dataclass(frozen=True)
class ServerAuthenticatedPrincipal:
    user_id: str
    organization_id: str
    active_role: str
    authorized_roles: frozenset[str]


class SessionVerifier(Protocol):
    def __call__(self, opaque_session: str) -> ServerAuthenticatedPrincipal: ...


def owner_journey_view(
    *, opaque_session: str, verify_session: SessionVerifier,
    ledger: SyntheticReplayLedger, correlation_id: str,
) -> JourneyView:
    """Read synthetic metadata only after a server-verifier attests owner rights.

    No org/role parameter is accepted from the request. This function never
    accesses real customer records and cannot dispatch an agent action.
    """
    if not opaque_session or not correlation_id:
        raise PermissionError("valid session and journey required")
    principal = verify_session(opaque_session)
    if not isinstance(principal, ServerAuthenticatedPrincipal):
        raise PermissionError("authenticated principal required")
    if not principal.user_id or not principal.organization_id:
        raise PermissionError("user and organization identity required")
    if principal.organization_id == "global":
        raise PermissionError("global tenant access denied")
    if (principal.active_role != "admin" or
            "admin" not in principal.authorized_roles):
        raise PermissionError("organization owner role required")
    return read_synthetic_journey(
        ledger,
        organization_id=principal.organization_id,
        correlation_id=correlation_id,
        viewer_organization=principal.organization_id,
        viewer_role="owner",
    )
