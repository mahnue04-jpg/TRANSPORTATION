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
