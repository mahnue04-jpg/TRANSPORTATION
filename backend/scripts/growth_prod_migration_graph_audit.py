"""Read-only Alembic revision graph inventory for a proposed Growth production release.

Does not import migrations/env.py, connect to any database, read credentials,
stamp a revision, or perform DDL. The production head is supplied as a
*recorded label*, not queried from a database.
"""
from __future__ import annotations

import json
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]
RECORDED_PRODUCTION_REVISION = "20260918_nova_v3_live_infrastructure"


def audit_graph(recorded_revision: str = RECORDED_PRODUCTION_REVISION) -> dict:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    # The recorded production revision may be a historical alias not present in
    # this branch. Report that as a HARD RELEASE BLOCKER, not a passing graph.
    revisions = list(script.walk_revisions())
    known = {rev.revision for rev in revisions}
    heads = list(script.get_heads())
    if recorded_revision not in known:
        matching = sorted(
            rev.revision for rev in revisions
            if rev.revision.startswith("20260918_nova_v3_live_")
        )
        return {
            "recorded_production_revision": recorded_revision,
            "repository_head": heads,
            "status": "blocked_unknown_production_revision",
            "candidate_repository_revisions": matching,
            "release_ready": False,
            "owner_review_required": True,
            "database_connected": False,
            "migration_applied": False,
            "version_stamped": False,
            "reason": "Production revision label is absent from repository graph; do not infer equivalence, stamp, or migrate",
        }
    current = script.get_revision(recorded_revision)
    heads = list(script.get_heads())
    if len(heads) != 1:
        raise RuntimeError(f"Expected a single migration head, found {len(heads)}")
    try:
        pending = list(script.iterate_revisions(heads[0], recorded_revision))
    except Exception as exc:
        raise RuntimeError("Recorded production revision not safely reachable from head") from exc
    pending.reverse()
    if not pending:
        raise RuntimeError("No revision delta found; verify production metadata before release")
    all_names = [rev.revision for rev in pending]
    return {
        "recorded_production_revision": recorded_revision,
        "repository_head": heads[0],
        "revision_count": len(all_names),
        "pending_revisions": all_names,
        "growth_revisions": [name for name in all_names if "nova_ga" in name or "growth" in name],
        "non_growth_revisions": [name for name in all_names if "nova_ga" not in name and "growth" not in name],
        "review_required": True,
        "release_ready": False,
        "status": "pending_manual_schema_reconciliation",
        "database_connected": False,
        "migration_applied": False,
        "version_stamped": False,
    }


if __name__ == "__main__":
    print(json.dumps(audit_graph(), sort_keys=True, indent=2))
