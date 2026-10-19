"""Judges no-cost Casting staging stores. It does not connect or provision.

Prices were read from Render's public pages on 2026-10-19:

- https://render.com/pricing
- https://render.com/docs/free
- https://render.com/docs/disks
- https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90

A Free Postgres is $0, limited to one active database per workspace, and expires
30 days after creation. After it expires, Render keeps it for 14 days and then
deletes it. Reading an expired Free database requires a paid upgrade. The
smallest Postgres plan on that pricing page is ``0.1c-256mb`` at $6/month.
Resuming a suspended paid database starts billing again. A persistent disk
needs a paid web service; the smallest web plan on that page is ``0.5c-512mb``
at $7/month, and disks are $0.25 per GB per month. Free web services cannot
attach a disk.
"""
from __future__ import annotations

PRODUCTION_DATABASE_NAMES = frozenset({
    "amicor-health-isf-db",
    "amicor-nova-db",
})

PAID_POSTGRES_MONTHLY_USD = 6
PAID_WEB_MONTHLY_USD = 7
DISK_USD_PER_GB = 0.25
FREE_POSTGRES_LIFETIME_DAYS = 30
FREE_POSTGRES_GRACE_DAYS = 14

ACCEPTANCE_STAGES = (
    {
        "stage": 0,
        "name": "ephemeral-preview",
        "executable_without_owner": True,
        "spend_usd": 0,
        "owner_retry_allowed": False,
        "public_intake": False,
        "outbound": False,
        "copies_accounts": False,
    },
    {
        "stage": 1,
        "name": "identify-suspended-free-db",
        "executable_without_owner": False,
        "dashboard_read_only": True,
        "spend_usd": 0,
        "owner_retry_allowed": False,
        "public_intake": False,
        "outbound": False,
        "copies_accounts": False,
    },
    {
        "stage": 2,
        "name": "empty-free-postgres",
        "executable_without_owner": False,
        "requires_free_slot_empty": True,
        "spend_usd": 0,
        "owner_retry_allowed": False,
        "public_intake": False,
        "outbound": False,
        "copies_accounts": False,
    },
    {
        "stage": 3,
        "name": "preview-env-only",
        "executable_without_owner": False,
        "spend_usd": 0,
        "owner_retry_allowed": False,
        "public_intake": False,
        "outbound": False,
        "copies_accounts": False,
    },
    {
        "stage": 4,
        "name": "synthetic-restart-proof",
        "executable_without_owner": False,
        "spend_usd": 0,
        "owner_retry_allowed": False,
        "uses_owner_password": False,
        "public_intake": False,
        "outbound": False,
        "copies_accounts": False,
    },
)


def decide_staging_store(
    action: str,
    *,
    database_name: str | None = None,
    free_postgres_active: bool | None = None,
    copy_requested: bool = False,
) -> dict[str, object]:
    """Return a closed decision. This function never provisions a resource."""
    name = (database_name or "").strip()
    production = name in PRODUCTION_DATABASE_NAMES
    decision = {
        "action": action,
        "allowed_now": False,
        "monthly_usd": 0,
        "durable": False,
        "owner_retry_allowed": False,
        "provisioned": False,
        "copies_accounts": False,
        "reason": "that staging action is not available",
    }

    if copy_requested or action == "copy_database":
        decision["reason"] = "account data is not copied"
        return decision
    if production or action == "attach_production":
        decision["reason"] = "production databases stay unattached"
        return decision
    if action == "keep_ephemeral":
        decision["allowed_now"] = True
        decision["reason"] = "the preview can stay on ephemeral sqlite at $0"
        return decision
    if action == "inspect_suspended_free":
        decision["allowed_now"] = True
        decision["reason"] = "a dashboard look is $0 and does not resume the database"
        return decision
    if action in {"resume_suspended", "upgrade_suspended_free"}:
        decision["monthly_usd"] = PAID_POSTGRES_MONTHLY_USD
        decision["reason"] = "resuming or upgrading the suspended database is a paid action"
        return decision
    if action == "create_paid_postgres":
        decision["monthly_usd"] = PAID_POSTGRES_MONTHLY_USD
        decision["durable"] = True
        decision["reason"] = "a new 0.1c-256mb Postgres is $6/month and spending is not approved"
        return decision
    if action == "attach_disk":
        decision["monthly_usd"] = PAID_WEB_MONTHLY_USD + DISK_USD_PER_GB
        decision["durable"] = True
        decision["reason"] = "a disk needs the $7/month web plan plus $0.25 per GB"
        return decision
    if action == "create_empty_free":
        decision["durable"] = True
        if free_postgres_active is None:
            decision["reason"] = "the free Postgres slot has not been verified empty"
            return decision
        if free_postgres_active:
            decision["reason"] = "one active Free Postgres already occupies the workspace"
            return decision
        if not name or name in PRODUCTION_DATABASE_NAMES:
            decision["reason"] = "the new database needs its own name"
            return decision
        decision["allowed_now"] = True
        decision["reason"] = (
            "an empty Free Postgres is $0 for 30 days and still leaves the retry gate closed"
        )
        return decision
    return decision
