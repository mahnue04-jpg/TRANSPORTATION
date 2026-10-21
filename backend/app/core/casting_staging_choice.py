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

PRODUCTION_SERVICE_NAMES = frozenset({
    "amicor-health-isf",
    "amicor-health-isf-py",
})

# Owner-connected Render inspection on 2026-10-19. No connection string is stored.
VERIFIED_STAGING_DATABASE = {
    "name": "amicor-casting-staging-db",
    "id": "dpg-dbap057btjjs7381egmg-a",
    "plan": "free",
    "region": "virginia",
    "status": "available",
    "expires_on": "2026-11-18",
}

PREVIEW_WEB_SERVICE = {
    "id": "srv-db7r3ke7bikc73ddosmg",
    "name": "amicor-health-isf-pr-339",
}

PREVIEW_LINK_ENV_KEYS = ("DATABASE_URL", "JWT_SECRET", "SECRET_KEY")
PREVIEW_LINK_MUST_STAY_UNSET = (
    "AMICOR_SEED_PASSWORD",
    "NOVA_CASTING_STAGING_READS",
    "ALLOWED_ORIGINS",
    "AMICOR_PUBLIC_URL",
    "APP_VERSION",
)

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
        "save_mode": "save-only",
        "database_id": VERIFIED_STAGING_DATABASE["id"],
        "service_id": PREVIEW_WEB_SERVICE["id"],
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
    if action == "link_verified_preview_database":
        return decide_preview_database_link(
            database_id=name,
            database_name=name,
            service_id="",
            service_name="",
        )
    return decision


def decide_preview_database_link(
    *,
    database_id: str,
    database_name: str,
    service_id: str,
    service_name: str,
    plan: str = "free",
    region: str = "virginia",
    status: str = "available",
    connection_string: str | None = None,
    copy_requested: bool = False,
    deploy_requested: bool = False,
) -> dict[str, object]:
    """Decide the preview link. The result never contains a connection string.

    ``allowed_now`` means the owner may perform the save-only dashboard step.
    This function does not call Render and does not store a secret reference.
    """
    decision: dict[str, object] = {
        "action": "link_verified_preview_database",
        "allowed_now": False,
        "executable_without_owner": False,
        "agent_can_store_reference": False,
        "monthly_usd": 0,
        "durable": False,
        "owner_retry_allowed": False,
        "provisioned": False,
        "copies_accounts": False,
        "public_intake": False,
        "outbound": False,
        "media_uploads": False,
        "schema_initialized": False,
        "save_mode": "save-only",
        "env_keys": list(PREVIEW_LINK_ENV_KEYS),
        "must_stay_unset": list(PREVIEW_LINK_MUST_STAY_UNSET),
        "database_id": VERIFIED_STAGING_DATABASE["id"],
        "database_name": VERIFIED_STAGING_DATABASE["name"],
        "service_id": PREVIEW_WEB_SERVICE["id"],
        "service_name": PREVIEW_WEB_SERVICE["name"],
        "reason": "that preview link is not available",
    }
    if connection_string is not None or copy_requested:
        decision["reason"] = "a connection string is not stored"
        return decision
    if deploy_requested:
        decision["reason"] = "save only; a preview deploy waits for a later review"
        return decision
    if (plan or "").strip().lower() != "free":
        decision["monthly_usd"] = PAID_POSTGRES_MONTHLY_USD
        decision["reason"] = "changing the free database to a paid plan is not approved"
        return decision
    requested_name = (database_name or "").strip()
    requested_id = (database_id or "").strip()
    if requested_name in PRODUCTION_DATABASE_NAMES or requested_id in PRODUCTION_DATABASE_NAMES:
        decision["reason"] = "production databases stay unattached"
        return decision
    requested_service_name = (service_name or "").strip()
    requested_service_id = (service_id or "").strip()
    if requested_service_name in PRODUCTION_SERVICE_NAMES:
        decision["reason"] = "production services stay unchanged"
        return decision
    identity_matches = (
        requested_id == VERIFIED_STAGING_DATABASE["id"]
        and requested_name == VERIFIED_STAGING_DATABASE["name"]
        and requested_service_id == PREVIEW_WEB_SERVICE["id"]
        and requested_service_name == PREVIEW_WEB_SERVICE["name"]
    )
    if not identity_matches:
        decision["reason"] = "only the verified free database links to the preview service"
        return decision
    if (status or "").strip().lower() != VERIFIED_STAGING_DATABASE["status"]:
        decision["reason"] = "the database is not available"
        return decision
    if (region or "").strip().lower() != VERIFIED_STAGING_DATABASE["region"]:
        decision["reason"] = "the internal reference requires Virginia on the database and the preview"
        return decision
    decision["allowed_now"] = True
    decision["durable"] = True
    decision["reason"] = (
        "the owner can save a secret reference and new signing keys on the preview only"
    )
    return decision
