"""Isolated, dependency-free building blocks for Nova Intelligence.

This module is NOT registered in the application and performs no uploads, OCR,
transcription, network calls, inference, data persistence or billing. It is
intentionally safe to develop without affecting live Nova product routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class TimedObservation:
    start_seconds: float
    end_seconds: float
    kind: str
    text: str
    source_ref: str

    def __post_init__(self) -> None:
        if not (isfinite(self.start_seconds) and isfinite(self.end_seconds)):
            raise ValueError("Timestamps must be finite")
        if self.start_seconds < 0 or self.end_seconds < self.start_seconds:
            raise ValueError("Invalid timestamp interval")
        if self.kind not in {"transcript", "frame_ocr", "scene"}:
            raise ValueError("Unsupported observation kind")
        if not self.text.strip() or not self.source_ref.strip():
            raise ValueError("An observation requires text and source reference")


def timeline(observations: Iterable[TimedObservation]) -> list[dict]:
    """Return a stable time-ordered timeline with evidence references.

    No summarization is attempted: this prevents unsupported claims or
    fabricated visual events when providers are unavailable.
    """
    ordered = sorted(observations, key=lambda o: (o.start_seconds, o.end_seconds, o.kind))
    return [
        {
            "start_seconds": item.start_seconds,
            "end_seconds": item.end_seconds,
            "kind": item.kind,
            "text": item.text,
            "source_ref": item.source_ref,
        }
        for item in ordered
    ]
