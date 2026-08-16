"""Placeholders for future secure W-9/tax and payout tokenization providers.

AMICOR must not store SSN, TIN, bank routing numbers, or bank account numbers.
These adapters are unconfigured configuration points only — no vendor, no API calls,
and no database columns for raw tax or banking identifiers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "ssn",
        "tin",
        "ein",
        "itin",
        "bank_account_number",
        "routing_number",
        "account_number",
        "iban",
    }
)


class SensitiveProviderNotConfigured(RuntimeError):
    """Raised when a future tax/payout provider is invoked without a real vendor."""


@dataclass(frozen=True)
class SensitiveProviderCapability:
    provider_key: str
    purpose: str
    mode: str
    vendor_selected: bool
    stores_raw_tax_or_bank_data: bool
    notes: str


def w9_tax_provider_capability() -> SensitiveProviderCapability:
    return SensitiveProviderCapability(
        provider_key="unconfigured",
        purpose="w9_tax",
        mode="placeholder",
        vendor_selected=False,
        stores_raw_tax_or_bank_data=False,
        notes=(
            "W-9 / tax collection remains a status flag only. "
            "Do not store SSN/TIN in AMICOR. Select a secure external tax provider later."
        ),
    )


def payout_tokenization_provider_capability() -> SensitiveProviderCapability:
    return SensitiveProviderCapability(
        provider_key="unconfigured",
        purpose="payout_tokenization",
        mode="placeholder",
        vendor_selected=False,
        stores_raw_tax_or_bank_data=False,
        notes=(
            "Payout onboarding is a status flag only. "
            "Do not collect bank routing or account numbers until a tokenization provider is selected."
        ),
    )


def list_sensitive_provider_capabilities() -> list[dict[str, Any]]:
    return [
        w9_tax_provider_capability().__dict__,
        payout_tokenization_provider_capability().__dict__,
    ]


def reject_raw_sensitive_payload(payload: dict[str, Any] | None) -> None:
    if not payload:
        return
    lowered = {str(key).strip().lower() for key in payload}
    overlap = lowered & FORBIDDEN_FIELD_NAMES
    if overlap:
        raise ValueError(
            "AMICOR must not accept SSN, TIN, or raw bank account/routing numbers. "
            f"Rejected fields: {', '.join(sorted(overlap))}"
        )


def start_w9_external_workflow(*, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reject_raw_sensitive_payload(payload)
    cap = w9_tax_provider_capability()
    raise SensitiveProviderNotConfigured(cap.notes)


def start_payout_tokenization(*, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reject_raw_sensitive_payload(payload)
    cap = payout_tokenization_provider_capability()
    raise SensitiveProviderNotConfigured(cap.notes)
