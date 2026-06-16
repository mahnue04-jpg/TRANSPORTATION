"""Phase 36 assistant execution and operational persistence helpers."""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    AssistantExecutionRecord,
    AssistantMemoryEntry,
    AssistantOperationalEventRecord,
)
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.core.nova.assistant_contract import (
    normalize_execution_record,
    normalize_memory_record,
    normalize_optional_object,
    normalize_operational_event_record,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value or {}, sort_keys=True, default=str)
    except Exception:
        return "{}"


def _build_execution_result(record: AssistantExecutionRecord, result_payload: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(result_payload or {}) if isinstance(result_payload, dict) else {}
    return {
        "execution_id": record.execution_id,
        "intent_id": record.intent_id,
        "status": record.status,
        "action_type": record.action_type,
        "session_id": record.session_id,
        "correlation_id": record.correlation_id,
        "queued_at": record.queued_at.isoformat() if record.queued_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "failed_at": record.failed_at.isoformat() if record.failed_at else None,
        "result": result,
        "error_message": record.error_message,
        "policy_version": record.policy_version,
        "policy_scope": record.policy_scope,
        "supervision_classification": record.supervision_classification,
    }


def _append_memory_entry(
    db: Session,
    *,
    user_id: str,
    role: str,
    session_id: str | None,
    memory_type: str,
    title: str,
    content: dict[str, Any],
) -> None:
    memory_entry = AssistantMemoryEntry(
        entry_id=f"mem-{uuid4()}",
        user_id=user_id,
        role=role,
        session_id=session_id,
        memory_type=memory_type,
        title=title,
        content_json=_safe_json(content),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    db.add(memory_entry)


def log_operational_event(
    *,
    user_id: str | None,
    role: str | None,
    event_type: str,
    event_name: str,
    status: str = "info",
    session_id: str | None = None,
    route: str | None = None,
    correlation_id: str | None = None,
    payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    try:
        with SessionLocal() as db:
            record = AssistantOperationalEventRecord(
                event_id=f"evt-{uuid4()}-{secrets.token_hex(3)}",
                user_id=user_id,
                role=role,
                session_id=session_id,
                route=route,
                event_type=str(event_type or "operational"),
                event_name=str(event_name or "event"),
                status=str(status or "info"),
                correlation_id=correlation_id,
                payload_json=_safe_json(payload),
                error_message=error_message,
                created_at=_utc_now(),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return normalize_operational_event_record(
                {
                    "event_id": record.event_id,
                    "type": record.event_type,
                    "event_type": record.event_type,
                    "event_name": record.event_name,
                    "status": record.status,
                    "detail": record.error_message,
                    "timestamp": record.created_at.isoformat() if record.created_at else None,
                    "session_id": record.session_id,
                    "route": record.route,
                    "correlation_id": record.correlation_id,
                    "payload": normalize_optional_object(record.payload_json),
                    "error_message": record.error_message,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                }
            )
    except Exception:
        logger.warning("assistant_operational_event_failed", exc_info=True)
    return None


def execute_verified_intent(
    *,
    user_id: str,
    role: str,
    intent_id: str,
    action_type: str,
    session_id: str,
    request_hash: str,
    correlation_id: str,
    policy_version: str,
    policy_scope: str,
    supervision_classification: str,
    preview_payload: dict[str, Any],
) -> dict[str, Any]:
    started_at = _utc_now()
    execution_id = f"exec-{uuid4()}-{secrets.token_hex(3)}"
    safe_payload = dict(preview_payload or {})

    with SessionLocal() as db:
        execution = AssistantExecutionRecord(
            execution_id=execution_id,
            correlation_id=correlation_id,
            intent_id=intent_id,
            request_hash=request_hash,
            user_id=user_id,
            role=role,
            session_id=session_id,
            action_type=action_type,
            status="pending",
            policy_version=policy_version,
            policy_scope=policy_scope,
            supervision_classification=supervision_classification,
            input_summary=str(safe_payload.get("requested_action_summary") or "assistant intent"),
            input_payload_json=_safe_json(safe_payload),
            queued_at=started_at,
            updated_at=started_at,
            created_at=started_at,
        )
        db.add(execution)

        _append_memory_entry(
            db,
            user_id=user_id,
            role=role,
            session_id=session_id,
            memory_type="recent_interaction",
            title="Assistant intent accepted",
            content={
                "intent_id": intent_id,
                "action_type": action_type,
                "correlation_id": correlation_id,
                "accepted_at": started_at.isoformat(),
            },
        )

        execution.status = "running"
        execution.started_at = _utc_now()
        execution.updated_at = _utc_now()

        result_payload = {
            "message": "Verified intent processed through controlled assistant workflow.",
            "execution_mode": "safe_controlled",
            "action_outcome": "advisory_execution_recorded",
            "operational_summary": str(safe_payload.get("operational_awareness") or "No additional operational context."),
            "recommended_follow_up": safe_payload.get("recommended_follow_up") or [],
        }

        execution.status = "completed"
        execution.result_json = _safe_json(result_payload)
        execution.completed_at = _utc_now()
        execution.updated_at = _utc_now()
        completed_at = execution.completed_at

        _append_memory_entry(
            db,
            user_id=user_id,
            role=role,
            session_id=session_id,
            memory_type="execution_summary",
            title="Assistant workflow completed",
            content={
                "execution_id": execution.execution_id,
                "intent_id": execution.intent_id,
                "status": execution.status,
                "completed_at": completed_at.isoformat() if completed_at else None,
                "result": result_payload,
            },
        )

        _append_memory_entry(
            db,
            user_id=user_id,
            role=role,
            session_id=session_id,
            memory_type="role_context",
            title="Role context snapshot",
            content={
                "role": role,
                "session_id": session_id,
                "policy_version": policy_version,
                "policy_scope": policy_scope,
                "supervision_classification": supervision_classification,
            },
        )

        db.commit()
        db.refresh(execution)

        response = _build_execution_result(execution, result_payload)

    log_operational_event(
        user_id=user_id,
        role=role,
        event_type="workflow",
        event_name="assistant_execution_completed",
        status="success",
        session_id=session_id,
        correlation_id=correlation_id,
        payload={
            "execution_id": execution_id,
            "intent_id": intent_id,
            "action_type": action_type,
            "status": "completed",
        },
    )

    return response


def get_recent_executions(user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 100))
    with SessionLocal() as db:
        records = (
            db.query(AssistantExecutionRecord)
            .filter(AssistantExecutionRecord.user_id == str(user_id))
            .order_by(AssistantExecutionRecord.created_at.desc())
            .limit(safe_limit)
            .all()
        )
        items: list[dict[str, Any]] = []
        for record in records:
            parsed_result: dict[str, Any] | None = None
            try:
                parsed_result = normalize_optional_object(record.result_json)
            except Exception:
                parsed_result = None
            items.append(normalize_execution_record(_build_execution_result(record, parsed_result)))
        return items


def get_recent_operational_events(user_id: str, *, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 100))
    with SessionLocal() as db:
        query = db.query(AssistantOperationalEventRecord).filter(AssistantOperationalEventRecord.user_id == str(user_id))
        if session_id:
            query = query.filter(AssistantOperationalEventRecord.session_id == str(session_id))
        records = query.order_by(AssistantOperationalEventRecord.created_at.desc()).limit(safe_limit).all()
        return [
            normalize_operational_event_record(
                {
                    "event_id": record.event_id,
                    "type": record.event_type,
                    "event_type": record.event_type,
                    "event_name": record.event_name,
                    "status": record.status,
                    "detail": record.error_message,
                    "timestamp": record.created_at.isoformat() if record.created_at else None,
                    "session_id": record.session_id,
                    "route": record.route,
                    "correlation_id": record.correlation_id,
                    "payload": normalize_optional_object(record.payload_json),
                    "error_message": record.error_message,
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                }
            )
            for record in records
        ]


def get_execution_by_id(user_id: str, execution_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        record = (
            db.query(AssistantExecutionRecord)
            .filter(
                AssistantExecutionRecord.user_id == str(user_id),
                AssistantExecutionRecord.execution_id == str(execution_id),
            )
            .first()
        )
        if not record:
            return None
        parsed_result: dict[str, Any] | None = None
        try:
            parsed_result = normalize_optional_object(record.result_json)
        except Exception:
            parsed_result = None
        return normalize_execution_record(_build_execution_result(record, parsed_result))


def get_recent_memory(user_id: str, *, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 100))
    with SessionLocal() as db:
        query = db.query(AssistantMemoryEntry).filter(AssistantMemoryEntry.user_id == str(user_id))
        if session_id:
            query = query.filter(AssistantMemoryEntry.session_id == str(session_id))
        records = query.order_by(AssistantMemoryEntry.created_at.desc()).limit(safe_limit).all()
        items: list[dict[str, Any]] = []
        for record in records:
            content = normalize_optional_object(record.content_json)
            items.append(
                normalize_memory_record(
                    {
                        "entry_id": record.entry_id,
                        "memory_type": record.memory_type,
                        "title": record.title,
                        "session_id": record.session_id,
                        "role": record.role,
                        "content": content,
                        "created_at": record.created_at.isoformat() if record.created_at else None,
                        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
                    }
                )
            )
        return items


def create_operational_note(
    *,
    user_id: str,
    role: str,
    session_id: str | None,
    title: str,
    note: str,
    scope: str,
) -> dict[str, Any]:
    now = _utc_now()
    with SessionLocal() as db:
        record = AssistantMemoryEntry(
            entry_id=f"mem-{uuid4()}",
            user_id=user_id,
            role=role,
            session_id=session_id,
            memory_type=str(scope or "operational_note"),
            title=str(title or "Operational note")[:128],
            content_json=_safe_json({"note": note}),
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

    log_operational_event(
        user_id=user_id,
        role=role,
        event_type="memory",
        event_name="operational_note_created",
        status="success",
        session_id=session_id,
        payload={"entry_id": record.entry_id, "scope": scope},
    )

    return {
        "entry_id": record.entry_id,
        "memory_type": record.memory_type,
        "title": record.title,
        "session_id": record.session_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
