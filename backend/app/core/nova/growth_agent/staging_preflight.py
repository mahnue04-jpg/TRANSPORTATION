"""Pure staging startup preflight. No SQL, migrations, tests, or network I/O.

Not wired into Render. Must be reviewed and explicitly authorized before use.
Run from backend/: python -m app.core.nova.growth_agent.staging_preflight
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlsplit


_SHA = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_HOST = "dpg-dbqv7mmtlv9c73d7tnb0-a"
_EXPECTED_DATABASE = "nova_ga_490_dispos"


def validate(environment: dict[str, str]) -> tuple[bool, str]:
    """Compare exact staging identities; never return a credential or connection URL."""
    current = environment.get("RENDER_GIT_COMMIT", "").strip().lower()
    approved = environment.get("NOVA_GA_APPROVED_STAGING_SHA", "").strip().lower()
    if not _SHA.fullmatch(approved) or not _SHA.fullmatch(current):
        return False, "Missing or invalid exact-commit pin"
    if current != approved:
        return False, "Deployed commit does not match approved staging pin"

    if environment.get("APP_ENV", "").lower() != "staging":
        return False, "APP_ENV must be staging"
    if environment.get("AMICOR_ENVIRONMENT", "").lower() != "staging":
        return False, "AMICOR_ENVIRONMENT must be staging"

    raw_url = environment.get("DATABASE_URL", "")
    try:
        parsed = urlsplit(raw_url)
        # URL parser credentials should never appear in error strings or logs.
        if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2"}:
            return False, "Expected staging PostgreSQL URL scheme"
        if parsed.hostname != _EXPECTED_HOST or parsed.path != "/" + _EXPECTED_DATABASE:
            return False, "Database identity does not match dedicated staging database"
        if not parsed.username or not parsed.password:
            return False, "Staging database credentials are missing"
        if parsed.query or parsed.fragment:
            return False, "Unexpected database URL parameters"
    except ValueError:
        return False, "Invalid database URL"

    forbidden_enabled = (
        "NOVA_STRIPE_LIVE_ENABLED",
        "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED",
    )
    for flag in forbidden_enabled:
        if environment.get(flag, "").strip().lower() in {"true", "1", "yes", "on"}:
            return False, "Unsafe live/deletion flag enabled"

    return True, "Growth staging preflight passed (identity only; database untested)"


def main() -> int:
    ok, message = validate(dict(os.environ))
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
