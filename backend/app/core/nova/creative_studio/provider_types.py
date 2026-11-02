"""Lightweight Studio status types; importing them never loads a provider SDK."""
from dataclasses import dataclass
from typing import Any

AVAILABLE = "AVAILABLE"
CONFIG_REQUIRED = "CONFIG_REQUIRED"
DISABLED = "DISABLED"
ERROR = "ERROR"

@dataclass
class ProviderStatus:
    provider_id: str
    kind: str
    status: str
    message: str
    configured: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind,
            "status": self.status,
            "message": self.message,
            "configured": self.configured,
        }
