"""Operational memory persistence for telemetry and runtime notes."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


class OperationalMemory:
    def __init__(self, file_path: str | Path = "memory/data/operational_memory.json") -> None:
        self.file_path = Path(file_path)
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.file_path.exists():
                return {}
            try:
                return json.loads(self.file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}

    def save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        events = data.get("events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        data["events"] = events
        self.save(data)
        return data
