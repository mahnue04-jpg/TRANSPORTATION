"""Startup create_all must keep draft casting tables out of the live database."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_startup_paths_omit_casting_tables():
    session = (ROOT / "app/db/session.py").read_text(encoding="utf-8")
    startup = (ROOT / "app/deployment/background_startup.py").read_text(encoding="utf-8")
    assert "def omit_casting_tables" in session
    assert 'startswith("nova_casting_")' in session
    assert "_install_casting_create_all_guard" in session
    assert "omit_casting_tables(" in startup
    schema = (ROOT / "app/core/nova/creative_studio/schema_ensure.py").read_text(encoding="utf-8")
    assert "casting_db_models" not in schema
    env = (ROOT / "migrations/env.py").read_text(encoding="utf-8")
    assert "casting_db_models" not in env
    assert "nova_casting_" not in env
    checklist = (ROOT.parent / "docs/nova-casting-staging-checklist.md").read_text(encoding="utf-8")
    for phrase in (
        "NOVA_CASTING_STAGING_READS",
        "media_uploads_enabled",
        "alembic upgrade heads",
        "Do not merge",
        "CASTING_TEST_POSTGRES_URL",
    ):
        assert phrase in checklist
