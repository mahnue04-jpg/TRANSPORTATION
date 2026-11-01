"""Non-billable spending calculations for Creative Studio.

This module deliberately performs NO provider calls and is NOT wired into paid
routes. Durable atomic reservations must be implemented before live use.
All amounts are integer USD cents; never use floating point for charging.
"""
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SpendingEntry:
    request_key: str
    reserved_cents: int
    actual_cents: int = 0
    status: str = "reserved"  # reserved, charged, released, uncertain

    def __post_init__(self) -> None:
        if not self.request_key:
            raise ValueError("request key required")
        if self.reserved_cents < 0 or self.actual_cents < 0:
            raise ValueError("negative spending is not allowed")
        if self.status not in {"reserved", "charged", "released", "uncertain"}:
            raise ValueError("invalid spending status")


def committed_cents(entries: Iterable[SpendingEntry]) -> int:
    """Conservatively count uncertain requests as fully reserved.

    Charging more than the reservation requires separate authorization.
    """
    total = 0
    for entry in entries:
        if entry.status == "released":
            continue
        total += max(entry.actual_cents, entry.reserved_cents if entry.status in {"reserved", "uncertain"} else 0)
    return total


def can_reserve(*, cap_cents: int, estimate_cents: int, request_key: str,
                entries: Iterable[SpendingEntry]) -> bool:
    if cap_cents < 0 or estimate_cents <= 0 or not request_key:
        return False
    current = tuple(entries)
    # A repeated key is not a new authorization; it must reuse the original job.
    if any(entry.request_key == request_key for entry in current):
        return False
    return committed_cents(current) + estimate_cents <= cap_cents
