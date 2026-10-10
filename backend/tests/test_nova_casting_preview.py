"""Regression checks for the non-production casting preview in existing Creative Studio."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "static" / "nova-creative" / "index.html"
PREVIEW = ROOT / "static" / "nova-creative" / "casting-preview.html"


def test_casting_preview_is_linked_from_existing_studio():
    assert STUDIO.is_file()
    assert PREVIEW.is_file()
    html = STUDIO.read_text(encoding="utf-8")
    assert 'href="/static/nova-creative/casting-preview.html"' in html
    assert 'href="/nova/creative"' in html


def test_casting_preview_has_three_audition_lanes_and_review():
    html = PREVIEW.read_text(encoding="utf-8")
    for expected in (
        "Reality TV casting",
        "Beauty competition",
        "Film and commercial auditions",
        'id="preview"',
        'id="candidates"',
        "Shortlist",
        "Clear demo shortlist",
    ):
        assert expected in html


def test_casting_preview_never_claims_real_submission_or_partnership():
    html = PREVIEW.read_text(encoding="utf-8")
    assert "not a live audition portal" in html
    assert "No relationship or integration with Zeus" in html
    assert "No application was submitted, stored or sent" in html
    assert 'type="submit"' in html
    assert 'e.preventDefault()' in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert 'type="file"' not in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html


def test_organizer_review_stages_are_in_memory_only():
    html = PREVIEW.read_text(encoding="utf-8")
    for expected in (
        'id="review-status"', 'id="review-note"',
        'id="save-review"', 'function openReview(',
        'Demo review updated in memory only; not saved or sent.',
        'Object.keys(reviews).forEach',
    ):
        assert expected in html
    assert "localStorage" not in html
    assert "fetch(" not in html


def test_optional_score_and_callback_are_demo_only():
    html = PREVIEW.read_text(encoding="utf-8")
    for expected in ('id="review-score"', 'id="callback-time"', 'no invitation sent', 'score:', 'callback:'):
        assert expected in html
    assert 'type="datetime-local"' in html
    assert "fetch(" not in html
    assert "localStorage" not in html


def test_organizer_review_filter_exists():
    html = PREVIEW.read_text(encoding="utf-8")
    assert 'id="candidate-filter"' in html
    assert 'value="All">All candidates' in html
    assert 'value="Callback">Callback requested' in html
    assert 'getElementById("candidate-filter").addEventListener("change",render)' in html
