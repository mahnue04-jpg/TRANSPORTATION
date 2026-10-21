"""Decision for a future Casting sign-in that could trust main Nova.

This module does not verify tokens, open a database, import accounts, or
contact main Nova. An environment variable cannot turn that path on.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

BLOCKER = (
    "No supported shared-auth path. Preview login checks platform_users in "
    "this database and verifies HS256 with this service's signing secret. "
    "Main Nova does not publish a JWKS, OIDC discovery document, or token "
    "introspection endpoint, so a main Nova token cannot be checked here."
)

OWNER_DECISIONS = (
    "Approve a public verification method on main Nova that does not copy JWT_SECRET, SECRET_KEY, DATABASE_URL, passwords, or account rows.",
    "Name the issuer URL and audience the preview may accept.",
    "Choose whether a verified subject may create a new local preview membership with no imported password, or must stay request-only.",
    "Keep casting reads, writes, media, email, SMS, and WhatsApp disabled until a separate approval.",
    "Leave the preview on amicor-casting-staging-db and leave production services unchanged.",
)

PROPOSED_ENV_NAMES = (
    "NOVA_CASTING_TRUSTED_SIGNIN",
    "NOVA_CASTING_TRUSTED_ISSUER",
    "NOVA_CASTING_TRUSTED_AUDIENCE",
    "NOVA_CASTING_TRUSTED_JWKS_URL",
)


def trusted_signin_decision(env: Mapping[str, str] | None = None) -> dict:
    """Report that shared sign-in stays off.

    Proposed environment names are recorded and ignored. This function does
    not read DATABASE_URL, JWT_SECRET, or SECRET_KEY, and it does not connect.
    """
    source = os.environ if env is None else env
    proposed = {name: str(source.get(name, "")).strip() for name in PROPOSED_ENV_NAMES}
    return {
        "supported": False,
        "enabled": False,
        "imports_accounts": False,
        "shares_database": False,
        "shares_signing_key": False,
        "shares_passwords": False,
        "validates_remote_token": False,
        "workflows_enabled": False,
        "production_integration": False,
        "algorithm": "HS256",
        "verifier": "local-hmac",
        "blocker": BLOCKER,
        "owner_decisions": list(OWNER_DECISIONS),
        "proposed_env_ignored": proposed,
    }
