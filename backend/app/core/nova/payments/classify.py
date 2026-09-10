"""Safe Stripe key-mode classification. Never returns secret values or prefixes."""
from __future__ import annotations

from dataclasses import dataclass

STATUSES = (
    "Configured",
    "Verified",
    "Missing",
    "Blocked",
    "Not verified",
    "Not applicable",
)

LIVE_PREFIXES = ("sk_live_", "rk_live_", "pk_live_")
TEST_PREFIXES = ("sk_test_", "rk_test_", "pk_test_")


@dataclass(frozen=True)
class KeyMode:
    present: bool
    mode: str | None
    status: str


def classify_key_mode(value: object) -> KeyMode:
    """Classify TEST versus LIVE from a known prefix only.

    The raw value is discarded. Unrecognized formats are Not verified.
    """
    text = str(value or "").strip()
    if not text:
        return KeyMode(present=False, mode=None, status="Missing")
    if text.startswith(LIVE_PREFIXES):
        return KeyMode(present=True, mode="LIVE", status="Configured")
    if text.startswith(TEST_PREFIXES):
        return KeyMode(present=True, mode="TEST", status="Configured")
    return KeyMode(present=True, mode=None, status="Not verified")


def modes_match(left: KeyMode, right: KeyMode) -> str:
    """Return a status for whether two classified keys share a mode."""
    if left.status == "Missing" or right.status == "Missing":
        return "Missing"
    if left.status == "Not verified" or right.status == "Not verified":
        return "Not verified"
    if left.mode and right.mode and left.mode == right.mode:
        return "Configured"
    return "Blocked"
