"""Owner-review HTML for the synthetic fixture timeline.

The page is static markup. It loads no scripts and contains no remote URLs.
"""
from __future__ import annotations

from html import escape

from app.core.nova.intelligence.fixtures import FIXTURES
from app.core.nova.intelligence.messages import (
    DIARIZATION_NOT_PERFORMED,
    NOT_PRODUCTION,
    SPEAKERS_UNKNOWN,
    SUMMARY_IS_FIXTURE,
)
from app.core.nova.intelligence.timeline import timeline


def render_demo_page(observations: list[dict] | None = None, summary: str | None = None) -> str:
    fixture = FIXTURES["meeting-clip-01"]
    ordered = observations if observations is not None else timeline(fixture.observations)
    shown_summary = fixture.summary if summary is None else summary
    rows: list[str] = []
    for item in ordered:
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('start_seconds', '')))}</td>"
            f"<td>{escape(str(item.get('end_seconds', '')))}</td>"
            f"<td>{escape(str(item.get('kind', '')))}</td>"
            f"<td>{escape(str(item.get('text', '')))}</td>"
            f"<td>{escape(str(item.get('source_ref', '')))}</td>"
            "</tr>"
        )
    summary_html = escape(shown_summary or "")
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8">'
        "<title>Synthetic media evidence</title>"
        "<style>"
        "body{font-family:sans-serif;margin:2rem;color:#1b1b1b}"
        "table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:0.4rem;text-align:left;vertical-align:top}"
        ".banner{background:#fff4d6;padding:1rem;margin-bottom:1rem}"
        "</style></head><body>"
        '<p class="banner">Synthetic fixture. '
        f"{escape(NOT_PRODUCTION)} {escape(SPEAKERS_UNKNOWN)} {escape(SUMMARY_IS_FIXTURE)} "
        f"{escape(DIARIZATION_NOT_PERFORMED)}</p>"
        "<h1>Synthetic meeting clip</h1>"
        "<p>Owner review only. Timestamps and source refs come from the offline fixture.</p>"
        f"<p>Fixture summary: {summary_html}</p>"
        "<table><thead><tr>"
        "<th>Start seconds</th><th>End seconds</th><th>Kind</th><th>Text</th><th>Source ref</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )
