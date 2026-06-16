"""PHASE 53 transportation-first service category foundation (additive, fail-safe)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ServiceCategory(str, Enum):
    MEDICAL_TRANSPORT = "medical_transport"
    RECURRING_TRANSPORT = "recurring_transport"
    PROVIDER_TRANSPORT = "provider_transport"
    FUTURE_MEDICAL_LOGISTICS = "future_medical_logistics"
    FUTURE_PHARMACY_DELIVERY = "future_pharmacy_delivery"


@dataclass(frozen=True)
class ServiceCategoryConfig:
    key: ServiceCategory
    label: str
    active: bool
    execution_enabled: bool


SERVICE_CATEGORY_CONFIG: dict[ServiceCategory, ServiceCategoryConfig] = {
    ServiceCategory.MEDICAL_TRANSPORT: ServiceCategoryConfig(
        key=ServiceCategory.MEDICAL_TRANSPORT,
        label="Medical Transport",
        active=True,
        execution_enabled=True,
    ),
    ServiceCategory.RECURRING_TRANSPORT: ServiceCategoryConfig(
        key=ServiceCategory.RECURRING_TRANSPORT,
        label="Recurring Transport",
        active=True,
        execution_enabled=True,
    ),
    ServiceCategory.PROVIDER_TRANSPORT: ServiceCategoryConfig(
        key=ServiceCategory.PROVIDER_TRANSPORT,
        label="Provider Transport",
        active=True,
        execution_enabled=True,
    ),
    ServiceCategory.FUTURE_MEDICAL_LOGISTICS: ServiceCategoryConfig(
        key=ServiceCategory.FUTURE_MEDICAL_LOGISTICS,
        label="Future Medical Logistics",
        active=False,
        execution_enabled=False,
    ),
    ServiceCategory.FUTURE_PHARMACY_DELIVERY: ServiceCategoryConfig(
        key=ServiceCategory.FUTURE_PHARMACY_DELIVERY,
        label="Future Pharmacy Delivery",
        active=False,
        execution_enabled=False,
    ),
}


_SERVICE_TYPE_ALIASES: dict[str, ServiceCategory] = {
    "medical_transport": ServiceCategory.MEDICAL_TRANSPORT,
    "healthcare": ServiceCategory.MEDICAL_TRANSPORT,
    "dialysis": ServiceCategory.MEDICAL_TRANSPORT,
    "discharge": ServiceCategory.MEDICAL_TRANSPORT,
    "oncology": ServiceCategory.MEDICAL_TRANSPORT,
    "specialist": ServiceCategory.MEDICAL_TRANSPORT,
    "appointment": ServiceCategory.MEDICAL_TRANSPORT,
    "recurring_transport": ServiceCategory.RECURRING_TRANSPORT,
    "provider_transport": ServiceCategory.PROVIDER_TRANSPORT,
    "future_medical_logistics": ServiceCategory.FUTURE_MEDICAL_LOGISTICS,
    "future_pharmacy_delivery": ServiceCategory.FUTURE_PHARMACY_DELIVERY,
}


def _normalized_token(value: Any) -> str:
    token = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in token:
        token = token.replace("__", "_")
    return token


def resolve_service_category(value: Any) -> ServiceCategory | None:
    token = _normalized_token(value)
    if not token:
        return None
    try:
        return ServiceCategory(token)
    except ValueError:
        return _SERVICE_TYPE_ALIASES.get(token)


def coerce_service_category(value: Any, *, default_to_medical: bool = True) -> ServiceCategory:
    resolved = resolve_service_category(value)
    if resolved is not None:
        return resolved
    if default_to_medical:
        return ServiceCategory.MEDICAL_TRANSPORT
    raise ValueError(f"Unknown service category: {value}")


def ensure_active_service_category(value: Any) -> ServiceCategory:
    resolved = coerce_service_category(value, default_to_medical=False)
    config = SERVICE_CATEGORY_CONFIG.get(resolved)
    if not config or not config.active or not config.execution_enabled:
        raise ValueError(
            f"Service category '{resolved.value}' is inactive. "
            "Only active transportation categories can execute runtime workflows."
        )
    return resolved


def serialize_service_category(value: Any) -> str:
    return coerce_service_category(value, default_to_medical=True).value


def service_category_status() -> list[dict[str, Any]]:
    return [
        {
            "key": cfg.key.value,
            "label": cfg.label,
            "active": cfg.active,
            "execution_enabled": cfg.execution_enabled,
            "future": not cfg.active,
        }
        for cfg in SERVICE_CATEGORY_CONFIG.values()
    ]
