"""Back up and transfer Studio staging records to an EMPTY prepared database.

Dry-run by default. Never changes deployment settings, creates schema, copies
refresh tokens, or submits provider work. The original SQLite file stays intact.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3

from sqlalchemy import Boolean, Date, DateTime, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url


class TransferBlocked(RuntimeError):
    """Fixed diagnostic codes only: never include record contents or credentials."""


def validate_target(environment: str, url: str, expected_host: str, expected_database: str) -> str:
    parsed = make_url(url)
    if environment != "staging":
        raise TransferBlocked("STAGING_ONLY")
    if parsed.get_backend_name() != "postgresql" or not expected_host or not expected_database:
        raise TransferBlocked("EXPLICIT_POSTGRES_TARGET_REQUIRED")
    if parsed.host != expected_host or parsed.database != expected_database:
        raise TransferBlocked("TARGET_IDENTITY_MISMATCH")
    if not (parsed.host or "").endswith(".neon.tech") or parsed.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise TransferBlocked("VERIFIED_ENCRYPTED_NEON_TARGET_REQUIRED")
    if "-pooler" in (parsed.host or ""):
        raise TransferBlocked("DIRECT_MIGRATION_CONNECTION_REQUIRED")
    return parsed.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


def _normalize(value, column):
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        if value not in (True, False, 0, 1):
            raise TransferBlocked("INVALID_BOOLEAN_VALUE")
        return bool(value)
    if isinstance(column.type, DateTime):
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(result, datetime):
            raise TransferBlocked("INVALID_DATETIME_VALUE")
        if column.type.timezone:
            return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
        return result
    if isinstance(column.type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _canonical(value):
    if isinstance(value, datetime):
        # SQLite drops timezone annotations; the application stores UTC.
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return {"bytes_b64": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _digest_rows(connection, table, columns):
    digest = hashlib.sha256()
    count = 0
    query = select(*(table.c[name] for name in columns)).order_by(*table.primary_key.columns)
    for row in connection.execute(query).mappings():
        payload = {name: _canonical(row[name]) for name in columns}
        digest.update(json.dumps(payload, sort_keys=True, allow_nan=False, separators=(",", ":")).encode())
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def _backup(source_path: Path, directory: Path) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / ("studio_before_postgres_" + secrets.token_hex(10) + ".sqlite")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(path) as backup:
        original.backup(backup)
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise TransferBlocked("BACKUP_INTEGRITY_FAILED")
    return path


def transfer(source_path: Path, target_engine, *, apply=False, backup_directory: Path | None = None):
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise TransferBlocked("SOURCE_DATABASE_MISSING")
    source_engine = create_engine("sqlite:///" + str(source_path), connect_args={"timeout": 5})
    try:
        with source_engine.connect() as source, target_engine.begin() as target:
            # Hold existing writers while taking the backup and reading rows.
            # No source data is changed; closing this connection releases the lock.
            source.exec_driver_sql("BEGIN IMMEDIATE")
            names = sorted(name for name in inspect(source).get_table_names()
                           if name == "platform_users" or name.startswith("nova_creative_"))
            if "platform_users" not in names or "nova_creative_projects" not in names:
                raise TransferBlocked("STUDIO_SOURCE_TABLES_MISSING")
            if "nova_creative_jobs" in names:
                active = source.execute(text("SELECT count(*) FROM nova_creative_jobs WHERE upper(status) IN ('QUEUED','RUNNING','PROCESSING')")).scalar_one()
                if active:
                    raise TransferBlocked("SOURCE_HAS_ACTIVE_RENDER_JOBS")
            existing = set(inspect(target).get_table_names())
            if set(names) - existing:
                raise TransferBlocked("PREPARE_TARGET_SCHEMA_FIRST")
            if target.dialect.name == "postgresql":
                quote = target.dialect.identifier_preparer.quote
                target.execute(text("LOCK TABLE " + ",".join(quote(name) for name in names) + " IN ACCESS EXCLUSIVE MODE"))
            source_tables = {name: Table(name, MetaData(), autoload_with=source) for name in names}
            target_tables = {name: Table(name, MetaData(), autoload_with=target) for name in names}
            plan = []
            for name in names:
                src, dst = source_tables[name], target_tables[name]
                if not src.primary_key.columns or set(src.c.keys()) - set(dst.c.keys()):
                    raise TransferBlocked("INCOMPATIBLE_TARGET_SCHEMA")
                if list(src.primary_key.columns.keys()) != list(dst.primary_key.columns.keys()):
                    raise TransferBlocked("INCOMPATIBLE_TARGET_PRIMARY_KEY")
                for column in dst.c:
                    if column.name not in src.c and not column.nullable and column.server_default is None:
                        raise TransferBlocked("REQUIRED_TARGET_COLUMN_MISSING_FROM_SOURCE")
                if target.execute(select(func.count()).select_from(dst)).scalar_one():
                    raise TransferBlocked("TARGET_NOT_EMPTY")
                plan.append({"table": name, "rows": source.execute(select(func.count()).select_from(src)).scalar_one()})
            report = {"mode": "apply" if apply else "dry_run", "tables": plan,
                      "scope": "Studio records and platform_users; refresh tokens and other modules excluded"}
            if not apply:
                return report
            if backup_directory is None:
                raise TransferBlocked("BACKUP_DIRECTORY_REQUIRED")
            report["backup"] = str(_backup(source_path, backup_directory))
            for item in plan:
                name = item["table"]
                src, dst = source_tables[name], target_tables[name]
                rows = source.execute(select(src).order_by(*src.primary_key.columns)).mappings()
                expected = hashlib.sha256()
                while batch := rows.fetchmany(200):
                    normalized = [{key: _normalize(row[key], dst.c[key]) for key in src.c.keys()} for row in batch]
                    for row in normalized:
                        expected.update(json.dumps({key: _canonical(value) for key, value in row.items()},
                                                   sort_keys=True, allow_nan=False, separators=(",", ":")).encode())
                        expected.update(b"\n")
                    target.execute(dst.insert(), normalized)
                count, checksum = _digest_rows(target, dst, list(src.c.keys()))
                if count != item["rows"] or checksum != expected.hexdigest():
                    raise TransferBlocked("COPIED_DATA_VERIFICATION_FAILED")
            report["verified"] = True
            return report  # target transaction commits only after all tables verify
    finally:
        source_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-target-host", required=True)
    parser.add_argument("--expected-target-database", required=True)
    parser.add_argument("--backup-directory", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        url = validate_target(os.getenv("APP_ENV", ""), os.getenv("NOVA_STAGING_TARGET_DATABASE_URL", ""),
                              args.expected_target_host, args.expected_target_database)
        target = create_engine(url, connect_args={"connect_timeout": 15})
        try:
            result = transfer(args.source, target, apply=args.apply, backup_directory=args.backup_directory)
        finally:
            target.dispose()
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc) if isinstance(exc, TransferBlocked) else type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
