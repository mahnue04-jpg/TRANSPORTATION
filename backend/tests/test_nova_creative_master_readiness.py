"""No-provider regression tests for exact-file chapter quality approval."""
from app.core.nova.creative_studio.calendar import _chapter_review_passed


def _approved_review():
    return {
        "status": "REVIEW_PASSED",
        "chapter_index": 1,
        "file_sha256": "a" * 64,
        "visuals_ok": True,
        "audio_ok": True,
        "captions_ok": True,
        "continuity_ok": True,
    }


def test_master_quality_gate_requires_exact_approved_file():
    review = _approved_review()
    assert _chapter_review_passed(review, 1, "a" * 64)
    assert not _chapter_review_passed(review, 2, "a" * 64)
    assert not _chapter_review_passed(review, 1, "b" * 64)
    assert not _chapter_review_passed(review, 1, "")
    assert not _chapter_review_passed(None, 1, "a" * 64)
    assert not _chapter_review_passed({}, 1, "a" * 64)


def test_master_quality_gate_fails_closed_on_review_defects():
    good = _approved_review()
    for key in ("visuals_ok", "audio_ok", "captions_ok", "continuity_ok"):
        bad = {**good, key: False}
        assert not _chapter_review_passed(bad, 1, "a" * 64)
        missing = dict(good)
        del missing[key]
        assert not _chapter_review_passed(missing, 1, "a" * 64)
    changes = {**good, "status": "CHANGES_REQUIRED"}
    assert not _chapter_review_passed(changes, 1, "a" * 64)
    pending = {**good, "status": "PENDING"}
    assert not _chapter_review_passed(pending, 1, "a" * 64)


def _build_plan(monkeypatch, tmp_path, *, first_review=True, second_review=True):
    """Exercise the actual readiness planner without paid media or network."""
    import json
    from types import SimpleNamespace
    from app.core.nova.creative_studio import calendar as studio
    from app.core.nova.creative_studio import private_object_storage as remote

    def make_asset(index, passed):
        sha = chr(ord("a") + index) * 64
        review = {
            "status": "REVIEW_PASSED" if passed else "CHANGES_REQUIRED",
            "chapter_index": index, "file_sha256": sha,
            "visuals_ok": passed, "audio_ok": True,
            "captions_ok": True, "continuity_ok": True,
            "notes": "" if passed else "Scene transition needs correction.",
        }
        return SimpleNamespace(
            id=f"asset-{index}", kind="video", url=f"private-studio-s3://test-{index}",
            metadata={
                "pipeline": "calendar_saved_clip_assembly",
                "calendar_entry_id": "entry",
                "chapter_index": index,
                "source_asset_ids": [f"source-{index}"],
                "duration_seconds": 180,
                "sha256": sha,
                "chapter_quality_review": review,
                "file_size_bytes": 50000,
            },
        )

    assets = [make_asset(0, first_review), make_asset(1, second_review)]
    chapters = [
        {"title": f"Chapter {i + 1}", "duration_seconds": 180,
         "asset_ids": [f"source-{i}"]}
        for i in range(2)
    ]
    entry = SimpleNamespace(chapters_json=json.dumps(chapters),
                            duration_seconds=360, status="approved")
    monkeypatch.setattr(studio, "_project", lambda *args: None)
    monkeypatch.setattr(studio, "_entry", lambda *args: entry)
    monkeypatch.setattr(studio, "DbCreativeStudioStore",
                        lambda db: SimpleNamespace(list_assets=lambda *args: assets))
    monkeypatch.setattr(studio, "get_service", lambda db: object())
    monkeypatch.setattr(remote, "enabled", lambda: True)
    monkeypatch.setattr(remote, "object_exists", lambda *args: True)
    return studio, assets


def test_chapter_plan_blocks_changes_required_and_reports_indices(monkeypatch, tmp_path):
    studio, assets = _build_plan(monkeypatch, tmp_path, second_review=False)
    plan = studio._chapter_rebuild_plan(object(), "owner", "project", "entry")
    assert plan["master_ready"] is False
    assert plan["needs_rebuild_indices"] == []
    assert plan["needs_review_indices"] == [1]
    assert plan["needs_correction_indices"] == [1]
    assert plan["reviewed_chapters"] == 1
    assert [row["review_status"] for row in plan["chapters"]] == [
        "REVIEW_PASSED", "CHANGES_REQUIRED"
    ]
    # A saved correction review must not create a publish-ready master.
    assert plan["published"] is False


def test_chapter_plan_accepts_only_both_exact_passed_reviews(monkeypatch, tmp_path):
    studio, assets = _build_plan(monkeypatch, tmp_path)
    passed = studio._chapter_rebuild_plan(object(), "owner", "project", "entry")
    assert passed["master_ready"] is True
    assert passed["reviewed_chapters"] == 2
    assert not passed["needs_review_indices"]
    assets[1].metadata["chapter_quality_review"]["file_sha256"] = "f" * 64
    stale = studio._chapter_rebuild_plan(object(), "owner", "project", "entry")
    assert stale["master_ready"] is False
    assert stale["needs_review_indices"] == [1]
    assert stale["needs_correction_indices"] == []
    assert stale["chapters"][1]["review_status"] == "REVIEW_REQUIRED"
    assert stale["version_sha256"] != passed["version_sha256"]


def test_chapter_plan_missing_file_blocks_without_review(monkeypatch, tmp_path):
    studio, assets = _build_plan(monkeypatch, tmp_path)
    from app.core.nova.creative_studio import private_object_storage as remote
    monkeypatch.setattr(remote, "object_exists",
                        lambda url, *args: not url.endswith("test-1"))
    plan = studio._chapter_rebuild_plan(object(), "owner", "project", "entry")
    assert plan["master_ready"] is False
    assert plan["needs_rebuild_indices"] == [1]
    assert plan["needs_review_indices"] == []
    assert plan["chapters"][1]["review_status"] == "NEEDS_REBUILD"


def test_final_master_endpoint_rejects_unreviewed_chapters(monkeypatch):
    """API guard: approved source MP4s alone never authorize a master."""
    from types import SimpleNamespace
    import pytest
    from fastapi import BackgroundTasks, HTTPException
    from app.core.nova.creative_studio import calendar as studio

    monkeypatch.setattr(studio, "_chapter_rebuild_plan", lambda *args: {
        "master_ready": False,
        "needs_rebuild_indices": [],
        "needs_review_indices": [1],
        "needs_correction_indices": [1],
        "version_sha256": "a" * 64,
    })
    monkeypatch.setattr(studio, "start_chapter_master_job",
                        lambda *args: pytest.fail("Unreviewed export must not queue"))
    with pytest.raises(HTTPException) as error:
        studio.update_final_master(
            "project", "entry",
            studio.ConfirmedMasterUpdateIn(version_sha256="a" * 64,
                                            confirm_rebuild=True),
            BackgroundTasks(), SimpleNamespace(user_id="owner"), object(),
        )
    assert error.value.status_code == 409
    assert error.value.detail["needs_review_indices"] == [1]
    assert error.value.detail["needs_correction_indices"] == [1]


def test_final_master_endpoint_rejects_stale_review_version(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from fastapi import BackgroundTasks, HTTPException
    from app.core.nova.creative_studio import calendar as studio

    monkeypatch.setattr(studio, "_chapter_rebuild_plan", lambda *args: {
        "master_ready": True, "version_sha256": "b" * 64
    })
    monkeypatch.setattr(studio, "start_chapter_master_job",
                        lambda *args: pytest.fail("Stale export must not queue"))
    with pytest.raises(HTTPException) as error:
        studio.update_final_master(
            "project", "entry",
            studio.ConfirmedMasterUpdateIn(version_sha256="a" * 64,
                                            confirm_rebuild=True),
            BackgroundTasks(), SimpleNamespace(user_id="owner"), object(),
        )
    assert error.value.status_code == 409
    assert "Refresh readiness" in error.value.detail


def test_failed_chapter_review_requires_actionable_notes(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException
    from app.core.nova.creative_studio import calendar as studio

    sha = "a" * 64
    asset = SimpleNamespace(id="asset-a", metadata={"sha256": sha})
    monkeypatch.setattr(studio, "_chapter_rebuild_plan", lambda *args: {
        "chapters": [{"chapter_index": 0, "status": "REUSABLE",
                      "asset_id": "asset-a", "asset_sha256": sha}]
    })
    monkeypatch.setattr(studio, "DbCreativeStudioStore", lambda db: SimpleNamespace(
        list_assets=lambda *args: [asset],
        save_asset=lambda *args: pytest.fail("Invalid review must not persist"),
    ))
    with pytest.raises(HTTPException) as error:
        studio.review_saved_chapter(
            "project", "entry", 0, "asset-a",
            studio.ChapterQualityReviewIn(
                visuals_ok=False, audio_ok=True, captions_ok=True,
                continuity_ok=True, notes="   ",
            ),
            SimpleNamespace(user_id="owner"), object(),
        )
    assert error.value.status_code == 422


def test_final_master_readiness_status_matrix():
    from app.core.nova.creative_studio.calendar import _final_master_readiness_status as status
    assert status("draft", 2, [], [], []) == "PLAN_APPROVAL_REQUIRED"
    assert status("approved", 1, [], [], []) == "MORE_CHAPTERS_REQUIRED"
    assert status("approved", 2, [0], [1], [1]) == "CHAPTER_REBUILD_REQUIRED"
    assert status("approved", 2, [], [1], [1]) == "CHAPTER_CORRECTIONS_REQUIRED"
    assert status("approved", 2, [], [1], []) == "CHAPTER_REVIEW_REQUIRED"
    assert status("approved", 2, [], [], []) == "READY_TO_UPDATE_FINAL_MASTER"


def test_readiness_plan_exposes_per_chapter_actions(monkeypatch, tmp_path):
    studio, assets = _build_plan(monkeypatch, tmp_path, second_review=False)
    plan = studio._chapter_rebuild_plan(object(), "owner", "project", "entry")
    assert plan["readiness_status"] == "CHAPTER_CORRECTIONS_REQUIRED"
    assert plan["blocking_chapters"] == [{
        "chapter_index": 1,
        "title": "Chapter 2",
        "reason": "CHANGES_REQUIRED",
        "next_action": "CORRECT_AND_REVIEW",
    }]
    assets[1].metadata["chapter_quality_review"] = {}
    needs_review = studio._chapter_rebuild_plan(object(), "owner", "project", "entry")
    assert needs_review["readiness_status"] == "CHAPTER_REVIEW_REQUIRED"
    assert needs_review["blocking_chapters"][0]["next_action"] == "REVIEW"
