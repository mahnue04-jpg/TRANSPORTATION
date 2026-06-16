"""Workflow memory persistence for task and state checkpoints."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


class WorkflowMemory:
    def __init__(self, file_path: str | Path = "memory/data/workflow_memory.json") -> None:
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

    def mark_step(self, workflow_id: str, step: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        workflows = data.get("workflows")
        if not isinstance(workflows, dict):
            workflows = {}

        history = workflows.get(workflow_id)
        if not isinstance(history, list):
            history = []
        history.append(step)
        workflows[workflow_id] = history
        data["workflows"] = workflows
        self.save(data)
        return data
