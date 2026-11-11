"""Disposable SQLite fixtures test copy/rollback; live PostgreSQL is separate."""
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sqlite3
import stat

import pytest
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, MetaData, String, Table, Text, create_engine, event, select
from sqlalchemy.engine import make_url

spec = importlib.util.spec_from_file_location("studio_staging_transfer", Path(__file__).resolve().parents[1] / "scripts/migrate_studio_staging.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def databases(tmp_path):
    source_path = tmp_path / "source.sqlite"
    source = create_engine("sqlite:///" + str(source_path))
    ci_url = os.getenv("STUDIO_TRANSFER_TEST_DATABASE_URL")
    if ci_url:
        parsed = make_url(ci_url)
        assert os.getenv("GITHUB_ACTIONS") == "true"
        assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database == "studio_transfer_ci"
    destination = create_engine(ci_url or ("sqlite:///" + str(tmp_path / "destination.sqlite")))
    meta = MetaData()
    users = Table("platform_users", meta, Column("id", String, primary_key=True), Column("email", String),
                  Column("hashed_password", String), Column("is_active", Boolean), Column("created_at", DateTime(timezone=True)))
    projects = Table("nova_creative_projects", meta, Column("id", String, primary_key=True),
                     Column("owner_id", String, ForeignKey("platform_users.id")), Column("metadata_json", Text))
    assets = Table("nova_creative_assets", meta, Column("id", String, primary_key=True),
                   Column("owner_id", String, ForeignKey("platform_users.id")), Column("project_id", String, ForeignKey("nova_creative_projects.id")), Column("url", Text))
    jobs = Table("nova_creative_jobs", meta, Column("id", String, primary_key=True), Column("status", String))
    tokens = Table("platform_refresh_tokens", meta, Column("id", String, primary_key=True), Column("token_hash", String))
    meta.create_all(source)
    meta.create_all(destination)
    with source.begin() as conn:
        conn.execute(users.insert(), {"id": "owner", "email": "fixture@example.com", "hashed_password": "fixture-password-hash",
                                      "is_active": True, "created_at": datetime(2026, 11, 10, tzinfo=timezone.utc)})
        conn.execute(projects.insert(), {"id": "project", "owner_id": "owner", "metadata_json": '{"approval":true}'})
        conn.execute(assets.insert(), {"id": "asset", "owner_id": "owner", "project_id": "project",
                                       "url": "private-studio-s3://owner/project/imported_video_fixture.mp4"})
        conn.execute(tokens.insert(), {"id": "refresh", "token_hash": "excluded-session"})
    try:
        yield source_path, source, destination, meta
    finally:
        meta.drop_all(destination)  # only this fixture's disposable tables
        source.dispose()
        destination.dispose()


def test_dry_run_never_copies_records_or_sessions(databases):
    path, source, destination, meta = databases
    report = module.transfer(path, destination)
    assert report["mode"] == "dry_run"
    assert {row["table"] for row in report["tables"]} == set(meta.tables) - {"platform_refresh_tokens"}
    with destination.connect() as conn:
        for table in meta.tables.values():
            assert conn.execute(select(table)).all() == []


def test_apply_preserves_account_ownership_metadata_and_file_refs_with_private_backup(databases, tmp_path):
    path, source, destination, meta = databases
    report = module.transfer(path, destination, apply=True, backup_directory=tmp_path / "backups")
    assert report["verified"] is True
    backup = Path(report["backup"])
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM platform_users").fetchone()[0] == 1
    with destination.connect() as conn:
        account = conn.execute(select(meta.tables["platform_users"])).mappings().one()
        asset = conn.execute(select(meta.tables["nova_creative_assets"])).mappings().one()
        assert account["hashed_password"] == "fixture-password-hash"
        assert account["is_active"] is True
        assert asset["owner_id"] == "owner" and asset["project_id"] == "project"
        assert asset["url"].startswith("private-studio-s3://owner/project/")
        assert conn.execute(select(meta.tables["platform_refresh_tokens"])).all() == []
    with source.connect() as conn:
        assert conn.execute(select(meta.tables["platform_users"])).mappings().one()["hashed_password"] == "fixture-password-hash"


def test_foreign_key_order_places_users_before_projects_before_assets(databases, tmp_path):
    path, source, destination, meta = databases
    names = ["nova_creative_assets", "nova_creative_projects", "platform_users"]
    order = module._dependency_order(names, {name: meta.tables[name] for name in names})
    assert order.index("platform_users") < order.index("nova_creative_projects")
    assert order.index("nova_creative_projects") < order.index("nova_creative_assets")
    report = module.transfer(path, destination, apply=True, backup_directory=tmp_path / "backups")
    assert report["verified"] is True


def test_cyclic_foreign_keys_block_without_copying(tmp_path):
    meta = MetaData()
    first = Table("nova_creative_first", meta, Column("id", String, primary_key=True),
                  Column("other_id", String, ForeignKey("nova_creative_second.id")))
    second = Table("nova_creative_second", meta, Column("id", String, primary_key=True),
                   Column("other_id", String, ForeignKey("nova_creative_first.id")))
    with pytest.raises(module.TransferBlocked, match="CYCLIC_STUDIO_FOREIGN_KEYS"):
        module._dependency_order(["nova_creative_first", "nova_creative_second"],
                                 {"nova_creative_first": first, "nova_creative_second": second})


def test_existing_destination_is_never_overwritten(databases, tmp_path):
    path, source, destination, meta = databases
    with destination.begin() as conn:
        conn.execute(meta.tables["platform_users"].insert(), {"id": "existing", "email": "existing@example.com"})
    with pytest.raises(module.TransferBlocked, match="TARGET_NOT_EMPTY"):
        module.transfer(path, destination, apply=True, backup_directory=tmp_path / "backups")
    with destination.connect() as conn:
        assert conn.execute(select(meta.tables["nova_creative_assets"])).all() == []
        assert conn.execute(select(meta.tables["platform_users"].c.id)).scalar_one() == "existing"


def test_second_transfer_refuses_to_overwrite_successful_copy(databases, tmp_path):
    path, source, destination, meta = databases
    first = module.transfer(path, destination, apply=True, backup_directory=tmp_path / "first")
    assert first["verified"] is True
    with pytest.raises(module.TransferBlocked, match="TARGET_NOT_EMPTY"):
        module.transfer(path, destination, apply=True, backup_directory=tmp_path / "second")
    assert not (tmp_path / "second").exists()
    with destination.connect() as conn:
        assert conn.execute(select(meta.tables["platform_users"])).all()
        assert conn.execute(select(meta.tables["nova_creative_assets"])).all()


def test_nonempty_projects_destination_is_rejected(databases, tmp_path):
    path, source, destination, meta = databases
    with destination.begin() as conn:
        conn.execute(meta.tables["nova_creative_projects"].insert(),
                     {"id": "unrelated", "owner_id": None, "metadata_json": "{}"})
    with pytest.raises(module.TransferBlocked, match="TARGET_NOT_EMPTY"):
        module.transfer(path, destination, apply=True, backup_directory=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_apply_requires_backup_directory(databases):
    path, source, destination, meta = databases
    with pytest.raises(module.TransferBlocked, match="BACKUP_DIRECTORY_REQUIRED"):
        module.transfer(path, destination, apply=True)
    with destination.connect() as conn:
        assert conn.execute(select(meta.tables["platform_users"])).all() == []


def test_mid_copy_failure_rolls_back_all_destination_rows(databases, tmp_path):
    path, source, destination, meta = databases
    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO nova_creative_projects"):
            raise RuntimeError("injected destination failure")
    event.listen(destination, "before_cursor_execute", fail)
    with pytest.raises(RuntimeError, match="injected destination failure"):
        module.transfer(path, destination, apply=True, backup_directory=tmp_path / "backups")
    event.remove(destination, "before_cursor_execute", fail)
    with destination.connect() as conn:
        for table in meta.tables.values():
            assert conn.execute(select(table)).all() == []
    assert list((tmp_path / "backups").glob("*.sqlite"))


def test_active_render_blocks_transfer(databases):
    path, source, destination, meta = databases
    with source.begin() as conn:
        conn.execute(meta.tables["nova_creative_jobs"].insert(), {"id": "pending", "status": "RUNNING"})
    with pytest.raises(module.TransferBlocked, match="SOURCE_HAS_ACTIVE_RENDER_JOBS"):
        module.transfer(path, destination)


def test_schema_drift_never_silently_discards_source_columns(databases):
    path, source, destination, meta = databases
    with destination.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE nova_creative_projects DROP COLUMN metadata_json")
    with pytest.raises(module.TransferBlocked, match="INCOMPATIBLE_TARGET_SCHEMA"):
        module.transfer(path, destination)


def test_checksum_failure_rolls_back_the_entire_transfer(databases, tmp_path):
    path, source, destination, meta = databases
    def corrupt(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO nova_creative_assets"):
            connection.exec_driver_sql("UPDATE nova_creative_assets SET url='corrupted-fixture-reference'")
    event.listen(destination, "after_cursor_execute", corrupt)
    with pytest.raises(module.TransferBlocked, match="COPIED_DATA_VERIFICATION_FAILED"):
        module.transfer(path, destination, apply=True, backup_directory=tmp_path / "backups")
    event.remove(destination, "after_cursor_execute", corrupt)
    with destination.connect() as conn:
        assert conn.execute(select(meta.tables["nova_creative_assets"])).all() == []


@pytest.mark.parametrize(("environment", "host", "database", "url", "code"), [
    ("production", "ep-staging.neon.tech", "staging", "postgresql://u:p@ep-staging.neon.tech/staging?sslmode=require", "STAGING_ONLY"),
    ("staging", "ep-other.neon.tech", "staging", "postgresql://u:p@ep-staging.neon.tech/staging?sslmode=require", "TARGET_IDENTITY_MISMATCH"),
    ("staging", "ep-staging.neon.tech", "staging", "postgresql://u:p@ep-staging.neon.tech/staging?sslmode=disable", "VERIFIED_ENCRYPTED_NEON_TARGET_REQUIRED"),
    ("staging", "ep-staging-pooler.neon.tech", "staging", "postgresql://u:p@ep-staging-pooler.neon.tech/staging?sslmode=require", "DIRECT_MIGRATION_CONNECTION_REQUIRED"),
])
def test_target_guards_block_wrong_or_unencrypted_destinations(environment, host, database, url, code):
    with pytest.raises(module.TransferBlocked, match=code):
        module.validate_target(environment, url, host, database)
