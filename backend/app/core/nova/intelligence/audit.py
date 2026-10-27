"""Audit lines for synthetic media jobs.

Only job id, tenant id, status, and fixture id are written. Transcript and
frame text must never be passed here.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("nova.intelligence.media.audit")

_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def record_audit(*, job_id: str, tenant_id: str, status: str, fixture_id: str) -> None:
    fields = (job_id, tenant_id, status, fixture_id)
    if any(not isinstance(item, str) or _TOKEN.fullmatch(item) is None for item in fields):
        logger.info("media_job_audit_dropped")
        return
    logger.info(
        "media_job job_id=%s tenant_id=%s status=%s fixture_id=%s",
        job_id,
        tenant_id,
        status,
        fixture_id,
    )
