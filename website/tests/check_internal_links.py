from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
missing: list[tuple[str, str]] = []
checked = 0
for html in ROOT.rglob("*.html"):
    text = html.read_text(encoding="utf-8")
    for href in re.findall(r'href="([^"]+)"', text):
        if href.startswith(("http://", "https://", "mailto:")):
            continue
        if href.startswith("#") and href != "#":
            continue
        if href == "#":
            missing.append((str(html.relative_to(ROOT)), href))
            continue
        path = href.split("?")[0]
        if not path.startswith("/"):
            continue
        rel = path.lstrip("/")
        target = ROOT / rel
        checked += 1
        exists = target.exists() or (ROOT / rel / "index.html").exists()
        if path.endswith("/") and (ROOT / rel / "index.html").exists():
            exists = True
        if not exists:
            missing.append((str(html.relative_to(ROOT)), href))
print(f"internal_checked={checked}")
print(f"missing={missing}")
if missing:
    raise SystemExit(1)
