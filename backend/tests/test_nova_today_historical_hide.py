"""Allowlisted historical Today hide: deactivate excess only, never delete."""
from __future__ import annotations

from app.core.nova.today.historical_hide import (
    CANONICAL_ACTION_IDS,
    EXCESS_ACTION_IDS,
    hide_verified_excess_today_rows,
)
from app.core.nova.today.models import NovaV2CommandAction
from app.core.nova.today.schema_ensure import ensure_nova_today_schema
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now


def _seed_row(*, action_id: str, owner: str, status: str, ref: str = "rec-attention", module: str = "business") -> None:
    with SessionLocal() as db:
        db.add(
            NovaV2CommandAction(
                action_id=action_id,
                organization_id="org-hide-test",
                owner_user_id=owner,
                source_module=module,
                source_ref_id=ref,
                title="historical hide seed",
                detail="seed",
                href="/nova/today",
                trust_label="ACTION REQUIRES APPROVAL",
                priority=40,
                status=status,
                recommended_action="acknowledge",
                created_at=now(),
            )
        )
        db.commit()


def test_hide_verified_excess_does_not_delete_or_touch_canonicals() -> None:
    init_platform_db()
    ensure_nova_today_schema(engine)
    for index, action_id in enumerate(sorted(EXCESS_ACTION_IDS)):
        _seed_row(action_id=action_id, owner=f"owner-excess-{index}", status="proposed")
    for index, action_id in enumerate(sorted(CANONICAL_ACTION_IDS)):
        status = "done" if action_id == "NV2-844561D2D0C2" else "proposed"
        _seed_row(action_id=action_id, owner=f"owner-canon-{index}", status=status)
    _seed_row(action_id="NV2-SMOKEKEEP0001", owner="owner-smoke", status="proposed", ref="v2live-keep")

    before = hide_verified_excess_today_rows(engine)
    assert before == 15
    again = hide_verified_excess_today_rows(engine)
    assert again == 0

    with SessionLocal() as db:
        rows = {row.action_id: row for row in db.query(NovaV2CommandAction).all()}
        assert len(rows) >= 15 + 5 + 1
        for action_id in EXCESS_ACTION_IDS:
            assert rows[action_id].status == "deactivated"
            assert rows[action_id].result_ref_id is None
            assert rows[action_id].decided_at is None
        for action_id in CANONICAL_ACTION_IDS:
            expected = "done" if action_id == "NV2-844561D2D0C2" else "proposed"
            assert rows[action_id].status == expected
        assert rows["NV2-SMOKEKEEP0001"].status == "proposed"
        assert db.query(NovaV2CommandAction).count() >= 21
