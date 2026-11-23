"""No-network safety checks for the historical production migration label.

Production's recorded Alembic revision is not the same as the current
repository's V3 revision ID. Never assume they are interchangeable.
"""
from scripts.growth_prod_migration_graph_audit import audit_graph


def test_unresolved_production_revision_is_hard_release_blocker():
    result = audit_graph()
    assert result["recorded_production_revision"] == "20260918_nova_v3_live_infrastructure"
    assert result["status"] == "blocked_unknown_production_revision"
    assert "20260918_nova_v3_live_infra" in result["candidate_repository_revisions"]
    assert result["release_ready"] is False
    assert result["database_connected"] is False
    assert result["migration_applied"] is False
    assert result["version_stamped"] is False
