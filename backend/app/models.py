from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """Chat message request with validation.
    
    Constraints:
    - user_id: non-empty, max 256 chars
    - message: non-empty, max 8000 chars
    """
    user_id: str = Field( # type: ignore
        ...,
        min_length=1,
        max_length=256,
        strip_whitespace=True,
        description="Unique identifier for the user",
    ) # type: ignore
    message: str = Field( # type: ignore
        ...,
        min_length=1,
        max_length=8000,
        strip_whitespace=True,
        description="Chat message content",
    ) # type: ignore

    @field_validator("user_id", "message")
    @classmethod
    def reject_empty_after_strip(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or whitespace-only")
        return v.strip()


class ResetRequest(BaseModel):
    """Memory reset request with validation.
    
    Constraints:
    - user_id: non-empty, max 256 chars
    """
    user_id: str = Field( # type: ignore
        ...,
        min_length=1,
        max_length=256,
        strip_whitespace=True,
        description="User identifier",
    ) # type: ignore

    @field_validator("user_id")
    @classmethod
    def reject_empty_after_strip(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("user_id cannot be empty")
        return v.strip()