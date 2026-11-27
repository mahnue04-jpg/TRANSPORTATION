from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class DeliveryResult:
    status: str
    provider: str
    cost_estimate_usd: float = 0.0
    external_id: str | None = None
    error_code: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    name: str
    live: bool

    def send(self, *, channel: str, payload: dict[str, Any]) -> DeliveryResult: ...
