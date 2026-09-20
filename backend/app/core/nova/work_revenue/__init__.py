"""Nova Work & Revenue Engine package.

Keep router loading lazy so reusable utility modules (verified profile, materials,
capability/application review helpers) can be imported independently without
forcing the full API router/service graph and creating circular imports.
"""
from __future__ import annotations

from typing import Any

__all__ = ["router"]


def __getattr__(name: str) -> Any:
    if name == "router":
        from app.core.nova.work_revenue.router import router
        return router
    raise AttributeError(name)
