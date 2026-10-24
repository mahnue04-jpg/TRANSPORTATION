"""Validate the generated AMICOR public pages contain Google Tag Manager once."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GTM_ID = "GTM-KTQ6Q68T"


def main():
    pages = sorted(ROOT.rglob("*.html"))
    assert pages, "No generated HTML pages found: run python _generate.py first"
    failures = []
    for path in pages:
        html = path.read_text(encoding="utf-8")
        if not html.lstrip().lower().startswith("<!doctype html"):
            continue
        script = "https://www.googletagmanager.com/gtm.js?id='
        noscript = f"https://www.googletagmanager.com/ns.html?id={GTM_ID}"
        if html.count(script) != 1 or html.count(noscript) != 1:
            failures.append(str(path.relative_to(ROOT)))
        if html.index("<!-- Google Tag Manager -->") > html.index("<meta charset="):
            failures.append(f"{path.relative_to(ROOT)}: GTM should be near head start")
    if failures:
        raise SystemExit("GTM missing/duplicate/out of place: " + ", ".join(failures))
    print(f"Verified GTM snippets in {len(pages)} HTML files")


if __name__ == "__main__":
    main()
