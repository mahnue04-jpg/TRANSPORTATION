"""Centralized structured logging helpers.

Design goals:
- Keep existing logger usage intact (non-breaking).
- Add optional request correlation context.
- Emit production-safe key-value fields (single-line, sanitized).
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any


_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str | None) -> Token[str | None]:
    """Set request correlation id for the current context."""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Reset request correlation id to previous value."""
    _request_id_ctx.reset(token)


def get_request_id() -> str | None:
    """Return active request correlation id if present."""
    return _request_id_ctx.get()


def safe_exception_message(exc: Exception | None, max_len: int = 512) -> str:
    """Return a sanitized, bounded exception string for logs."""
    if exc is None:
        return "unknown"
    text = str(exc).replace("\n", " ").replace("\r", " ").strip()
    if not text:
        text = exc.__class__.__name__
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _safe_value(value: Any) -> str:
    text = str(value)
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return text.strip()


def _build_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(fields):
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={_safe_value(value)}")
    return " ".join(parts)


def log_event(
    logger: Any,
    level: int,
    event: str,
    message: str,
    **fields: Any,
) -> None:
    """Emit a structured single-line log entry with request correlation."""
    req_id = get_request_id()
    payload: dict[str, Any] = {
        "event": event,
        "request_id": req_id,
        **fields,
    }
    field_text = _build_fields(payload)
    if field_text:
        logger.log(level, "%s | %s", message, field_text)
    else:
        logger.log(level, "%s", message)


def log_request_lifecycle(
    logger: Any,
    level: int,
    event: str,
    route: str,
    latency_ms: int | None = None,
    provider: str | None = None,
    status: str | None = None,
    **fields: Any,
) -> None:
    """Emit standardized request lifecycle events used for freeze diagnostics."""
    log_event(
        logger,
        level,
        event=event,
        message=event,
        route=route,
        latency_ms=latency_ms,
        provider=provider,
        status=status,
        **fields,
    )
