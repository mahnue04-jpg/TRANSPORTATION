"""Static safety and usability checks for the PR #519 fictional campaign preview.

These are source-level checks, not an authenticated backend/browser acceptance test.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    status = (ROOT / "nova/growth/index.html").read_text(encoding="utf-8")
    demo = (ROOT / "nova/growth/demo/index.html").read_text(encoding="utf-8")
    assert 'href="/nova/growth/demo/"' in status, "Preview status must link to fictional walkthrough"
    assert "Not connected" in status, "Preview status must not imply backend connectivity"
    assert "Fictional browser demo only" in demo, "Demo must label simulated data"
    assert "No server data changed" in demo, "Save must disclose non-persistence"
    assert "This is not the PR #519 live backend" in demo
    assert 'id="demo-feedback"' in demo and 'aria-live="polite"' in demo
    for key in ("inquiries", "authorized", "sending", "sensitive"):
        assert f'id="demo-{key}"' in demo
    assert 'id="demo-contact"' in demo and 'id="demo-stage"' in demo
    assert 'id="demo-reset"' in demo and "Refreshing this page resets" in demo
    assert "Cannot advance:" in demo and "Cannot move from " in demo
    # Demo source must not make authenticated or outbound application requests.
    for forbidden in ("fetch(", "XMLHttpRequest", "navigator.sendBeacon(", "localStorage", "sessionStorage",
                      "window.open(", "/api/nova/growth-agent", "action=\"http"):
        assert forbidden not in demo, f"Demo must remain browser-only: {forbidden}"
    print("Growth campaign source-level preview safety checks passed (no hosted browser verification)")


if __name__ == "__main__":
    main()
