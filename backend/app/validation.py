"""Request validation helpers and error handling utilities.

Provides consistent validation for:
- User identifiers
- Request payloads  
- Upload parameters
- Configuration parameters
"""
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError


def validate_user_id(user_id: str | None, field_name: str = "user_id") -> str:
    """Validate and normalize user_id.
    
    Args:
        user_id: Raw user identifier
        field_name: Field name for error messages
        
    Returns:
        Normalized (stripped) user_id
        
    Raises:
        HTTPException 400 if invalid
    """
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is required and must be a string",
        )
    
    normalized = user_id.strip()
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} cannot be empty or whitespace-only",
        )
    
    if len(normalized) > 256:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} exceeds maximum length (256 chars)",
        )
    
    return normalized


def validate_message(message: str | None, field_name: str = "message", max_len: int = 8000) -> str:
    """Validate and normalize message content.
    
    Args:
        message: Raw message text
        field_name: Field name for error messages
        max_len: Maximum allowed length
        
    Returns:
        Normalized (stripped) message
        
    Raises:
        HTTPException 400 if invalid
    """
    if not message or not isinstance(message, str):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is required and must be a string",
        )
    
    normalized = message.strip()
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} cannot be empty or whitespace-only",
        )
    
    if len(normalized) > max_len:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} exceeds maximum length ({max_len} chars)",
        )
    
    return normalized


def handle_validation_error(error: ValidationError, context: str = "") -> None:
    """Convert Pydantic validation error to HTTPException.
    
    Args:
        error: Pydantic ValidationError
        context: Additional context for error message
        
    Raises:
        HTTPException 422 with validation details
    """
    errors = error.errors()
    
    # Format error message from first validation error
    if errors:
        first_err = errors[0]
        field = ".".join(str(x) for x in first_err["loc"] if str(x) != "__root__")
        msg = first_err["msg"]
        detail = f"Validation error in {field}: {msg}" if field else msg
    else:
        detail = "Validation error"
    
    if context:
        detail = f"{context}: {detail}"
    
    raise HTTPException(
        status_code=422,
        detail=detail,
    )


def validate_content_type(content_type: str | None, allowed_types: set[str]) -> str:
    """Validate and normalize content type.
    
    Args:
        content_type: Raw content type header
        allowed_types: Set of allowed MIME types
        
    Returns:
        Normalized content type (without parameters)
        
    Raises:
        HTTPException 415 if unsupported
    """
    if not content_type:
        raise HTTPException(
            status_code=415,
            detail="Content-Type header is required",
        )
    
    # Extract MIME type (strip charset etc.)
    mime_type = content_type.split(";")[0].strip()
    
    if mime_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content type '{mime_type}'. Allowed: {sorted(allowed_types)}",
        )
    
    return mime_type


def validate_file_size(size: int, max_bytes: int, filename: str | None = None) -> None:
    """Validate file size.
    
    Args:
        size: File size in bytes
        max_bytes: Maximum allowed size in bytes
        filename: Optional filename for error context
        
    Raises:
        HTTPException 413 if too large
    """
    if size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        filename_str = f" ({filename})" if filename else ""
        raise HTTPException(
            status_code=413,
            detail=f"File too large{filename_str}. Maximum: {max_mb:.1f} MB",
        )


def safe_dict_get(d: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    """Safely get value from dict with type checking.
    
    Args:
        d: Dictionary to query
        key: Key to retrieve
        default: Default value if key not found
        
    Returns:
        Value from dict or default
    """
    if d is None or not isinstance(d, dict):
        return default
    return d.get(key, default)
