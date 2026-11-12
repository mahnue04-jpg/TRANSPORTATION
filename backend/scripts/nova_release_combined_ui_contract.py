"""Cross-product combined dashboard static acceptance, no cloud or secrets."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "backend/static/nova-work/index.html"
STATIC = ROOT / "backend/static/nova-work"


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        options = dict(attrs)
        if "id" in options:
            self.ids.append(options["id"])
        if tag == "script" and options.get("src"):
            self.scripts.append(options["src"])
        if tag == "link" and options.get("rel") == "stylesheet":
            self.styles.append(options.get("href"))


def main():
    content = PAGE.read_text(encoding="utf-8")
    if any(marker in content for marker in ("<<<<<<<", "=======", ">>>>>>>")):
        raise AssertionError("Conflict marker present")
    elements = Elements()
    elements.feed(content)
    duplicate_ids = sorted(key for key, n in Counter(elements.ids).items() if n > 1)
    if duplicate_ids:
        raise AssertionError(f"Duplicate DOM IDs: {duplicate_ids[:10]}")
    for key in (
        "first-client-board", "first-client-refresh", "first-client-list",
        "operations-csv-form", "operations-scoped-csv-form",
        "nova-bookkeeping-console", "bookkeeping-submit-form",
        "bookkeeping-eligible-tasks", "live-job-form",
    ):
        assert key in elements.ids, f"Missing integration control: {key}"
    for name in ("work.js", "first-client.js", "operations-csv.js", "bookkeeping.js"):
        src = "/static/nova-work/" + name
        assert elements.scripts.count(src) == 1, f"Missing/duplicate script: {src}"
        assert (STATIC / name).is_file(), f"Missing script: {name}"
        subprocess.run(["node", "--check", str(STATIC / name)], check=True)
    assert elements.styles.count("/static/nova-work/first-client.css") == 1
    assert (STATIC / "first-client.css").is_file()
    print("PASS: unique controls and all four Work & Revenue/Operations/Accounting scripts coexist.")
    print("This is a static acceptance test, not an authenticated staging test.")


if __name__ == "__main__":
    main()
