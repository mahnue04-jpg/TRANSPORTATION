"""Safely combine disjoint Nova Work & Revenue dashboard sections in CI only.

The merge has exactly one known conflict: both draft branches insert separate
UI panels into the same HTML file. This tool refuses unknown conflicts,
missing anchors, duplicate controls or changed script layout.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TARGET = "backend/static/nova-work/index.html"
BOARD_PATTERN = re.compile(
    r'    <section class="command-card" id="first-client-board"'
    r'.*?^    </section>\n',
    re.MULTILINE | re.DOTALL,
)
LINK = '  <link rel="stylesheet" href="/static/nova-work/first-client.css" />'
SCRIPT = '  <script src="/static/nova-work/first-client.js"></script>'
NAV = '      <p class="hint"><a href="#first-client-board">View saved first-client opportunities</a> — a saved lead is not an application submission.</p>'
ANCHOR = '    <section class="counts" aria-label="Work counts">'
END_SCRIPTS = '  <script src="/static/nova-work/bookkeeping.js"></script>'


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def reconcile() -> None:
    conflicts = git("diff", "--name-only", "--diff-filter=U").splitlines()
    if conflicts != [TARGET]:
        raise RuntimeError(f"Unexpected merge conflict files; no auto-resolution: {conflicts!r}")
    # :2 = ours (Operations/Accounting integrated tree), :3 = theirs (Revenue)
    ours = git("show", f":2:{TARGET}")
    theirs = git("show", f":3:{TARGET}")
    if any(v in ours for v in (LINK, SCRIPT, 'id="first-client-board"')):
        raise RuntimeError("Revenue panel already present in accounting HTML; manual review")
    if any(v not in theirs for v in (LINK, SCRIPT, 'id="first-client-board"', NAV)):
        raise RuntimeError("Revenue UI contract changed; manual review")
    if 'id="nova-bookkeeping-console"' not in ours or 'id="operations-scoped-csv-form"' not in ours:
        raise RuntimeError("Operations or accounting panel missing from integrated base")
    board = BOARD_PATTERN.findall(theirs)
    if len(board) != 1:
        raise RuntimeError("Expected exactly one complete first-client board")
    if ours.count(ANCHOR) != 1 or ours.count(END_SCRIPTS) != 1:
        raise RuntimeError("Accounting HTML insertion anchors changed")
    combined = ours.replace(
        '  <link rel="stylesheet" href="/static/nova-work/work.css" />',
        '  <link rel="stylesheet" href="/static/nova-work/work.css" />\n' + LINK,
        1,
    )
    combined = combined.replace(ANCHOR, board[0] + "\n" + ANCHOR, 1)
    combined = combined.replace(END_SCRIPTS, END_SCRIPTS + "\n" + SCRIPT, 1)
    combined = combined.replace(
        '      <div id="live-job-results">No live discovery run yet.</div>',
        '      <div id="live-job-results">No live discovery run yet.</div>\n' + NAV,
        1,
    )
    if any(combined.count(token) != 1 for token in (
        LINK, SCRIPT, NAV, 'id="first-client-board"',
        'id="operations-scoped-csv-form"', 'id="nova-bookkeeping-console"',
    )):
        raise RuntimeError("Combined dashboard control is duplicated or missing")
    if "<<<<<<<" in combined or ">>>>>>>" in combined:
        raise RuntimeError("Unresolved conflict markers remain")
    Path(TARGET).write_text(combined, encoding="utf-8")
    subprocess.run(["git", "add", TARGET], check=True)
    print("Resolved only shared dashboard panel conflict in EPHEMERAL CI workspace.")


if __name__ == "__main__":
    try:
        reconcile()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"REQUIRES_MANUAL_REVIEW: {exc}", file=sys.stderr)
        raise SystemExit(1)
