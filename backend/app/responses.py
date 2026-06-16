"""Standardized API response envelopes and helpers.

Implements normalized response structure for consistent error handling and observability:
  { ok: bool, data: any, error: string|null, meta: object }

Provides backward compatibility wrappers for gradual endpoint migration.
"""
from typing import Any

from pydantic import BaseModel, Field


class ResponseMeta(BaseModel):
    """Optional metadata attached to normalized responses."""
    request_id: str | None = Field(default=None, description="Request trace ID")
    latency_ms: int | None = Field(default=None, description="Processing time in milliseconds")
    version: str | None = Field(default=None, description="API version")


class NormalizedResponse(BaseModel):
    """Standard response envelope for all normalized API endpoints."""
    ok: bool = Field(
        ...,
        description="True if request succeeded, False if error occurred",
    )
    data: Any = Field(
        default=None,
        description="Success response data. Null on error.",
    )
    error: str | None = Field(
        default=None,
        description="Error message if ok=False, else null",
    )
    meta: ResponseMeta = Field(
        default_factory=ResponseMeta,
        description="Optional metadata (request_id, latency_ms, version)",
    )

    class Config:
        json_schema_extra = { # type: ignore
            "examples": [
                {
                    "ok": True,
                    "data": {"user_id": "abc123", "status": "ready"},
                    "error": None,
                    "meta": {"request_id": "req_123", "latency_ms": 45, "version": "1.0"},
                },
                {
                    "ok": False,
                    "data": None,
                    "error": "Invalid user_id",
                    "meta": {"request_id": "req_456", "latency_ms": 12},
                },
            ]
        }


def normalize_success(
    data: Any,
    *,
    request_id: str | None = None,
    latency_ms: int | None = None,
    version: str | None = None,
) -> NormalizedResponse:
    """Create a success response with normalized envelope.
    
    Args:
        data: Response payload (any JSON-serializable value)
        request_id: Optional request trace ID
        latency_ms: Optional processing time
        version: Optional version string
        
    Returns:
        NormalizedResponse with ok=True and provided data
    """
    return NormalizedResponse(
        ok=True,
        data=data,
        error=None,
        meta=ResponseMeta(
            request_id=request_id,
            latency_ms=latency_ms,
            version=version,
        ),
    )


def normalize_error(
    error_msg: str,
    *,
    request_id: str | None = None,
    latency_ms: int | None = None,
) -> NormalizedResponse:
    """Create an error response with normalized envelope.
    
    Args:
        error_msg: Human-readable error message
        request_id: Optional request trace ID
        latency_ms: Optional processing time
        
    Returns:
        NormalizedResponse with ok=False and error message
    """
    return NormalizedResponse(
        ok=False,
        data=None,
        error=error_msg,
        meta=ResponseMeta(
            request_id=request_id,
            latency_ms=latency_ms,
        ),
    )


def as_dict(response: NormalizedResponse) -> dict[str, Any]:
    """Convert normalized response to dict for JSONResponse."""
    return response.model_dump(exclude_none=False)
