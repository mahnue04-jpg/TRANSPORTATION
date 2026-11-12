"""Offline, read-only verification of an exported Studio SQLite + media archive.

Runs on a trusted machine with backup copies. Never contacts Render, Neon, R2,
or providers; never extracts media or prints private paths, owners or records.
The original backup files are never opened for writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile


class RestoreBlocked(RuntimeError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(path: Path, kind: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise RestoreBlocked(kind + "_MISSING_OR_SYMLINK")


def _check_media(archive: Path) -> int:
    _safe_file(archive, "MEDIA_ARCHIVE")
    files = 0
    total_bytes = 0
    max_archive_bytes = 8 * 1024 * 1024 * 1024
    max_files = 100000
    seen = set()
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            for item in tar:
                parts = Path(item.name).parts
                if (not parts or item.name.startswith("/") or
                        any(part in {"..", ""} for part in parts) or
                        parts[0] not in {"nova_creative_media", "nova_creative_media-private-imports"} or
                        item.issym() or item.islnk() or item.isdev() or item.isfifo()):
                    raise RestoreBlocked("UNSAFE_MEDIA_ARCHIVE_ENTRY")
                if not (item.isfile() or item.isdir()):
                    raise RestoreBlocked("UNSUPPORTED_MEDIA_ARCHIVE_ENTRY")
                if item.name in seen:
                    raise RestoreBlocked("DUPLICATE_MEDIA_ARCHIVE_ENTRY")
                seen.add(item.name)
                if item.isfile():
                    files += 1
                    if files > max_files or item.size < 0 or item.size > max_archive_bytes - total_bytes:
                        raise RestoreBlocked("MEDIA_ARCHIVE_LIMIT_EXCEEDED")
                    total_bytes += item.size
                    # Read every compressed member to surface truncated media archives.
                    stream = tar.extractfile(item)
                    if stream is None:
                        raise RestoreBlocked("UNREADABLE_MEDIA_ARCHIVE_ENTRY")
                    with stream:
                        observed = 0
                        while chunk := stream.read(1024 * 1024):
                            observed += len(chunk)
                        if observed != item.size:
                            raise RestoreBlocked("MEDIA_ARCHIVE_ENTRY_TRUNCATED")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise RestoreBlocked("MEDIA_ARCHIVE_INVALID") from exc
    return files


def verify(database: Path, media: Path | None = None,
           expected_db_sha256: str | None = None,
           expected_media_sha256: str | None = None,
           expected_media_files: int | None = None) -> dict:
    _safe_file(database, "DATABASE_BACKUP")
    if expected_db_sha256 and _hash(database) != expected_db_sha256.lower():
        raise RestoreBlocked("DATABASE_CHECKSUM_MISMATCH")
    if media is not None:
        _safe_file(media, "MEDIA_ARCHIVE")
        if expected_media_sha256 and _hash(media) != expected_media_sha256.lower():
            raise RestoreBlocked("MEDIA_CHECKSUM_MISMATCH")
    # A temporary, isolated restore validates the SQLite backup can be copied and
    # opened without modifying or replacing the source.
    with tempfile.TemporaryDirectory(prefix="studio-restore-") as location:
        restored = Path(location) / "restored.sqlite"
        uri = database.resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=5) as source:
                with sqlite3.connect(restored) as target:
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RestoreBlocked("RESTORED_DATABASE_INTEGRITY_FAILED")
                    names = {row[0] for row in target.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
                    required = {"platform_users", "nova_creative_projects",
                                "nova_creative_assets"}
                    if not required.issubset(names):
                        raise RestoreBlocked("STUDIO_TABLES_MISSING")
                    # Counts only; never emit record content or owner identifiers.
                    counts = {}
                    for name in sorted(n for n in names if n == "platform_users"
                                       or n.startswith("nova_creative_")):
                        safe_name = '"' + name.replace('"', '""') + '"'
                        counts[name] = target.execute(
                            "SELECT COUNT(*) FROM " + safe_name).fetchone()[0]
        except sqlite3.Error as exc:
            raise RestoreBlocked("DATABASE_RESTORE_FAILED") from exc
    result = {"database_restore": "pass", "database_integrity": "pass",
              "studio_table_counts": counts, "originals_modified": False}
    if media is not None:
        result["media_archive_read"] = "pass"
        result["media_archive_files"] = _check_media(media)
        if expected_media_files is not None and result["media_archive_files"] != expected_media_files:
            raise RestoreBlocked("MEDIA_FILE_COUNT_MISMATCH")
        result["media_extracted"] = False
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--expected-db-sha256")
    parser.add_argument("--expected-media-sha256")
    parser.add_argument("--expected-media-files", type=int)
    args = parser.parse_args(argv)
    try:
        print(json.dumps({"status": "passed", "checks": verify(
            args.database, args.media,
            args.expected_db_sha256, args.expected_media_sha256,
            args.expected_media_files)}, sort_keys=True))
        return 0
    except RestoreBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 1
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "RESTORE_VERIFICATION_FAILED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
