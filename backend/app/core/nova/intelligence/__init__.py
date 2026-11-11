"""Nova intelligence package.

Operational scoring stays importable as ``NovaIntelligenceEngine``. Synthetic
media modules are loaded only by their own callers.
"""
from __future__ import annotations

from typing import Any

__all__ = ["NovaIntelligenceEngine"]


def __getattr__(name: str) -> Any:
    if name == "NovaIntelligenceEngine":
        from app.core.nova.intelligence.operational_engine import NovaIntelligenceEngine

        return NovaIntelligenceEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
