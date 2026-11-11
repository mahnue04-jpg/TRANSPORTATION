"""Read-only staging Studio backup and media-reference preflight.

Does not deploy, migrate, upload, generate media, or expose account content.
A private, integrity-checked SQLite snapshot is created only with --backup.
Actual file-media bytes must be separately backed up before a database cutover.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat


class PreflightBlocked(RuntimeError):
    pass


def _connect_ro(path: Path):
    # The source is never opened in write mode or created implicitly.
    if not path.is_file() or path.is_symlink():
        raise PreflightBlocked("SOURCE_MISSING_OR_SYMLINK")
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)


def snapshot(source: Path, destination: Path):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise PreflightBlocked("BACKUP_INSIDE_SOURCE_PATH")
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    if destination.is_symlink() or (stat.S_IMODE(destination.stat().st_mode) & 0o077):
        raise PreflightBlocked("BACKUP_DIRECTORY_NOT_PRIVATE")
    backup_path = destination / ("studio_staging_" + secrets.token_hex(12) + ".sqlite")
    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with _connect_ro(source) as original, sqlite3.connect(backup_path) as copy:
            original.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PreflightBlocked("BACKUP_INTEGRITY_FAILED")
        return backup_path
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise


def inventory(path: Path) -> dict:
    with _connect_ro(path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"platform_users", "nova_creative_projects", "nova_creative_assets"}
        if not required.issubset(names):
            raise PreflightBlocked("STUDIO_TABLES_MISSING")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise PreflightBlocked("SOURCE_INTEGRITY_FAILED")
        selected = sorted(name for name in names if name == "platform_users" or name.startswith("nova_creative_"))
        counts = {}
        for name in selected:
            # Names come from sqlite_master and are explicitly escaped before interpolation.
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        if "nova_creative_jobs" in names:
            active = conn.execute(
                "SELECT COUNT(*) FROM nova_creative_jobs "
                "WHERE upper(status) IN ('QUEUED','RUNNING','PROCESSING')"
            ).fetchone()[0]
        else:
            active = 0
        cols = {row[1] for row in conn.execute('PRAGMA table_info("nova_creative_assets")')}
        refs = {"total": counts["nova_creative_assets"], "empty": 0,
                "local_on_disk": 0, "local_missing": 0, "remote_or_other": 0}
        if "url" in cols:
            for (raw,) in conn.execute("SELECT url FROM nova_creative_assets"):
                value = str(raw or "").strip()
                if not value:
                    refs["empty"] += 1
                elif value.startswith("/") or value.startswith("file://"):
                    # Do not traverse or read media. Never print URLs or local filenames.
                    candidate = Path(value[7:] if value.startswith("file://") else value)
                    if candidate.is_file():
                        refs["local_on_disk"] += 1
                    else:
                        refs["local_missing"] += 1
                else:
                    refs["remote_or_other"] += 1
        return {"tables": counts, "active_jobs": active, "asset_references": refs,
                "source_integrity": "ok"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("/data/chat.db"))
    p.add_argument("--backup-directory", type=Path)
    p.add_argument("--backup", action="store_true")
    args = p.parse_args()
    try:
        if os.getenv("APP_ENV", "").lower() not in {"staging", "stage"}:
            raise PreflightBlocked("STAGING_ONLY")
        result = inventory(args.source)
        result["mode"] = "backup" if args.backup else "inventory"
        if args.backup:
            if args.backup_directory is None:
                raise PreflightBlocked("BACKUP_DIRECTORY_REQUIRED")
            if result["active_jobs"]:
                raise PreflightBlocked("ACTIVE_JOBS_PRESENT")
            file = snapshot(args.source, args.backup_directory)
            result["backup_integrity"] = "ok"
            result["backup_created"] = True
            # The backup location is deliberately not logged.
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, PreflightBlocked) else type(error).__name__
        print(json.dumps({"status": "blocked", "reason": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
