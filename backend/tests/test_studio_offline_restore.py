"""Disposable, offline checks for Studio backup restore acceptance."""
import hashlib
import importlib.util
from pathlib import Path
import io
import sqlite3
import tarfile

import pytest

spec = importlib.util.spec_from_file_location(
    "studio_offline_restore", Path(__file__).resolve().parents[1] /
    "scripts/verify_studio_offline_restore.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


@pytest.fixture
def backups(tmp_path):
    db = tmp_path / "backup.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE platform_users(id TEXT PRIMARY KEY);
        CREATE TABLE nova_creative_projects(id TEXT PRIMARY KEY);
        CREATE TABLE nova_creative_assets(id TEXT PRIMARY KEY);
        INSERT INTO platform_users VALUES ('private-owner');
        INSERT INTO nova_creative_projects VALUES ('private-project');
        INSERT INTO nova_creative_assets VALUES ('private-asset');
        """)
    archive = tmp_path / "media.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        data = b"synthetic-test-video-only"
        item = tarfile.TarInfo("nova_creative_media/test.mp4")
        item.size = len(data)
        tar.addfile(item, io.BytesIO(data))
    return db, archive


def test_verified_backup_isolated_without_source_changes(backups):
    db, archive = backups
    old_db, old_media = db.read_bytes(), archive.read_bytes()
    result = restore.verify(
        db, archive, hashlib.sha256(old_db).hexdigest(),
        hashlib.sha256(old_media).hexdigest())
    assert result["database_restore"] == "pass"
    assert result["database_integrity"] == "pass"
    assert result["studio_table_counts"]["platform_users"] == 1
    assert result["media_archive_files"] == 1
    assert result["originals_modified"] is False
    assert result["media_extracted"] is False
    assert db.read_bytes() == old_db and archive.read_bytes() == old_media
    assert "private-owner" not in str(result)


def test_wrong_digest_blocks_before_copy(backups):
    db, archive = backups
    with pytest.raises(restore.RestoreBlocked, match="DATABASE_CHECKSUM_MISMATCH"):
        restore.verify(db, archive, expected_db_sha256="0" * 64)


def test_missing_file_does_not_get_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(restore.RestoreBlocked, match="DATABASE_BACKUP_MISSING"):
        restore.verify(missing)
    assert not missing.exists()


def test_archive_path_traversal_rejected(backups, tmp_path):
    db, _ = backups
    bad = tmp_path / "unsafe.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        data = b"malicious-demo"
        info = tarfile.TarInfo("../escape.mp4")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(restore.RestoreBlocked, match="UNSAFE_MEDIA_ARCHIVE_ENTRY"):
        restore.verify(db, bad)
    assert not (tmp_path / "escape.mp4").exists()


def test_archive_symlink_rejected(backups, tmp_path):
    db, _ = backups
    bad = tmp_path / "symlink.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("nova_creative_media/outside")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(restore.RestoreBlocked, match="UNSAFE_MEDIA_ARCHIVE_ENTRY"):
        restore.verify(db, bad)


def test_corrupt_sqlite_rejected(tmp_path):
    db = tmp_path / "bad.sqlite"
    db.write_bytes(b"not a valid sqlite database")
    with pytest.raises(restore.RestoreBlocked, match="DATABASE_RESTORE_FAILED"):
        restore.verify(db)


def test_missing_studio_tables_rejected(tmp_path):
    db = tmp_path / "wrong.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE unrelated (x TEXT)")
    with pytest.raises(restore.RestoreBlocked, match="STUDIO_TABLES_MISSING"):
        restore.verify(db)
