"""Command queue with terminal-state protection and STOP priority."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from lifesaver_home_hub.audit import now_iso

LIFECYCLE = (
    "QUEUED",
    "SENT_LOCAL",
    "RECEIVED",
    "ACKNOWLEDGED",
    "EXECUTING",
    "COMPLETED",
    "FAILED",
    "TIMED_OUT",
    "CANCELLED",
    "REJECTED",
)
TERMINAL = frozenset({"COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED", "REJECTED"})


class CommandQueue:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.by_client: dict[str, str] = {}

    def enqueue(self, command: str, *, client_command_id: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        if client_command_id and client_command_id in self.by_client:
            existing = self.items[self.by_client[client_command_id]]
            existing["idempotent"] = True
            return existing
        command_id = str(uuid4())
        row = {
            "command_id": command_id,
            "client_command_id": client_command_id,
            "command": command,
            "status": "QUEUED",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "acknowledged": False,
            "idempotent": False,
            "extra": extra or {},
        }
        self.items[command_id] = row
        if client_command_id:
            self.by_client[client_command_id] = command_id
        return row

    def advance(self, command_id: str, status: str, *, ack: bool | None = None) -> dict[str, Any]:
        row = self.items[command_id]
        if row["status"] in TERMINAL:
            return row
        if status not in LIFECYCLE:
            raise ValueError("Unknown command lifecycle status.")
        row["status"] = status
        row["updated_at"] = now_iso()
        if ack:
            row["acknowledged"] = True
        if status in {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED"}:
            row["completed_at"] = now_iso()
        return row

    def get(self, command_id: str) -> dict[str, Any] | None:
        return self.items.get(command_id)

    def cancel_pending(self, reason: str = "cancelled") -> int:
        count = 0
        for row in self.items.values():
            if row["status"] not in TERMINAL and row["command"] not in {"ROTATE_STOP", "STOP_MOTOR"}:
                row["status"] = "CANCELLED"
                row["updated_at"] = now_iso()
                row["cancel_reason"] = reason
                count += 1
        return count
