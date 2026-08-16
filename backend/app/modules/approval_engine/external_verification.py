"""Configurable external verification adapters for BASE onboarding.

No commercial vendor is selected or hardcoded. Adapters are configuration points
so Amicor can plug in providers after business/legal review. AI must never
manufacture verification results through these adapters.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from app.modules.approval_engine.statuses import ACTOR_TYPES

# Canonical external verification lifecycle (BASE and future tiers).
EXTERNAL_VERIFICATION_STATUSES = frozenset(
    {
        "NOT_STARTED",
        "ACTION_REQUIRED",
        "SUBMITTED",
        "PENDING_EXTERNAL",
        "VERIFIED",
        "CLEARED",
        "FAILED",
        "DISQUALIFIED",
        "EXPIRED",
        "MANUAL_REVIEW",
    }
)

PROTECTED_EXTERNAL_REQUIREMENT_KEYS = frozenset({"mvr", "background_study", "fingerprint"})
TERMINAL_EXTERNAL_RESULTS = frozenset(
    {"VERIFIED", "CLEARED", "FAILED", "DISQUALIFIED", "EXPIRED"}
)

# Requirement keys that use external / provider / manual verification adapters for BASE.
BASE_EXTERNAL_REQUIREMENT_KEYS = (
    "drivers_license",
    "mvr",
    "vehicle_insurance",
    "vehicle_registration",
    "vehicle_inspection",
    "base_training",
    "contractor_agreement",
    "w9",
    "payout_setup",
    "medical_qualification",  # adapter present; only blocking when authoritative rules apply
)

# Kept separate from BASE activation unless later authoritative rules apply.
NON_BASE_EXTERNAL_REQUIREMENT_KEYS = (
    "background_study",
    "fingerprint",
    "sts_training",
    "mhcp_credentialing",
)

# Map AI/legacy requirement statuses into external lifecycle values.
_LEGACY_TO_EXTERNAL = {
    "PENDING": "NOT_STARTED",
    "MISSING": "ACTION_REQUIRED",
    "MISSING_CONSENT": "ACTION_REQUIRED",
    "NOT_STARTED": "ACTION_REQUIRED",
    "PENDING_EXTERNAL": "PENDING_EXTERNAL",
    "PENDING_VERIFICATION": "PENDING_EXTERNAL",
    "IN_PROGRESS": "SUBMITTED",
    "COMPLETE": "VERIFIED",
    "VERIFIED": "VERIFIED",
    "CLEARED": "CLEARED",
    "FAILED": "FAILED",
    "DISQUALIFIED": "DISQUALIFIED",
    "EXPIRED": "EXPIRED",
    "REQUIRED": "ACTION_REQUIRED",
    "NOT_REQUIRED": "NOT_STARTED",
    "FUTURE": "NOT_STARTED",
    "UNKNOWN": "ACTION_REQUIRED",
    "MANUAL_REVIEW": "MANUAL_REVIEW",
    "SUBMITTED": "SUBMITTED",
    "ACTION_REQUIRED": "ACTION_REQUIRED",
}


def normalize_external_status(status: str | None) -> str:
    raw = str(status or "NOT_STARTED").strip().upper()
    if raw in EXTERNAL_VERIFICATION_STATUSES:
        return raw
    return _LEGACY_TO_EXTERNAL.get(raw, "ACTION_REQUIRED")


def traffic_for_external_status(status: str) -> str:
    normalized = normalize_external_status(status)
    if normalized in {"VERIFIED", "CLEARED"}:
        return "green"
    if normalized in {"PENDING_EXTERNAL", "SUBMITTED", "MANUAL_REVIEW"}:
        return "yellow"
    if normalized == "NOT_STARTED":
        return "red"
    # ACTION_REQUIRED, FAILED, DISQUALIFIED, EXPIRED
    return "red"


def is_externally_satisfied(status: str | None) -> bool:
    return normalize_external_status(status) in {"VERIFIED", "CLEARED"}


@dataclass
class ExternalVerificationRecord:
    """Evidence packet for an external/manual verification outcome."""

    requirement_key: str
    status: str
    evidence_source: str | None = None
    provider_key: str | None = None
    provider_reference_id: str | None = None
    verification_date: date | None = None
    expiration_date: date | None = None
    reviewer_source: str = "EXTERNAL"  # AI | USER | SYSTEM | EXTERNAL
    reviewer_id: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ExternalVerificationRecord":
        status = normalize_external_status(self.status)
        reviewer = str(self.reviewer_source or "EXTERNAL").upper()
        if reviewer not in ACTOR_TYPES:
            reviewer = "EXTERNAL"
        if status in {"VERIFIED", "CLEARED"} and not (self.evidence_source or self.provider_reference_id):
            raise ValueError(
                "VERIFIED/CLEARED external results require evidence_source and/or provider_reference_id"
            )
        if reviewer == "AI" and status in TERMINAL_EXTERNAL_RESULTS:
            raise ValueError(
                "AI must not manufacture external verification results "
                f"(attempted {status} for {self.requirement_key})"
            )
        if (
            reviewer == "SYSTEM"
            and self.requirement_key in PROTECTED_EXTERNAL_REQUIREMENT_KEYS
            and status in {"VERIFIED", "CLEARED"}
        ):
            raise ValueError(
                "Automatic internal logic must not mark MVR, background study, or fingerprint "
                f"as {status}"
            )
        return ExternalVerificationRecord(
            requirement_key=self.requirement_key,
            status=status,
            evidence_source=self.evidence_source,
            provider_key=self.provider_key,
            provider_reference_id=self.provider_reference_id,
            verification_date=self.verification_date,
            expiration_date=self.expiration_date,
            reviewer_source=reviewer,
            reviewer_id=self.reviewer_id,
            notes=self.notes,
            metadata=dict(self.metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self.normalized())
        if payload.get("verification_date"):
            payload["verification_date"] = payload["verification_date"].isoformat()
        if payload.get("expiration_date"):
            payload["expiration_date"] = payload["expiration_date"].isoformat()
        return payload


@dataclass
class AdapterCapability:
    provider_key: str
    label: str
    mode: str  # "manual" | "configurable_provider" | "unconfigured"
    requirement_keys: tuple[str, ...]
    can_submit: bool
    can_poll: bool
    vendor_selected: bool
    notes: str


class ExternalVerificationAdapter(ABC):
    """Provider/manual adapter interface — no vendor hardcoding."""

    provider_key: str
    label: str
    mode: str

    @abstractmethod
    def capability(self) -> AdapterCapability:
        raise NotImplementedError

    @abstractmethod
    def submit(
        self,
        *,
        organization_id: str,
        case_id: str,
        requirement_key: str,
        payload: dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> ExternalVerificationRecord:
        """Submit a verification request to an external/manual queue.

        Must not invent a VERIFIED/FAILED result.
        """
        raise NotImplementedError

    @abstractmethod
    def record_result(
        self,
        *,
        organization_id: str,
        case_id: str,
        record: ExternalVerificationRecord,
    ) -> ExternalVerificationRecord:
        """Record an authoritative external/manual result with evidence."""
        raise NotImplementedError

    def poll(
        self,
        *,
        organization_id: str,
        case_id: str,
        requirement_key: str,
        provider_reference_id: str | None = None,
    ) -> ExternalVerificationRecord | None:
        """Optional poll. Default: not supported (returns None)."""
        return None


class ManualVerificationAdapter(ExternalVerificationAdapter):
    """Human/ops-driven verification until a vendor is selected."""

    provider_key = "manual"
    label = "Manual / ops verification"
    mode = "manual"

    def __init__(self, requirement_keys: tuple[str, ...]):
        self._keys = requirement_keys

    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            provider_key=self.provider_key,
            label=self.label,
            mode=self.mode,
            requirement_keys=self._keys,
            can_submit=True,
            can_poll=False,
            vendor_selected=False,
            notes=(
                "No commercial vendor selected. Operators submit requests and record "
                "authoritative results with evidence after business/legal review."
            ),
        )

    def submit(
        self,
        *,
        organization_id: str,
        case_id: str,
        requirement_key: str,
        payload: dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> ExternalVerificationRecord:
        if requirement_key not in self._keys:
            raise ValueError(f"Manual adapter does not cover {requirement_key}")
        return ExternalVerificationRecord(
            requirement_key=requirement_key,
            status="PENDING_EXTERNAL",
            evidence_source="manual_queue",
            provider_key=self.provider_key,
            provider_reference_id=(payload or {}).get("provider_reference_id"),
            reviewer_source="USER",
            reviewer_id=actor_id,
            notes=(payload or {}).get("notes")
            or "Submitted to manual verification queue — awaiting authoritative result",
            metadata={"organization_id": organization_id, "case_id": case_id, "mode": "manual"},
        ).normalized()

    def record_result(
        self,
        *,
        organization_id: str,
        case_id: str,
        record: ExternalVerificationRecord,
    ) -> ExternalVerificationRecord:
        if record.requirement_key not in self._keys:
            raise ValueError(f"Manual adapter does not cover {record.requirement_key}")
        normalized = record.normalized()
        if normalized.provider_key is None:
            normalized.provider_key = self.provider_key
        normalized.metadata = {
            **(normalized.metadata or {}),
            "organization_id": organization_id,
            "case_id": case_id,
            "mode": "manual",
        }
        return normalized


class ConfigurableProviderAdapter(ExternalVerificationAdapter):
    """Configuration point for a future vendor — not selected/connected yet."""

    def __init__(self, *, provider_key: str, requirement_keys: tuple[str, ...], label: str | None = None):
        self.provider_key = provider_key
        self.label = label or f"Configurable provider ({provider_key})"
        self.mode = "configurable_provider"
        self._keys = requirement_keys

    def capability(self) -> AdapterCapability:
        configured = self.provider_key not in {"", "unconfigured", "none", "manual"}
        return AdapterCapability(
            provider_key=self.provider_key,
            label=self.label,
            mode="unconfigured" if not configured else self.mode,
            requirement_keys=self._keys,
            can_submit=False,
            can_poll=False,
            vendor_selected=False,
            notes=(
                "Provider key reserved as a configuration point only. "
                "No vendor credentials, API calls, or results are active until Amicor "
                "selects a vendor after business/legal review."
            ),
        )

    def submit(self, **kwargs: Any) -> ExternalVerificationRecord:
        raise ValueError(
            f"Provider '{self.provider_key}' is not connected. "
            "Select and configure a vendor after business/legal review, or use the manual adapter."
        )

    def record_result(
        self,
        *,
        organization_id: str,
        case_id: str,
        record: ExternalVerificationRecord,
    ) -> ExternalVerificationRecord:
        # Still allow recording if an external human attaches evidence while vendor is pending selection.
        # This does not invent a vendor API response.
        normalized = record.normalized()
        if normalized.reviewer_source == "AI":
            raise ValueError("AI cannot record provider results")
        normalized.provider_key = normalized.provider_key or self.provider_key
        normalized.metadata = {
            **(normalized.metadata or {}),
            "organization_id": organization_id,
            "case_id": case_id,
            "mode": "configurable_provider_unconnected",
        }
        return normalized


def _env_provider_key(requirement_key: str) -> str:
    env_name = f"AMICOR_EXT_VERIFY_{requirement_key.upper()}_PROVIDER"
    value = str(os.getenv(env_name, "manual") or "manual").strip().lower()
    return value or "manual"


def build_adapter_registry() -> dict[str, ExternalVerificationAdapter]:
    """Map each BASE external requirement to a configurable adapter (default: manual)."""
    registry: dict[str, ExternalVerificationAdapter] = {}
    for key in BASE_EXTERNAL_REQUIREMENT_KEYS:
        provider = _env_provider_key(key)
        if provider in {"manual", "ops", "human"}:
            registry[key] = ManualVerificationAdapter((key,))
        else:
            # Named configuration slot only — not a selected commercial vendor integration.
            registry[key] = ConfigurableProviderAdapter(
                provider_key=provider,
                requirement_keys=(key,),
                label=f"Configured slot '{provider}' for {key} (not connected)",
            )
    # Separate non-BASE adapters exist as manual placeholders but are not BASE activation criteria.
    for key in NON_BASE_EXTERNAL_REQUIREMENT_KEYS:
        registry[key] = ManualVerificationAdapter((key,))
    return registry


def list_adapter_capabilities() -> list[dict[str, Any]]:
    registry = build_adapter_registry()
    rows: list[dict[str, Any]] = []
    for key in list(BASE_EXTERNAL_REQUIREMENT_KEYS) + list(NON_BASE_EXTERNAL_REQUIREMENT_KEYS):
        adapter = registry[key]
        cap = adapter.capability()
        rows.append(
            {
                "requirement_key": key,
                "base_activation": key in BASE_EXTERNAL_REQUIREMENT_KEYS,
                "provider_key": cap.provider_key,
                "label": cap.label,
                "mode": cap.mode,
                "can_submit": cap.can_submit,
                "can_poll": cap.can_poll,
                "vendor_selected": cap.vendor_selected,
                "notes": cap.notes,
                "config_env": f"AMICOR_EXT_VERIFY_{key.upper()}_PROVIDER",
            }
        )
    return rows


def get_adapter(requirement_key: str) -> ExternalVerificationAdapter:
    registry = build_adapter_registry()
    if requirement_key not in registry:
        raise ValueError(f"No external verification adapter registered for {requirement_key}")
    return registry[requirement_key]
