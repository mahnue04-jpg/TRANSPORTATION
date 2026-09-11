"""Import/syntax checks for prepared Lifesaver Alembic revisions.

Does not connect to staging or production and does not run upgrade().
"""
from __future__ import annotations

import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
PHASE1 = VERSIONS / "20260911_lifesaver_phase1_schema.py"
PHASE2 = VERSIONS / "20260911_lifesaver_phase2_schema.py"


def _load(path: Path):
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    compile(source, str(path), "exec")
    namespace: dict[str, object] = {}
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102 — local revision import check
    return source, module, namespace


def test_lifesaver_revisions_import_and_chain():
    source1, _, ns1 = _load(PHASE1)
    source2, _, ns2 = _load(PHASE2)
    assert ns1["revision"] == "20260911_lifesaver_phase1_schema"
    assert ns1["down_revision"] == "20260909_nova_freight_settlement"
    assert ns2["revision"] == "20260911_lifesaver_phase2_schema"
    assert ns2["down_revision"] == "20260911_lifesaver_phase1_schema"
    assert callable(ns1["upgrade"]) and callable(ns1["downgrade"])
    assert callable(ns2["upgrade"]) and callable(ns2["downgrade"])
    assert "health_isf_" not in source1
    assert "health_isf_" not in source2
    assert "ForeignKey" not in source1
    assert "ForeignKey" not in source2
    for table in (
        "lifesaver_profiles",
        "lifesaver_consents",
        "lifesaver_care_circle_members",
        "lifesaver_health_readings",
        "lifesaver_audit_events",
    ):
        assert table in source1
    assert "lifesaver_transport_requests" in source2
    assert "lifesaver_notification_outbox" in source2
    assert "device_alias" in source2
    assert "ingestion_status" in source2
    assert "op.drop_table" in source1
    assert "drop_column" in source2


def test_staging_smoke_script_has_no_embedded_secrets():
    script = Path(__file__).resolve().parents[2] / "scripts" / "lifesaver_staging_smoke.py"
    source = script.read_text(encoding="utf-8")
    compile(source, str(script), "exec")
    assert "LIFESAVER_SMOKE_PASSWORD" in source
    assert "getenv" in source
    assert "password\": \"" not in source
    assert "sk_live_" not in source
