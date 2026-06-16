"""Shared assistant runtime contract helpers."""

from __future__ import annotations

import json
from typing import Any


def normalize_optional_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def normalize_optional_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def normalize_optional_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("{") and raw.endswith("}"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
    return {}


def normalize_supervision_details(value: Any, default: str = "supervision_enforced") -> dict[str, Any]:
    if isinstance(value, dict):
        details = dict(value)
        details["classification"] = normalize_optional_text(details.get("classification"), default)
        return details
    return {
        "classification": normalize_optional_text(value, default),
        "requires_human_confirmation": True,
    }


def normalize_supervision_classification(value: Any, default: str = "supervision_enforced") -> str:
    return normalize_supervision_details(value, default).get("classification", default)


def normalize_assistant_preview_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = normalize_optional_object(payload)
    normalized = dict(source)

    summary = normalize_optional_object(source.get("requested_action_summary"))
    summary.setdefault("intent_id", normalize_optional_text(summary.get("intent_id")))
    summary.setdefault("intent", normalize_optional_text(summary.get("intent"), "preview"))
    summary.setdefault("mode", normalize_optional_text(summary.get("mode"), "dry_run_preview_only"))

    supervision = normalize_supervision_details(source.get("supervision_classification"))

    preview_card = normalize_optional_object(source.get("preview_card"))
    preview_card["proposed_operation"] = normalize_optional_text(preview_card.get("proposed_operation"), summary.get("intent", "preview"))
    preview_card["affected_systems"] = normalize_optional_list(preview_card.get("affected_systems"))
    preview_card["supervision_classification"] = normalize_supervision_classification(
        preview_card.get("supervision_classification") or supervision
    )
    preview_card["runtime_impact"] = normalize_optional_text(preview_card.get("runtime_impact"), "no_runtime_mutation")
    preview_card["allowed_status"] = normalize_optional_text(preview_card.get("allowed_status"), "ALLOWED")
    preview_card["reason_codes"] = normalize_optional_list(preview_card.get("reason_codes"))

    normalized["requested_action_summary"] = summary
    normalized["operational_awareness"] = normalize_optional_object(source.get("operational_awareness"))
    normalized["dependency_awareness"] = normalize_optional_object(source.get("dependency_awareness"))
    normalized["supervision_classification"] = supervision
    normalized["estimated_impact"] = normalize_optional_object(source.get("estimated_impact"))
    normalized["safety_classification"] = normalize_optional_object(source.get("safety_classification"))
    normalized["preview_card"] = preview_card
    normalized["integrity"] = normalize_optional_object(source.get("integrity"))
    normalized["confirmation"] = normalize_optional_object(source.get("confirmation"))
    normalized["governance"] = normalize_optional_object(source.get("governance"))
    normalized["security_state"] = normalize_optional_object(source.get("security_state"))
    normalized["confirmation_verification"] = normalize_optional_object(source.get("confirmation_verification"))
    normalized["workflow_execution"] = normalize_optional_object(source.get("workflow_execution"))
    normalized["execution_pipeline"] = normalize_optional_object(source.get("execution_pipeline"))
    normalized["endpoint"] = normalize_optional_text(source.get("endpoint"))
    normalized["dry_run_only"] = source.get("dry_run_only") is not False
    normalized["execution_disabled"] = source.get("execution_disabled") is not False
    return normalized


def normalize_client_event_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = normalize_optional_object(payload)
    normalized_payload = normalize_optional_object(source.get("payload"))

    return {
        "event_type": normalize_optional_text(source.get("event_type") or source.get("eventType") or source.get("type"), "client"),
        "event_name": normalize_optional_text(source.get("event_name") or source.get("eventName") or source.get("name"), "event"),
        "status": normalize_optional_text(source.get("status"), "info"),
        "session_id": source.get("session_id") or source.get("sessionId"),
        "route": source.get("route") or source.get("path"),
        "correlation_id": source.get("correlation_id") or source.get("correlationId"),
        "payload": normalized_payload,
        "error_message": source.get("error_message") or source.get("errorMessage"),
    }


def normalize_execution_record(record: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(record or {})
    normalized = {
        "execution_id": normalize_optional_text(source.get("execution_id")),
        "intent_id": normalize_optional_text(source.get("intent_id")),
        "status": normalize_optional_text(source.get("status"), "pending"),
        "action_type": normalize_optional_text(source.get("action_type"), "preview"),
        "session_id": normalize_optional_text(source.get("session_id")),
        "correlation_id": normalize_optional_text(source.get("correlation_id")),
        "queued_at": source.get("queued_at"),
        "started_at": source.get("started_at"),
        "completed_at": source.get("completed_at"),
        "failed_at": source.get("failed_at"),
        "result": source.get("result") if isinstance(source.get("result"), dict) else {},
        "error_message": normalize_optional_text(source.get("error_message")),
    }
    return normalized


def normalize_memory_record(record: dict[str, Any] | None) -> dict[str, Any]:
    source = normalize_optional_object(record)
    content = normalize_optional_object(source.get("content"))
    return {
        "entry_id": normalize_optional_text(source.get("entry_id")),
        "memory_type": normalize_optional_text(source.get("memory_type"), "memory"),
        "title": normalize_optional_text(source.get("title"), "memory"),
        "session_id": source.get("session_id"),
        "role": normalize_optional_text(source.get("role")),
        "content": content,
        "created_at": source.get("created_at"),
        "updated_at": source.get("updated_at"),
    }


def normalize_operational_event_record(record: dict[str, Any] | None) -> dict[str, Any]:
    source = normalize_optional_object(record)
    payload = normalize_optional_object(source.get("payload"))

    event_id = normalize_optional_text(source.get("event_id"))
    signature = normalize_optional_text(source.get("signature"), f"sig-{event_id[-12:]}" if event_id else "sig-unknown")

    return {
        "event_id": event_id,
        "type": normalize_optional_text(source.get("type") or source.get("event_type"), "client"),
        "event_type": normalize_optional_text(source.get("event_type") or source.get("type"), "client"),
        "event_name": normalize_optional_text(source.get("event_name"), "event"),
        "status": normalize_optional_text(source.get("status"), "info"),
        "detail": normalize_optional_text(source.get("detail") or source.get("error_message") or payload.get("detail") or payload.get("message") or source.get("event_name")),
        "timestamp": source.get("timestamp") or source.get("created_at"),
        "signature": signature,
        "session_id": source.get("session_id"),
        "route": source.get("route"),
        "correlation_id": source.get("correlation_id"),
        "payload": payload,
        "error_message": source.get("error_message"),
        "created_at": source.get("created_at"),
    }