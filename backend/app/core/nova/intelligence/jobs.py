"""In-memory synthetic media jobs. Evidence comes only from fixtures."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from app.core.nova.intelligence.fixtures import (
    SyntheticFixture,
    UnknownFixture,
    require_known_fixture,
    resolve_allowlisted_fixture,
)
from app.core.nova.intelligence.messages import (
    DIARIZATION_NOT_PERFORMED,
    NOTHING_INVENTED,
    SOURCE_REJECTED,
    SPEAKERS_UNKNOWN,
    SUMMARY_IS_FIXTURE,
)
from app.core.nova.intelligence.quotas import QuotaError, check_quota
from app.core.nova.intelligence.ssrf import UnsafeMediaUrl
from app.core.nova.intelligence.timeline import TimedObservation, timeline

_LOCK = threading.Lock()


class RejectedSource(Exception):
    detail = SOURCE_REJECTED


@dataclass(frozen=True)
class StoredJob:
    job_id: str
    tenant_id: str
    fixture_id: str
    status: str
    observations: tuple[TimedObservation, ...]
    duration_seconds: float | None
    summary: str | None
    erased: bool = False


_JOBS: dict[str, StoredJob] = {}


def reset_jobs() -> None:
    with _LOCK:
        _JOBS.clear()


def _resolve_source(source_type: object, source_value: object) -> SyntheticFixture:
    try:
        if source_type == "fixture":
            return require_known_fixture(source_value)
        if source_type == "https_url":
            return require_known_fixture(resolve_allowlisted_fixture(source_value))
    except (UnknownFixture, UnsafeMediaUrl):
        raise RejectedSource() from None
    raise RejectedSource()


def create_job(
    *,
    tenant_id: str,
    source_type: object,
    source_value: object,
    media_type: object,
    declared_bytes: object,
) -> StoredJob:
    check_quota(media_type, declared_bytes)
    fixture = _resolve_source(source_type, source_value)
    completed = fixture.status == "completed"
    observations = fixture.observations if completed else tuple()
    job = StoredJob(
        job_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fixture_id=fixture.fixture_id,
        status=fixture.status,
        observations=observations,
        duration_seconds=fixture.duration_seconds if completed else None,
        summary=fixture.summary if completed and observations else None,
        erased=False,
    )
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def _parse_job_id(job_id: str) -> str | None:
    try:
        return str(uuid.UUID(job_id))
    except (ValueError, AttributeError, TypeError):
        return None


def visible_job(job_id: str, tenant_id: str) -> StoredJob | None:
    parsed = _parse_job_id(job_id)
    if parsed is None:
        return None
    with _LOCK:
        job = _JOBS.get(parsed)
        if job is None or job.erased or job.tenant_id != tenant_id:
            return None
        return job


def erase_job(job_id: str, tenant_id: str) -> StoredJob | None:
    parsed = _parse_job_id(job_id)
    if parsed is None:
        return None
    with _LOCK:
        job = _JOBS.get(parsed)
        if job is None or job.erased or job.tenant_id != tenant_id:
            return None
        tombstone = StoredJob(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            fixture_id=job.fixture_id,
            status="erased",
            observations=tuple(),
            duration_seconds=None,
            summary=None,
            erased=True,
        )
        _JOBS[parsed] = tombstone
        return tombstone


def _segments(ordered: list[dict], kind: str) -> list[dict]:
    rows: list[dict] = []
    for item in ordered:
        if item["kind"] != kind:
            continue
        if kind == "scene":
            rows.append(
                {
                    "start_seconds": item["start_seconds"],
                    "end_seconds": item["end_seconds"],
                    "summary": item["text"],
                    "source_ref": item["source_ref"],
                }
            )
        else:
            rows.append(
                {
                    "start_seconds": item["start_seconds"],
                    "end_seconds": item["end_seconds"],
                    "text": item["text"],
                    "source_ref": item["source_ref"],
                }
            )
    return rows


def public_status(job: StoredJob) -> dict:
    body = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": 1.0 if job.status == "completed" else 0.0,
    }
    if job.status == "failed":
        body["error_code"] = "no_evidence"
    return body


def public_result(job: StoredJob) -> dict:
    ordered = timeline(job.observations) if job.status == "completed" else []
    summary = job.summary if ordered else None
    warnings = [
        SPEAKERS_UNKNOWN,
        SUMMARY_IS_FIXTURE,
        DIARIZATION_NOT_PERFORMED,
    ]
    if not ordered:
        warnings.insert(0, NOTHING_INVENTED)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "synthetic": True,
        "production_analysis": False,
        "duration_seconds": job.duration_seconds if job.status == "completed" else None,
        "observations": ordered,
        "transcript_segments": _segments(ordered, "transcript"),
        "frame_observations": _segments(ordered, "frame_ocr"),
        "scenes": _segments(ordered, "scene"),
        "summary": summary,
        "warnings": warnings,
    }
