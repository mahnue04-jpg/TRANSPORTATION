"""Request validation helpers and error handling utilities.

Provides consistent validation for:
- User identifiers
- Request payloads  
- Upload parameters
- Configuration parameters
"""
from io import BytesIO
from pathlib import PurePath
from typing import Any
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from pydantic import ValidationError


_MAX_FILENAME_LEN = 255
_SAFE_TEXT_TYPES = frozenset({
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
})
_MIME_ALLOWED_EXTENSIONS: dict[str, frozenset[str]] = {
    "text/plain": frozenset({".txt", ".text", ".log"}),
    "text/markdown": frozenset({".md", ".markdown"}),
    "text/csv": frozenset({".csv"}),
    "application/json": frozenset({".json"}),
    "application/pdf": frozenset({".pdf"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset({".docx"}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset({".xlsx"}),
    "image/png": frozenset({".png"}),
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/webp": frozenset({".webp"}),
}
_MAX_ARCHIVE_ENTRIES = 1500
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_COMPRESSION_RATIO = 120.0
_MAX_ARCHIVE_SINGLE_ENTRY_BYTES = 16 * 1024 * 1024


def validate_filename(filename: str | None) -> str:
    """Validate upload filename against path traversal and control chars.

    Args:
        filename: Raw upload filename

    Returns:
        Stripped filename

    Raises:
        HTTPException 400 if invalid
    """
    if not filename or not isinstance(filename, str): # type: ignore
        raise HTTPException(status_code=400, detail="filename is required")

    normalized = filename.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="filename cannot be empty")
    if len(normalized) > _MAX_FILENAME_LEN:
        raise HTTPException(status_code=400, detail=f"filename exceeds maximum length ({_MAX_FILENAME_LEN} chars)")
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise HTTPException(status_code=400, detail="filename contains invalid path characters")
    if any(ord(ch) < 32 for ch in normalized):
        raise HTTPException(status_code=400, detail="filename contains control characters")

    return normalized


def _is_likely_utf8_text(content: bytes) -> bool:
    if not content:
        return True
    sample = content[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def validate_file_signature(content_type: str, content: bytes, filename: str | None = None) -> None:
    """Validate file magic signature against declared MIME type.

    This is intentionally strict for binary types and lightweight for text types,
    to block common MIME spoofing attacks without breaking benign text uploads.

    Args:
        content_type: Normalized MIME type
        content: Raw file bytes
        filename: Optional filename for error context

    Raises:
        HTTPException 400 if signature does not match
    """
    if content_type in _SAFE_TEXT_TYPES:
        if not _is_likely_utf8_text(content):
            raise HTTPException(
                status_code=400,
                detail="Uploaded text file is not valid UTF-8 text",
            )
        return

    if content_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="File content does not match application/pdf")
        return

    if content_type == "image/png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=400, detail="File content does not match image/png")
        return

    if content_type == "image/jpeg":
        if len(content) < 4 or content[:2] != b"\xff\xd8" or content[-2:] != b"\xff\xd9":
            raise HTTPException(status_code=400, detail="File content does not match image/jpeg")
        return

    if content_type == "image/webp":
        if len(content) < 16 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
            raise HTTPException(status_code=400, detail="File content does not match image/webp")
        return

    if content_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        if len(content) < 4 or content[:4] != b"PK\x03\x04":
            raise HTTPException(status_code=400, detail=f"File content does not match {content_type}")
        if filename and content_type.endswith("document") and not filename.lower().endswith(".docx"):
            raise HTTPException(status_code=400, detail="Filename extension must be .docx for this content type")
        if filename and content_type.endswith("sheet") and not filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="Filename extension must be .xlsx for this content type")
        return


def validate_extension_mime_policy(content_type: str, filename: str) -> None:
    """Validate filename extension against declared MIME type.

    To stay non-breaking for legacy clients, files without an extension are
    allowed; when an extension exists, it must match the MIME allow-list.
    """
    suffix = PurePath(filename).suffix.lower()
    if not suffix:
        return

    allowed = _MIME_ALLOWED_EXTENSIONS.get(content_type)
    if not allowed:
        return
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Filename extension '{suffix}' does not match content type '{content_type}'",
        )


def validate_archive_safety(content_type: str, content: bytes, filename: str | None = None) -> None:
    """Validate ZIP-based office files against zip-bomb and zip-slip patterns."""
    if content_type not in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        return

    try:
        archive = ZipFile(BytesIO(content))
    except BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid Office document archive")

    total_entries = 0
    total_uncompressed = 0
    total_compressed = 0

    for info in archive.infolist():
        total_entries += 1
        if total_entries > _MAX_ARCHIVE_ENTRIES:
            raise HTTPException(status_code=400, detail="Archive contains too many entries")

        name = info.filename.replace("\\", "/")
        if name.startswith("/") or "../" in name or name.endswith("/.."):
            raise HTTPException(status_code=400, detail="Archive contains unsafe entry paths")

        total_uncompressed += info.file_size
        total_compressed += info.compress_size

        if info.file_size > _MAX_ARCHIVE_SINGLE_ENTRY_BYTES:
            raise HTTPException(status_code=400, detail="Archive contains an oversized entry")

        if total_uncompressed > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise HTTPException(status_code=400, detail="Archive expanded size exceeds safety threshold")

    ratio = float(total_uncompressed) / max(float(total_compressed), 1.0)
    if ratio > _MAX_ARCHIVE_COMPRESSION_RATIO:
        raise HTTPException(status_code=400, detail="Archive compression ratio exceeds safety threshold")


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
    if not user_id or not isinstance(user_id, str): # type: ignore
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
    if not message or not isinstance(message, str): # type: ignore
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
    if d is None or not isinstance(d, dict): # type: ignore
        return default
    return d.get(key, default)
