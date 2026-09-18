"""Production-grade adapter contracts. No live third-party connections."""

from app.core.nova.work_revenue.adapters.contracts import ADAPTER_KINDS, AdapterRequest, AdapterResult
from app.core.nova.work_revenue.adapters.registry import adapter_inventory, get_adapter

__all__ = ["ADAPTER_KINDS", "AdapterRequest", "AdapterResult", "adapter_inventory", "get_adapter"]
