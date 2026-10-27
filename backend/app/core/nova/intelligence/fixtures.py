"""Offline synthetic meeting fixtures. No media bytes and no real people."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.nova.intelligence.ssrf import UnsafeMediaUrl, validate_https_url
from app.core.nova.intelligence.timeline import TimedObservation

_FIXTURE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Defined out of time order on purpose. Results must be sorted by timeline().
_MEETING_OBSERVATIONS = (
    TimedObservation(8.0, 8.0, "frame_ocr", "Agenda", "frame:8"),
    TimedObservation(1.0, 3.0, "transcript", "Welcome to the synthetic planning standup.", "audio:1-3"),
    TimedObservation(8.0, 12.0, "scene", "A title card labeled Synthetic Meeting stays on screen.", "frame:8-12"),
    TimedObservation(4.0, 7.0, "transcript", "The agenda on screen is fixture text.", "audio:4-7"),
)


@dataclass(frozen=True)
class SyntheticFixture:
    fixture_id: str
    status: str
    duration_seconds: float | None
    summary: str | None
    observations: tuple[TimedObservation, ...]


class UnknownFixture(Exception):
    pass


FIXTURES: dict[str, SyntheticFixture] = {
    "meeting-clip-01": SyntheticFixture(
        fixture_id="meeting-clip-01",
        status="completed",
        duration_seconds=12.0,
        summary="Fixture text: a short synthetic standup with an on-screen agenda card.",
        observations=_MEETING_OBSERVATIONS,
    ),
    "meeting-clip-empty": SyntheticFixture(
        fixture_id="meeting-clip-empty",
        status="completed",
        duration_seconds=0.0,
        summary=None,
        observations=tuple(),
    ),
    "meeting-clip-failed": SyntheticFixture(
        fixture_id="meeting-clip-failed",
        status="failed",
        duration_seconds=None,
        summary=None,
        observations=tuple(),
    ),
}

ALLOWLIST = {
    "https://fixtures.nova.invalid/synthetic/meeting-clip-01": "meeting-clip-01",
    "https://fixtures.nova.invalid/synthetic/meeting-clip-empty": "meeting-clip-empty",
    "https://fixtures.nova.invalid/synthetic/meeting-clip-failed": "meeting-clip-failed",
}


def require_known_fixture(fixture_id: object) -> SyntheticFixture:
    if not isinstance(fixture_id, str) or _FIXTURE_ID.fullmatch(fixture_id) is None:
        raise UnknownFixture()
    fixture = FIXTURES.get(fixture_id)
    if fixture is None:
        raise UnknownFixture()
    return fixture


def resolve_allowlisted_fixture(value: object) -> str:
    canonical = validate_https_url(value)
    fixture_id = ALLOWLIST.get(canonical)
    if fixture_id is None:
        raise UnsafeMediaUrl("Source URL is not allowed")
    return fixture_id
