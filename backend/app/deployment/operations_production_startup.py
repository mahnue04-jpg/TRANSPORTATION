"""Production startup for the shared Operations PostgreSQL database.

Disposable SQLite and any database other than the shared production database
keep the existing seed and schema bootstrap. When Operations is pointed at the
shared production database, startup preserves accounts, passwords, roles,
permissions, and records. It does not open a connection and it does not return
credentials.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

_PRODUCTION_MARKERS = {"production", "prod"}
_SHARED_DATABASE_NAME = "amicor"


def postgres_database_name(url: str) -> str:
    """Return the database name from a PostgreSQL URL, or an empty string."""
    raw = (url or "").strip()
    if not raw.lower().startswith("postgres"):
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    name = (parsed.path or "").strip("/").split("/", 1)[0].split("?", 1)[0].strip()
    return name.casefold()


def operations_production_startup_mode(database_url: str | None = None) -> bool:
    """True when this process must not seed or change the shared production database."""
    app_env = os.getenv("APP_ENV", "").strip().lower()
    amicor_env = os.getenv("AMICOR_ENVIRONMENT", "").strip().lower()
    if not {app_env, amicor_env}.intersection(_PRODUCTION_MARKERS):
        return False
    url = os.getenv("DATABASE_URL", "") if database_url is None else database_url
    return postgres_database_name(url) == _SHARED_DATABASE_NAME


def operations_production_startup_report() -> dict[str, object]:
    """Describe startup behavior without connection strings or secrets."""
    enabled = operations_production_startup_mode()
    return {
        "mode": "preserve_existing_records" if enabled else "disposable_database",
        "database_name": _SHARED_DATABASE_NAME if enabled else "",
        "seed_demo_accounts": not enabled,
        "schema_mutations": not enabled,
        "preserves_accounts": enabled,
        "preserves_passwords": enabled,
        "preserves_roles": enabled,
        "preserves_permissions": enabled,
        "preserves_records": enabled,
        "live_sales_enabled": False,
    }
