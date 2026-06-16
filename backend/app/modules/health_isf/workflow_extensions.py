"""PHASE 53 additive workflow extensibility registry for transportation runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from app.modules.health_isf.service_categories import (
    ServiceCategory,
    coerce_service_category,
    ensure_active_service_category,
)


class RuntimeEventCategory(str, Enum):
    DISPATCH_LIFECYCLE = "dispatch_lifecycle"
    DISPATCH_RECOVERY = "dispatch_recovery"
    WEBSOCKET_SYNC = "websocket_sync"
    RUNTIME_REPLAY = "runtime_replay"
    RUNTIME_AUDIT = "runtime_audit"


class LifecycleExtensionHook(Protocol):
    """Lifecycle extension protocol for future module registration."""

    def before_transition(self, context: dict[str, Any]) -> None:
        ...

    def after_transition(self, context: dict[str, Any]) -> None:
        ...


@dataclass(frozen=True)
class WorkflowRegistryResolution:
    service_category: ServiceCategory
    active: bool


class WorkflowExtensionRegistry:
    def __init__(self) -> None:
        self._lifecycle_hooks: dict[ServiceCategory, list[LifecycleExtensionHook]] = {
            ServiceCategory.MEDICAL_TRANSPORT: [],
            ServiceCategory.RECURRING_TRANSPORT: [],
            ServiceCategory.PROVIDER_TRANSPORT: [],
            ServiceCategory.FUTURE_MEDICAL_LOGISTICS: [],
            ServiceCategory.FUTURE_PHARMACY_DELIVERY: [],
        }

    def resolve_active_service_category(self, service_type: Any) -> WorkflowRegistryResolution:
        service_category = ensure_active_service_category(service_type)
        return WorkflowRegistryResolution(service_category=service_category, active=True)

    def resolve_service_category(self, service_type: Any) -> WorkflowRegistryResolution:
        category = coerce_service_category(service_type, default_to_medical=True)
        active = category in {
            ServiceCategory.MEDICAL_TRANSPORT,
            ServiceCategory.RECURRING_TRANSPORT,
            ServiceCategory.PROVIDER_TRANSPORT,
        }
        return WorkflowRegistryResolution(service_category=category, active=active)

    def register_lifecycle_hook(self, service_type: Any, hook: LifecycleExtensionHook) -> None:
        resolution = self.resolve_active_service_category(service_type)
        self._lifecycle_hooks[resolution.service_category].append(hook)

    def lifecycle_hooks(self, service_type: Any) -> list[LifecycleExtensionHook]:
        resolution = self.resolve_service_category(service_type)
        return list(self._lifecycle_hooks.get(resolution.service_category, []))

    def categorize_runtime_event(self, event_name: str) -> RuntimeEventCategory:
        token = str(event_name or "").strip().lower().replace("-", "_")
        if token in {"runtime_reconnected", "sync", "subscribed", "unsubscribed"}:
            return RuntimeEventCategory.WEBSOCKET_SYNC
        if token in {"admin_override", "dispatch_recovery"}:
            return RuntimeEventCategory.DISPATCH_RECOVERY
        if token in {"runtime_replay", "replay"}:
            return RuntimeEventCategory.RUNTIME_REPLAY
        if token in {"lifecycle_audit", "audit"}:
            return RuntimeEventCategory.RUNTIME_AUDIT
        return RuntimeEventCategory.DISPATCH_LIFECYCLE


_registry = WorkflowExtensionRegistry()


def get_workflow_extension_registry() -> WorkflowExtensionRegistry:
    return _registry
