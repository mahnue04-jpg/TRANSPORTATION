"""No-connection checks for a future Nova Central PostgreSQL reader audit."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1] /
          "scripts/nova_central_reader_privilege_audit_542.py")
spec = importlib.util.spec_from_file_location("central_privilege_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("NOVA_CENTRAL_ISOLATED_TEST", raising=False)
    monkeypatch.setenv("NOVA_CENTRAL_PERMISSION_AUDIT_APPROVED", "true")
    monkeypatch.setenv("NOVA_CENTRAL_APPROVED_COMMIT", "a" * 40)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("NOVA_CENTRAL_EXPECTED_DB_HOST", "central-only.internal")
    monkeypatch.setenv("NOVA_CENTRAL_READER_DATABASE_URL",
                       "postgresql://nova_central_542_reader:fictional@central-only.internal/nova_central_542_dispos")


def test_valid_fictional_configuration_is_parsed_without_connecting(config):
    url = audit.check_target()
    assert "fictional@" in url


@pytest.mark.parametrize("field,value", [
    ("AMICOR_ENVIRONMENT", "production"),
    ("APP_ENV", "test"),
    ("NOVA_CENTRAL_ISOLATED_TEST", "1"),
    ("NOVA_CENTRAL_PERMISSION_AUDIT_APPROVED", "false"),
    ("NOVA_CENTRAL_APPROVED_COMMIT", "b" * 40),
    ("RENDER_GIT_COMMIT", "b" * 40),
    ("NOVA_CENTRAL_EXPECTED_DB_HOST", "foreign.internal"),
    ("NOVA_CENTRAL_READER_DATABASE_URL", "postgresql://prod:pw@central-only.internal/amicor"),
    ("NOVA_CENTRAL_READER_DATABASE_URL", "postgresql://nova_central_542_reader:pw@central-only.internal/nova_central_542_dispos?options=-crole%3Dadmin"),
    ("NOVA_CENTRAL_READER_DATABASE_URL", "sqlite:////tmp/unsafe.db"),
])
def test_unapproved_target_or_runtime_never_connects(config, monkeypatch, field, value):
    monkeypatch.setenv(field, value)
    with pytest.raises(RuntimeError):
        audit.check_target()


def good_report():
    return dict(
        database="nova_central_542_dispos",
        principal="nova_central_542_reader",
        session_user="nova_central_542_reader",
        can_login=True,
        superuser=False,
        create_role=False,
        create_db=False,
        replication=False,
        bypass_rls=False,
        can_create_schema=False,
        can_create_public_table=False,
        can_create_temp_table=False,
        role_memberships=[],
        other_tables={},
        tables={
            "platform_users": {
                "SELECT": False,
                "columns": {
                    **{col: True for col in audit._READER_COLUMNS},
                    "email": False, "hashed_password": False,
                    "display_name": False,
                },
                "INSERT": False, "UPDATE": False, "DELETE": False,
                "TRUNCATE": False, "REFERENCES": False, "TRIGGER": False,
            },
            "nova_central_journey_read_model": {
                "SELECT": True,
                "INSERT": False, "UPDATE": False, "DELETE": False,
                "TRUNCATE": False, "REFERENCES": False, "TRIGGER": False,
            },
        },
    )


def test_expected_read_only_catalog_is_reviewable():
    assert audit.assess_privileges(good_report()) == []


@pytest.mark.parametrize("field,value", [
    ("database", "amicor"),
    ("principal", "postgres"),
    ("session_user", "postgres"),
    ("superuser", True),
    ("create_role", True),
    ("create_db", True),
    ("replication", True),
    ("bypass_rls", True),
    ("can_create_schema", True),
])
def test_unsafe_role_or_database_fails_closed(field, value):
    report = good_report()
    report[field] = value
    assert audit.assess_privileges(report)


@pytest.mark.parametrize("action", ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"])
def test_each_forbidden_table_privilege_fails_closed(action):
    report = good_report()
    report["tables"]["platform_users"][action] = True
    assert audit.assess_privileges(report)


def test_missing_table_fails_closed():
    report = good_report()
    del report["tables"]["platform_users"]
    assert audit.assess_privileges(report)


def test_full_user_table_select_is_rejected():
    report = good_report()
    report["tables"]["platform_users"]["SELECT"] = True
    assert "unsafe_full_user_table_SELECT" in audit.assess_privileges(report)


@pytest.mark.parametrize("column", audit._READER_COLUMNS)
def test_missing_required_user_column_is_rejected(column):
    report = good_report()
    report["tables"]["platform_users"]["columns"][column] = False
    assert "missing_user_column_SELECT_" + column in audit.assess_privileges(report)


@pytest.mark.parametrize("column", ["email", "hashed_password", "display_name"])
def test_sensitive_user_column_grant_is_rejected(column):
    report = good_report()
    report["tables"]["platform_users"]["columns"][column] = True
    assert "unsafe_user_column_SELECT_" + column in audit.assess_privileges(report)


def test_missing_column_inventory_is_rejected():
    report = good_report()
    del report["tables"]["platform_users"]["columns"]
    assert "unknown_user_columns" in audit.assess_privileges(report)


def test_public_schema_create_fails_closed():
    report = good_report()
    report["can_create_public_table"] = True
    assert "public_schema_create_allowed" in audit.assess_privileges(report)


def test_temp_table_create_fails_closed():
    report = good_report()
    report["can_create_temp_table"] = True
    assert "temporary_table_create_allowed" in audit.assess_privileges(report)


@pytest.mark.parametrize("grant", ["SELECT", "ANY_COLUMN_SELECT", "INSERT", "UPDATE", "DELETE"])
def test_unrelated_table_grant_fails_closed(grant):
    report = good_report()
    report["other_tables"] = {"public.unrelated_private_records": {
        action: action == grant for action in
        ("SELECT", "ANY_COLUMN_SELECT", "INSERT", "UPDATE", "DELETE",
         "TRUNCATE", "REFERENCES", "TRIGGER")
    }}
    assert "unapproved_table_privileges_public.unrelated_private_records" in audit.assess_privileges(report)


def test_unrelated_table_inventory_must_be_present():
    report = good_report()
    del report["other_tables"]
    assert "unknown_unrelated_table_privileges" in audit.assess_privileges(report)


def test_missing_role_membership_inventory_fails_closed():
    report = good_report()
    del report["role_memberships"]
    assert "unknown_role_memberships" in audit.assess_privileges(report)


@pytest.mark.parametrize("memberships", [
    ["legacy_admin"],
    ["public_reader"],
    ["reader_group", "admin_group"],
])
def test_direct_or_transitive_role_membership_fails_closed(memberships):
    report = good_report()
    report["role_memberships"] = memberships
    assert "unexpected_role_memberships" in audit.assess_privileges(report)
