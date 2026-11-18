"""Disposable SQLite replay ledger for synthetic Nova acceptance tests ONLY.

This is not a dispatcher, production schema, durable customer store or integration.
No external I/O beyond caller-provided disposable local SQLite files.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class SyntheticReplayLedger:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.execute("PRAGMA busy_timeout=1000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS synthetic_events (
                organization_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                event_fingerprint TEXT NOT NULL,
                step INTEGER NOT NULL,
                PRIMARY KEY (organization_id, event_id),
                UNIQUE (organization_id, idempotency_key),
                UNIQUE (organization_id, correlation_id, step)
            )
        """)

    def accept(self, *, organization_id: str, correlation_id: str, event_id: str,
               idempotency_key: str, fingerprint: str, step: int) -> str:
        """Atomically record a mock step or reject replay conflicts and skipped steps.

        The fingerprint must come from a canonical, validated event serializer.
        Caller identity and approval validation must happen before calling this.
        """
        if not all(isinstance(v, str) and v for v in (
                organization_id, correlation_id, event_id, idempotency_key, fingerprint)):
            raise ValueError("nonempty synthetic ledger identifiers required")
        if type(step) is not int or not 0 <= step <= 3:
            raise ValueError("step out of synthetic scope")
        db = self.connection
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute("""
                SELECT correlation_id, idempotency_key, event_fingerprint, step
                FROM synthetic_events WHERE organization_id=? AND event_id=?
            """, (organization_id, event_id)).fetchone()
            expected = (correlation_id, idempotency_key, fingerprint, step)
            if existing is not None:
                if existing == expected:
                    db.execute("COMMIT")
                    return "duplicate"
                raise PermissionError("event id collision")
            by_key = db.execute("""
                SELECT correlation_id, event_id, event_fingerprint, step
                FROM synthetic_events WHERE organization_id=? AND idempotency_key=?
            """, (organization_id, idempotency_key)).fetchone()
            if by_key is not None:
                if by_key == (correlation_id, event_id, fingerprint, step):
                    db.execute("COMMIT")
                    return "duplicate"
                raise PermissionError("idempotency collision")
            current = db.execute("""
                SELECT MAX(step) FROM synthetic_events
                WHERE organization_id=? AND correlation_id=?
            """, (organization_id, correlation_id)).fetchone()[0]
            if step != (0 if current is None else current + 1):
                raise PermissionError("out-of-order or replayed stage")
            db.execute("""
                INSERT INTO synthetic_events
                (organization_id, correlation_id, event_id, idempotency_key, event_fingerprint, step)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (organization_id, correlation_id, event_id, idempotency_key, fingerprint, step))
            db.execute("COMMIT")
            return "accepted"
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def steps(self, organization_id: str, correlation_id: str) -> tuple[int, ...]:
        rows = self.connection.execute("""
            SELECT step FROM synthetic_events
            WHERE organization_id=? AND correlation_id=? ORDER BY step
        """, (organization_id, correlation_id))
        return tuple(row[0] for row in rows)

    def close(self):
        self.connection.close()
