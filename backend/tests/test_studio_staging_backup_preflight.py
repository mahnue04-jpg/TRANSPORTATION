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
