"""No-network tests for the private, read-only Growth schema inventory."""
import pytest
from app.core.nova.growth_agent.private_schema_inventory import (
    validate_private_diagnostic_env, inspect_schema,
)


def valid_env():
    return {
        "NOVA_GA_PRIVATE_DB_DIAGNOSTIC_APPROVED": "true",
        "APP_ENV": "staging", "AMICOR_ENVIRONMENT": "staging",
        "NOVA_GA_APPROVED_STAGING_SHA": "a" * 40,
        "RENDER_GIT_COMMIT": "a" * 40,
        "DATABASE_URL": (
            "postgresql+psycopg2://fixture:secret@"
            "dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos"
        ),
    }


@pytest.mark.parametrize("field,value", [
    ("NOVA_GA_PRIVATE_DB_DIAGNOSTIC_APPROVED", "false"),
    ("APP_ENV", "production"),
    ("AMICOR_ENVIRONMENT", "production"),
    ("NOVA_GA_APPROVED_STAGING_SHA", "b" * 40),
    ("RENDER_GIT_COMMIT", "b" * 40),
    ("DATABASE_URL", "postgresql://fixture:secret@prod.invalid/amicor"),
    ("DATABASE_URL", "postgresql://fixture:secret@dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos?sslmode=disable"),
])
def test_reject_unsafe_configuration(field, value):
    env = valid_env()
    env[field] = value
    with pytest.raises(ValueError) as err:
        validate_private_diagnostic_env(env)
    assert "secret" not in str(err.value)


def test_valid_private_staging_configuration_only():
    assert validate_private_diagnostic_env(valid_env()).startswith("postgresql://")


class Cursor:
    def __init__(self, database="nova_ga_490_dispos"):
        self.calls = []
        self.database = database
        self.last = ""
    def execute(self, sql):
        assert sql.lstrip().upper().startswith("SELECT ")
        self.calls.append(sql)
        self.last = sql
    def fetchone(self):
        if "current_database()" in self.last:
            return (self.database, 180000)
        if "alembic_version" in self.last and "EXISTS" in self.last:
            return (True,)
        if "count(*)" in self.last:
            return (21,)
        return (False,)
    def fetchall(self):
        return [("20261112_nova_ga_retention",)]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class Connection:
    def __init__(self, database="nova_ga_490_dispos"):
        self.cursor_obj = Cursor(database)
        self.readonly = False
        self.rolled_back = False
        self.closed = False
    def set_session(self, readonly, autocommit):
        assert readonly is True and autocommit is False
        self.readonly = True
    def cursor(self):
        assert self.readonly
        return self.cursor_obj
    def rollback(self):
        self.rolled_back = True
    def close(self):
        self.closed = True


def test_inventory_is_readonly_and_has_no_records_or_secrets():
    conn = Connection()
    def connect(url, **kwargs):
        assert kwargs["connect_timeout"] == 8
        assert url == "test-only"
        return conn
    result = inspect_schema(connect, "test-only")
    assert result["database_identity"] == "nova_ga_490_dispos"
    assert result["alembic_heads"] == ["20261112_nova_ga_retention"]
    assert result["growth_table_count"] == 21
    assert result["campaign_review_table_exists"] is False
    assert result["backup_verified"] is False
    assert result["data_rows_examined"] == 0
    assert conn.rolled_back and conn.closed


def test_wrong_connected_db_fails_closed():
    conn = Connection(database="amicor")
    with pytest.raises(ValueError, match="Unexpected connected database"):
        inspect_schema(lambda *args, **kwargs: conn, "test-only")
    assert conn.closed


def test_restored_copy_requires_independent_approval_and_exact_identity():
    env = valid_env()
    env["NOVA_GA_DIAGNOSTIC_TARGET"] = "restored_copy"
    env["DATABASE_URL"] = (
        "postgresql+psycopg2://fixture:secret@"
        "dpg-dbuku8dckfvc73ch22e0-a/nova_ga_490_dispos_nu6s"
    )
    with pytest.raises(ValueError, match="not authorized"):
        validate_private_diagnostic_env(env)
    env["NOVA_GA_RESTORED_COPY_READ_ONLY_APPROVED"] = "true"
    assert validate_private_diagnostic_env(env).startswith("postgresql://")
    env["DATABASE_URL"] = (
        "postgresql+psycopg2://fixture:secret@"
        "dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos"
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_private_diagnostic_env(env)


def test_reject_unknown_target_and_copy_as_original():
    env = valid_env()
    env["NOVA_GA_DIAGNOSTIC_TARGET"] = "anything"
    with pytest.raises(ValueError, match="Unrecognized"):
        validate_private_diagnostic_env(env)
    env["NOVA_GA_DIAGNOSTIC_TARGET"] = "original"
    env["DATABASE_URL"] = (
        "postgresql://fixture:secret@"
        "dpg-dbuku8dckfvc73ch22e0-a/nova_ga_490_dispos_nu6s"
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_private_diagnostic_env(env)


def test_copy_inventory_uses_exact_connected_database():
    conn = Connection(database="nova_ga_490_dispos_nu6s")
    result = inspect_schema(
        lambda *args, **kwargs: conn,
        "fixture-only",
        expected_database="nova_ga_490_dispos_nu6s",
    )
    assert result["database_identity"] == "nova_ga_490_dispos_nu6s"
    assert result["read_only"] is True
    assert result["backup_verified"] is False
    assert conn.rolled_back and conn.closed


def test_copy_inventory_rejects_original_connection():
    conn = Connection(database="nova_ga_490_dispos")
    with pytest.raises(ValueError, match="Unexpected connected database"):
        inspect_schema(
            lambda *args, **kwargs: conn,
            "fixture-only",
            expected_database="nova_ga_490_dispos_nu6s",
        )
    assert conn.closed
