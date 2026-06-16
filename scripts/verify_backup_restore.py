#!/usr/bin/env python3
"""Verify SQLite backup and restore for the live Amicor database.

Creates a backup copy of the source SQLite database, restores that backup into
a fresh SQLite file, and compares row counts plus a few anchor rows to prove
the restored database contains the same data.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


TABLES_TO_CHECK = [
    "platform_users",
    "platform_audit_logs",
    "health_isf_customer_ride_requests",
    "health_isf_drivers",
    "health_isf_rides",
    "health_isf_dispatch_assignments",
    "health_isf_payment_transactions",
    "health_isf_settlement_ledger",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def open_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def table_count(conn: sqlite3.Connection, table: str) -> int:
    cursor = conn.execute(f"SELECT COUNT(*) AS count FROM {table}")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def maybe_anchor(conn: sqlite3.Connection, table: str) -> dict[str, object] | None:
    anchors = {
        "platform_users": "SELECT id, email, role FROM platform_users ORDER BY created_at ASC LIMIT 1",
        "platform_audit_logs": "SELECT id, action, path, method, status_code FROM platform_audit_logs ORDER BY id DESC LIMIT 1",
        "health_isf_customer_ride_requests": "SELECT id, rider_name, dispatch_status FROM health_isf_customer_ride_requests ORDER BY created_at DESC LIMIT 1",
        "health_isf_drivers": "SELECT id, name, status FROM health_isf_drivers ORDER BY created_at DESC LIMIT 1",
        "health_isf_rides": "SELECT id, status, lifecycle_state, driver_id FROM health_isf_rides ORDER BY created_at DESC LIMIT 1",
        "health_isf_dispatch_assignments": "SELECT id, ride_id, driver_id, assignment_state FROM health_isf_dispatch_assignments ORDER BY created_at DESC LIMIT 1",
        "health_isf_payment_transactions": "SELECT id, ride_id, status, invoice_reference FROM health_isf_payment_transactions ORDER BY created_at DESC LIMIT 1",
        "health_isf_settlement_ledger": "SELECT id, payment_transaction_id, participant_type, status FROM health_isf_settlement_ledger ORDER BY created_at DESC LIMIT 1",
    }
    query = anchors.get(table)
    if not query:
        return None
    row = conn.execute(query).fetchone()
    return dict(row) if row else None


def compare_databases(source: sqlite3.Connection, restored: sqlite3.Connection) -> dict[str, object]:
    table_results: list[dict[str, object]] = []
    all_match = True

    for table in TABLES_TO_CHECK:
        source_count = table_count(source, table)
        restored_count = table_count(restored, table)
        source_anchor = maybe_anchor(source, table)
        restored_anchor = maybe_anchor(restored, table)
        count_match = source_count == restored_count
        anchor_match = source_anchor == restored_anchor
        match = count_match and anchor_match
        all_match = all_match and match
        table_results.append(
            {
                "table": table,
                "source_count": source_count,
                "restored_count": restored_count,
                "count_match": count_match,
                "source_anchor": source_anchor,
                "restored_anchor": restored_anchor,
                "anchor_match": anchor_match,
                "match": match,
            }
        )

    return {
        "match": all_match,
        "tables": table_results,
    }


def backup_and_restore(source_path: Path, backup_path: Path, restored_path: Path) -> dict[str, object]:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        backup_path.unlink()
    if restored_path.exists():
        restored_path.unlink()

    source = open_sqlite(source_path)
    backup = open_sqlite(backup_path)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()

    restored_source = open_sqlite(backup_path)
    restored = open_sqlite(restored_path)
    try:
        restored_source.backup(restored)
    finally:
        restored.close()
        restored_source.close()

    source_verify = open_sqlite(source_path)
    backup_verify = open_sqlite(backup_path)
    restored_verify = open_sqlite(restored_path)
    try:
        return {
            "source_path": str(source_path),
            "backup_path": str(backup_path),
            "restored_path": str(restored_path),
            "backup_exists": backup_path.exists(),
            "restored_exists": restored_path.exists(),
            "comparison": compare_databases(source_verify, restored_verify),
            "backup_comparison": compare_databases(source_verify, backup_verify),
        }
    finally:
        source_verify.close()
        backup_verify.close()
        restored_verify.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify SQLite backup and restore.")
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1] / "backend" / "data" / "chat.db"),
        help="Source SQLite database file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / ".runtime" / "backup_verification"),
        help="Directory for backup and restore artifacts.",
    )
    args = parser.parse_args(argv)

    source_path = Path(args.source)
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": f"Source database not found: {source_path}"}, indent=2))
        return 2

    output_dir = Path(args.output_dir)
    stamp = utc_stamp()
    backup_path = output_dir / f"chat-backup-{stamp}.db"
    restored_path = output_dir / f"chat-restored-{stamp}.db"

    result = backup_and_restore(source_path, backup_path, restored_path)
    result["verified_at"] = datetime.now(timezone.utc).isoformat()
    result["ok"] = bool(result["comparison"]["match"] and result["backup_comparison"]["match"])

    print(json.dumps(result, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))