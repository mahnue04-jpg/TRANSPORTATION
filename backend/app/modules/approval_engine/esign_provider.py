"""Placeholder adapter for a future contractor-agreement e-sign provider.

Phase 2B keeps typed/uploaded acceptance. This module is an interface only —
it is not live and must not be treated as a connected vendor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ESignProviderNotConfigured(RuntimeError):
    """Raised when a live e-sign provider is invoked before one is selected."""


@dataclass(frozen=True)
class ESignProviderCapability:
    provider_key: str
    purpose: str
    mode: str
    vendor_selected: bool
    live: bool
    notes: str


def esign_provider_capability() -> ESignProviderCapability:
    return ESignProviderCapability(
        provider_key="unconfigured",
        purpose="contractor_agreement_esign",
        mode="placeholder",
        vendor_selected=False,
        live=False,
        notes=(
            "No e-sign vendor is selected. Phase 2B records typed acceptance and/or "
            "an uploaded agreement copy with a version number. Do not treat this adapter as live."
        ),
    )


def start_live_esign(*, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = payload
    cap = esign_provider_capability()
    raise ESignProviderNotConfigured(cap.notes)
