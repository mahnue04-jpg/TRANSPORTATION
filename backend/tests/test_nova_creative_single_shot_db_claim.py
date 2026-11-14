"""Owner-scoped SQL claim check for one five-second provider post.

Real SQLite transactions, two independent sessions, zero video-provider calls.
"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.creative_studio.db_models import NovaCreativeProject
from app.core.nova.creative_studio.store import DbCreativeStudioStore


def test_first_shot_sql_claim_one_winner_and_no_cross_owner(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'single-shot-claim.sqlite'}")
    NovaCreativeProject.__table__.create(bind=engine)
    original = {"film_project": "The Return", "budget_confirmation": {"confirmed": True}}
    with Session(engine) as db:
        db.add(NovaCreativeProject(
            id="project-shot", owner_id="owner-one", title="Five-second actor test",
            project_type="short_drama", platform="YouTube",
            objective="", audience="", tone="", duration_target=5,
            status="draft", brand_profile_id=None, brief_id=None,
            metadata_json=json.dumps(original, ensure_ascii=True),
            created_at="2026-11-10T00:00:00Z", updated_at="2026-11-10T00:00:00Z",
        ))
        db.commit()
    reserved = dict(original, first_shot_paid_claim={
        "id": "reservation-a", "reference_image_asset_id": "frame-1", "state": "RESERVED",
    })
    attempted = dict(original, first_shot_paid_claim={
        "id": "reservation-a", "reference_image_asset_id": "frame-1", "state": "POST_ATTEMPTED",
    })
    try:
        with Session(engine) as first, Session(engine) as second:
            a, b = DbCreativeStudioStore(first), DbCreativeStudioStore(second)
            assert a.compare_and_swap_project_metadata("project-shot", "owner-one", original, reserved) is True
            assert b.compare_and_swap_project_metadata("project-shot", "owner-one", original, reserved) is False
            assert a.compare_and_swap_project_metadata("project-shot", "owner-one", reserved, attempted) is True
            assert b.compare_and_swap_project_metadata("project-shot", "owner-one", reserved, attempted) is False
            assert b.compare_and_swap_project_metadata("project-shot", "other-owner", attempted, reserved) is False
            project = b.get_project("project-shot", "owner-one")
            assert project.metadata["first_shot_paid_claim"]["state"] == "POST_ATTEMPTED"
            assert project.metadata["film_project"] == "The Return"
    finally:
        engine.dispose()
