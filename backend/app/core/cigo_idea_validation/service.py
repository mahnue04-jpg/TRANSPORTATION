"""In-memory fictional worksheets. Nothing here sends mail, charges a card, or renders video."""
from __future__ import annotations

import csv
import io
import os
import re
import threading
import uuid
from datetime import datetime, timezone

from app.core.cigo_idea_validation.script import (
    EXAMPLE,
    RESULTS,
    SCRIPT_ID,
    SCRIPT_TEXT,
    WORKFLOW,
    word_count,
)

_SPACE = re.compile(r"\s+")
IDEA_MIN = 12
IDEA_MAX = 500
TEXT_MIN = 20
TEXT_MAX = 500
CONSUMER_MIN = 8


def demo_enabled() -> bool:
    """Local mock only. Production never mounts this, even if the flag is set."""
    runtime = os.getenv("RUNTIME_ENVIRONMENT", os.getenv("ENVIRONMENT", "development")).strip().lower()
    if runtime in {"production", "prod"}:
        return False
    return os.getenv("CIGO_IDEA_VALIDATION_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _key(value: str) -> str:
    return _SPACE.sub(" ", value.strip().lower())


def _text(payload: dict, name: str, minimum: int) -> str | None:
    value = payload.get(name)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if len(_key(cleaned)) < minimum or len(cleaned) > TEXT_MAX:
        return None
    return cleaned


def validate(payload: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    consumer = _text(payload, "consumer", CONSUMER_MIN)
    if consumer is None:
        errors["consumer"] = f"Name the fictional consumer in at least {CONSUMER_MIN} characters."
    job = _text(payload, "job", TEXT_MIN)
    if job is None:
        errors["job"] = f"Describe the job in at least {TEXT_MIN} characters."
    idea = payload.get("idea")
    if not isinstance(idea, str) or len(_key(idea)) < IDEA_MIN:
        errors["idea"] = f"Describe the idea in at least {IDEA_MIN} characters."
    elif len(idea.strip()) > IDEA_MAX:
        errors["idea"] = f"Keep the idea to {IDEA_MAX} characters."
    assumption = _text(payload, "assumption", TEXT_MIN)
    if assumption is None:
        errors["assumption"] = f"Name the assumption in at least {TEXT_MIN} characters."
    evidence = _text(payload, "evidence", TEXT_MIN)
    if evidence is None:
        errors["evidence"] = f"Write the evidence card in at least {TEXT_MIN} characters."
    if payload.get("evidence_is_fictional") is not True:
        errors["evidence_is_fictional"] = "Mark the evidence card as fictional before it can be saved."
    if payload.get("result") not in RESULTS:
        errors["result"] = "Choose continue, reshape, or pause."
    if payload.get("consent") is not True:
        errors["consent"] = "Consent is required before a fictional worksheet can be saved."
    return errors


class IdeaValidationDemo:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.failures: list[dict] = []
        self.outbound_sends = 0
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self.records.clear()
            self.failures.clear()
            self.outbound_sends = 0

    def submit(self, payload: object, *, force_failure: str | None = None) -> dict:
        if not isinstance(payload, dict):
            failure = self._failure("invalid_input", {"body": "Request body must be a JSON object."})
            return self._invalid(failure)
        data = dict(payload)
        errors = validate(data)
        if errors:
            return self._invalid(self._failure("invalid_input", errors))
        if (force_failure or "").strip().lower() == "store":
            failure = self._failure("store_unavailable", {"store": "Simulated storage failure. Nothing was saved."})
            return {
                "ok": False,
                "status": "failed",
                "http_status": 503,
                "failure": failure,
                "outbound_sends": self.outbound_sends,
            }

        idea = str(data["idea"]).strip()
        consumer = str(data["consumer"]).strip()
        idea_key = _key(idea)
        consumer_key = _key(consumer)
        with self._lock:
            existing = next(
                (row for row in self.records if row["idea_key"] == idea_key and row["consumer_key"] == consumer_key),
                None,
            )
            if existing:
                return {
                    "ok": True,
                    "status": "duplicate",
                    "http_status": 200,
                    "created": False,
                    "record": self._public(existing),
                    "outbound_sends": self.outbound_sends,
                }
            record = {
                "id": _new_id("idea"),
                "created_at": _now(),
                "consumer": consumer,
                "consumer_key": consumer_key,
                "job": str(data["job"]).strip(),
                "idea": idea,
                "idea_key": idea_key,
                "assumption": str(data["assumption"]).strip(),
                "evidence": str(data["evidence"]).strip(),
                "evidence_is_fictional": True,
                "result": data["result"],
                "consent": True,
                "status": "worksheet_only",
            }
            self.records.append(record)
        return {
            "ok": True,
            "status": "created",
            "http_status": 201,
            "created": True,
            "record": self._public(record),
            "outbound_sends": self.outbound_sends,
        }

    def snapshot(self) -> dict:
        with self._lock:
            records = [self._public(row) for row in self.records]
            failures = list(self.failures)
            outbound = self.outbound_sends
        return {"records": records, "failures": failures, "outbound_sends": outbound}

    def evidence(self) -> dict:
        snap = self.snapshot()
        return {
            "schema": "amicor.cigo.consumer_idea_validation.v1",
            "assessment_ready": False,
            "video_rendered": False,
            "repeating_plate_created": False,
            "paid_provider_called": False,
            "commercial_use_cleared": False,
            "ip_agreement_signed": False,
            "submitted_to_cigo": False,
            "outbound_sends": snap["outbound_sends"],
            "provider": {
                "heygen_payg_watermark_free_commercial_mp4": "not_confirmed",
                "avatar_iv_seated_9_16_full_length_synced": "not_confirmed",
                "quoted_checkout_usd": None,
                "charged_usd": 0,
                "subscription_started": False,
            },
            "script": {
                "id": SCRIPT_ID,
                "text": SCRIPT_TEXT,
                "word_count": word_count(SCRIPT_TEXT),
                "rendered": False,
            },
            "workflow": list(WORKFLOW),
            "example": dict(EXAMPLE),
            "worksheet_count": len(snap["records"]),
            "failures": snap["failures"],
        }

    def export_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "id",
                "created_at",
                "consumer",
                "job",
                "idea",
                "assumption",
                "evidence",
                "evidence_is_fictional",
                "result",
                "consent",
                "status",
            ],
        )
        writer.writeheader()
        for row in self.snapshot()["records"]:
            writer.writerow(row)
        return buffer.getvalue()

    def _invalid(self, failure: dict) -> dict:
        return {
            "ok": False,
            "status": "invalid",
            "http_status": 422,
            "failure": failure,
            "outbound_sends": self.outbound_sends,
        }

    def _failure(self, kind: str, fields: dict[str, str]) -> dict:
        item = {"id": _new_id("fail"), "at": _now(), "kind": kind, "fields": fields}
        with self._lock:
            self.failures.append(item)
        return item

    @staticmethod
    def _public(row: dict) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "consumer": row["consumer"],
            "job": row["job"],
            "idea": row["idea"],
            "assumption": row["assumption"],
            "evidence": row["evidence"],
            "evidence_is_fictional": row["evidence_is_fictional"],
            "result": row["result"],
            "consent": row["consent"],
            "status": row["status"],
        }
