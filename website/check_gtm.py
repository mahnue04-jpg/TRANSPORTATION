"""Check the generated AMICOR HTML pages for Google Tag Manager snippets."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GTM_ID = "GTM-KTQ6Q68T"


def main():
    pages = [p for p in ROOT.rglob("*.html") if p.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")]
    if not pages:
        raise SystemExit("No generated HTML pages found")
    failures = []
    for path in pages:
        html = path.read_text(encoding="utf-8")
        # Retired-route redirect documents do not load the site template.
        if '<meta http-equiv="refresh"' in html or '<meta http-equiv="refresh"' in html.lower():
            continue
        script_start = "<!-- Google Tag Manager -->"
        script_url = "https://www.googletagmanager.com/gtm.js?id="
        noscript_url = f"https://www.googletagmanager.com/ns.html?id={GTM_ID}"
        if (html.count(script_start) != 1 or html.count(script_url) != 1
                or html.count(noscript_url) != 1):
            failures.append(f"{path.relative_to(ROOT)}: missing or duplicate GTM snippets")
            continue
        if not (html.index("<head>") < html.index(script_start) < html.index("<meta charset=")):
            failures.append(f"{path.relative_to(ROOT)}: head snippet misplaced")
        body_pos = html.find("<body")
        noscript_pos = html.find("<!-- Google Tag Manager (noscript) -->")
        content_pos = html.find('class="skip"')
        if content_pos < 0:
            content_pos = html.find("<main")
        if not (body_pos >= 0 and body_pos < noscript_pos < content_pos):
            failures.append(f"{path.relative_to(ROOT)}: body snippet misplaced")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Verified GTM snippets in {len(pages)} HTML files")


if __name__ == "__main__":
    main()
