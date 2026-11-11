"""Disposable validation of Studio staging inventory and backup safety."""
import os
from pathlib import Path
import sqlite3
import stat
import importlib.util

import pytest

spec = importlib.util.spec_from_file_location(
    "studio_staging_backup_preflight",
    Path(__file__).resolve().parents[1] / "scripts/studio_staging_backup_preflight.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "chat.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
          CREATE TABLE platform_users(id TEXT PRIMARY KEY);
          CREATE TABLE nova_creative_projects(id TEXT PRIMARY KEY);
          CREATE TABLE nova_creative_assets(id TEXT PRIMARY KEY, url TEXT);
          CREATE TABLE nova_creative_jobs(id TEXT PRIMARY KEY, status TEXT);
          INSERT INTO platform_users VALUES ('owner');
          INSERT INTO nova_creative_projects VALUES ('project');
          INSERT INTO nova_creative_assets VALUES ('a', '/unavailable/example.mp4');
          INSERT INTO nova_creative_assets VALUES ('b', 's3://private-bucket/object');
          INSERT INTO nova_creative_assets VALUES ('c', NULL);
        """)
    return path


def test_inventory_counts_and_redacted_media_locations(source):
    result = module.inventory(source)
    assert result["tables"]["platform_users"] == 1
    assert result["tables"]["nova_creative_assets"] == 3
    assert result["asset_references"]["local_missing"] == 1
    assert result["asset_references"]["remote_or_other"] == 1
    assert result["asset_references"]["empty"] == 1
    assert result["active_jobs"] == 0
    assert "/unavailable" not in str(result)
    assert "private-bucket" not in str(result)


def test_backup_is_private_consistent_and_source_unchanged(source, tmp_path):
    backup = module.snapshot(source, tmp_path / "private")
    assert backup.is_file()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM nova_creative_assets").fetchone()[0] == 3
    assert module.inventory(source)["tables"]["nova_creative_assets"] == 3


def test_missing_source_never_creates_database(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(module.PreflightBlocked, match="SOURCE_MISSING_OR_SYMLINK"):
        module.inventory(missing)
    assert not missing.exists()


def test_symlink_source_is_rejected(source, tmp_path):
    link = tmp_path / "link.db"
    link.symlink_to(source)
    with pytest.raises(module.PreflightBlocked, match="SOURCE_MISSING_OR_SYMLINK"):
        module.inventory(link)


def test_private_backup_directory_rejects_existing_permissive_mode(source, tmp_path):
    directory = tmp_path / "public_backup"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    with pytest.raises(module.PreflightBlocked, match="BACKUP_DIRECTORY_NOT_PRIVATE"):
        module.snapshot(source, directory)


def test_active_jobs_are_reported(source):
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO nova_creative_jobs VALUES ('j','RUNNING')")
    assert module.inventory(source)["active_jobs"] == 1


def test_missing_studio_tables_are_rejected(tmp_path):
    path = tmp_path / "empty.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE platform_users(id TEXT)")
    with pytest.raises(module.PreflightBlocked, match="STUDIO_TABLES_MISSING"):
        module.inventory(path)


def test_main_blocks_active_jobs_before_creating_backup(source, tmp_path, monkeypatch, capsys):
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO nova_creative_jobs VALUES ('busy', 'QUEUED')")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setattr(
        "sys.argv",
        ["preflight", "--source", str(source), "--backup", "--backup-directory", str(tmp_path / "backups")],
    )
    assert module.main() == 1
    assert not (tmp_path / "backups").exists()
    output = capsys.readouterr().out
    assert "ACTIVE_JOBS_PRESENT" in output


def test_main_refuses_non_staging_environment(source, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        "sys.argv",
        ["preflight", "--source", str(source), "--backup", "--backup-directory", str(tmp_path / "backups")],
    )
    assert module.main() == 1
    assert "STAGING_ONLY" in capsys.readouterr().out
    assert not (tmp_path / "backups").exists()


def test_main_discards_snapshot_with_active_jobs(source, tmp_path, monkeypatch, capsys):
    actual_snapshot = module.snapshot

    def raced_snapshot(path, dest):
        backup = actual_snapshot(path, dest)
        with sqlite3.connect(backup) as conn:
            conn.execute("INSERT INTO nova_creative_jobs VALUES ('late', 'PROCESSING')")
        return backup

    monkeypatch.setattr(module, "snapshot", raced_snapshot)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setattr(
        "sys.argv",
        ["preflight", "--source", str(source), "--backup", "--backup-directory", str(tmp_path / "backups")],
    )
    assert module.main() == 1
    assert "BACKUP_CONTAINS_ACTIVE_JOBS" in capsys.readouterr().out
    assert list((tmp_path / "backups").glob("*.sqlite")) == []


def test_main_discards_snapshot_with_changed_counts(source, tmp_path, monkeypatch, capsys):
    actual_snapshot = module.snapshot

    def raced_snapshot(path, dest):
        backup = actual_snapshot(path, dest)
        with sqlite3.connect(backup) as conn:
            conn.execute("INSERT INTO platform_users VALUES ('late')")
        return backup

    monkeypatch.setattr(module, "snapshot", raced_snapshot)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setattr(
        "sys.argv",
        ["preflight", "--source", str(source), "--backup", "--backup-directory", str(tmp_path / "backups")],
    )
    assert module.main() == 1
    assert "BACKUP_SOURCE_COUNTS_CHANGED" in capsys.readouterr().out
    assert list((tmp_path / "backups").glob("*.sqlite")) == []


def test_main_inventory_does_not_create_backup(source, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setattr("sys.argv", ["preflight", "--source", str(source)])
    assert module.main() == 0
    data = __import__("json").loads(capsys.readouterr().out)
    assert data["mode"] == "inventory"
    assert "backup_created" not in data
    assert data["tables"]["nova_creative_projects"] == 1


def test_backup_includes_committed_sqlite_wal_changes(source, tmp_path):
    # Keep a writer open so SQLite's committed updates remain in its WAL file.
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("INSERT INTO platform_users VALUES ('wal-committed')")
        writer.commit()
        backup = module.snapshot(source, tmp_path / "private_wal")
        with sqlite3.connect(backup) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT COUNT(*) FROM platform_users").fetchone()[0] == 2
    finally:
        writer.close()


def test_backup_directory_symlink_is_rejected(source, tmp_path):
    actual_directory = tmp_path / "actual_private"
    actual_directory.mkdir(mode=0o700)
    link = tmp_path / "link_directory"
    link.symlink_to(actual_directory, target_is_directory=True)
    with pytest.raises(module.PreflightBlocked, match="BACKUP_DIRECTORY_NOT_PRIVATE"):
        module.snapshot(source, link)
    assert list(actual_directory.glob("*")) == []


def test_snapshot_does_not_modify_source_content(source, tmp_path):
    original = source.read_bytes()
    module.snapshot(source, tmp_path / "private_copy")
    assert source.read_bytes() == original


def test_main_successful_backup_keeps_path_private(source, tmp_path, monkeypatch, capsys):
    private = tmp_path / "private_backups"
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setattr(
        "sys.argv",
        ["preflight", "--source", str(source), "--backup", "--backup-directory", str(private)],
    )
    assert module.main() == 0
    message = capsys.readouterr().out
    result = __import__("json").loads(message)
    assert result["backup_created"] is True
    assert result["backup_integrity"] == "ok"
    assert result["tables"]["platform_users"] == 1
    assert str(private) not in message
    assert len(list(private.glob("*.sqlite"))) == 1


def test_backup_rejects_low_disk_space_without_creating_file(source, tmp_path, monkeypatch):
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: Usage(100, 90, 10))
    destination = tmp_path / "private"
    with pytest.raises(module.PreflightBlocked, match="INSUFFICIENT_DISK_SPACE_FOR_BACKUP"):
        module.snapshot(source, destination)
    assert list(destination.glob("*.sqlite")) == []


def test_backup_accepts_sufficient_disk_headroom(source, tmp_path, monkeypatch):
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: Usage(10**10, 0, 10**10))
    backup = module.snapshot(source, tmp_path / "private")
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
