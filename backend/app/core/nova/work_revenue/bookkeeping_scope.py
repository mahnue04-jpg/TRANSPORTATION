"""Read-only, server-side scope resolution for supervised finance assignments.

Records must be provisioned by a separately reviewed contractual authorization
process. No client, HTTP caller or self-service owner checkbox can create an
APPROVED record through this module. Missing schema/record always denies.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .bookkeeping_assignment import BookkeepingAssignment, SUPPORTED_WORK_TYPES
from . import service

metadata = sa.MetaData()
consents = sa.Table(
    "nova_bookkeeping_contract_authorizations", metadata,
    sa.Column("authorization_id", sa.String(36), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("engagement_id", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(32), nullable=False),
    sa.Column("work_type", sa.String(40), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("contract_ref_sha256", sa.String(64), nullable=False),
    sa.Column("client_ai_consent_ref_sha256", sa.String(64), nullable=False),
    sa.Column("data_processing_ref_sha256", sa.String(64), nullable=False),
    sa.Column("verified_by_user_id", sa.String(36), nullable=False),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint("organization_id", "owner_user_id",
                        "engagement_id", "task_id", "work_type",
                        name="uq_nova_bookkeeping_consent_scope"),
)


class ConsentNotVerified(ValueError):
    pass


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    ) and value != "0" * 64


def _trusted_eligible_task(
    task: dict, completed_ids: set[str], work_type: str, *,
    verified_contract_scope: bool = False,
) -> bool:
    """Structured task work type required; text descriptions are not sufficient."""
    dependency = str(task.get("depends_on_task_id") or "")
    return (
        (task.get("bookkeeping_work_type") == work_type or (
            verified_contract_scope and task.get("bookkeeping_work_type") in (None, "")
        ))
        and str(task.get("classification") or "").upper() == "NOVA"
        and str(task.get("responsible_party") or "").upper() == "NOVA"
        and task.get("review_required") is True
        and str(task.get("status") or "").upper()
        in {"READY", "NOT_STARTED", "IN_PROGRESS"}
        and not str(task.get("blocked_reason") or "").strip()
        and not str(task.get("required_owner_input") or "").strip()
        and (not dependency or dependency in completed_ids)
    )


def resolve_bookkeeping_assignment(
    db: Session, *, owner, engagement_id: str, task_id: str, work_type: str,
    now: datetime | None = None, lock_consent: bool = False,
) -> BookkeepingAssignment:
    """Require active saved task plus independently verified contract records.

    This function never creates or upgrades a consent. The existing Work &
    Revenue task model does not currently persist `bookkeeping_work_type`,
    so staging remains fail-closed until an explicitly reviewed schema change.
    """
    org = getattr(owner, "organization_id", None)
    owner_id = getattr(owner, "user_id", None)
    if not all(
        isinstance(x, str) and 0 < len(x) <= 120 and x.strip() and x.lower() != "global"
        for x in (org, owner_id, engagement_id, task_id)
    ) or work_type not in SUPPORTED_WORK_TYPES:
        raise ConsentNotVerified("Valid organization, owner and assigned work required")
    bind = db.get_bind()
    if bind.dialect.name != "postgresql" or not sa.inspect(bind).has_table(consents.name):
        raise ConsentNotVerified("Verified contract authorization schema unavailable")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ConsentNotVerified("Timezone-aware validation required")
    query = sa.select(consents).where(
        consents.c.organization_id == org,
        consents.c.owner_user_id == owner_id,
        consents.c.engagement_id == engagement_id,
        consents.c.task_id == task_id,
        consents.c.work_type == work_type,
        consents.c.status == "APPROVED",
        consents.c.revoked_at.is_(None),
    )
    if lock_consent:
        # Only an exclusive PostgreSQL row lock serializes verification with
        # a concurrent revocation update. Caller MUST commit/rollback promptly.
        query = query.with_for_update()
    records = db.execute(query).mappings().all()
    if len(records) != 1:
        raise ConsentNotVerified("Current verified contract authorization missing")
    record = records[0]
    if not all(_digest(record[key]) for key in (
        "contract_ref_sha256", "client_ai_consent_ref_sha256",
        "data_processing_ref_sha256",
    )) or not record["verified_by_user_id"]:
        raise ConsentNotVerified("Auditable contract and consent evidence missing")
    verified = record["verified_at"]
    expires = record["valid_until"]
    if not isinstance(verified, datetime) or not isinstance(expires, datetime):
        raise ConsentNotVerified("Contract verification dates invalid")
    # PostgreSQL TIMESTAMP WITH TIME ZONE normally returns aware datetimes.
    if verified.tzinfo is None or expires.tzinfo is None:
        raise ConsentNotVerified("Contract timestamps must contain timezones")
    if verified > now or expires <= now or verified >= expires:
        raise ConsentNotVerified("Contract authorization expired or invalid")

    # Resolve existing CSV-scope helpers after module initialization to avoid
    # circular module imports with the registered owner-only router.
    from .operations_owner_csv_api import _eligible_engagement, _completed_task_ids
    try:
        engagement = service.get_engagement(
            db, engagement_id, organization_id=org, user=owner,
        )
    except service.NovaWorkError as exc:
        raise ConsentNotVerified("Saved engagement unavailable") from exc
    if (
        not isinstance(engagement, dict)
        or str(engagement.get("engagement_id") or "") != engagement_id
        or not _eligible_engagement(engagement, org, owner_id)
    ):
        raise ConsentNotVerified("Engagement is inactive or not owner-scoped")
    tasks = [
        t for t in (engagement.get("tasks") or [])
        if isinstance(t, dict) and str(t.get("task_id") or "") == task_id
    ]
    if len(tasks) != 1 or not _trusted_eligible_task(
        tasks[0], _completed_task_ids(engagement), work_type,
        verified_contract_scope=True,
    ):
        raise ConsentNotVerified("No eligible structured bookkeeping task")
    return BookkeepingAssignment(
        organization_id=org, owner_user_id=owner_id,
        engagement_id=engagement_id, task_id=task_id, work_type=work_type,
        ai_assistance_permitted=True, data_processing_authorized=True,
        human_review_required=True, contracted_work_types=frozenset({work_type}),
    )
