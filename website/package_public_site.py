"""Copy the public website into dist/ for preview and Cloudflare upload.

Owner notes, the generator, tests, and Wrangler config stay out of the upload.
"""

from pathlib import Path
from shutil import copy2, rmtree

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "dist"
EXTENSIONS = {
    ".html",
    ".css",
    ".js",
    ".svg",
    ".png",
    ".webp",
    ".jpg",
    ".jpeg",
    ".ico",
    ".xml",
    ".txt",
    ".json",
    ".webmanifest",
}
SPECIAL = {"_headers", "_redirects", "_routes.json"}
SKIP_DIRS = {"tests", "__pycache__", "node_modules"}


def main() -> None:
    if OUT.exists():
        rmtree(OUT)
    OUT.mkdir()
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in EXTENSIONS and path.name not in SPECIAL:
            continue
        target = OUT / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(path, target)
    required = [
        OUT / "index.html",
        OUT / "products" / "index.html",
        OUT / "functions" / "api" / "leads.js",
    ]
    missing = [str(path.relative_to(OUT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Public package is missing {', '.join(missing)}")
    leaked = [
        OUT / "EMAIL.md",
        OUT / "_generate.py",
        OUT / "wrangler.toml",
        OUT / "package_public_site.py",
    ]
    present = [path.name for path in leaked if path.exists()]
    if present:
        raise SystemExit(f"Public package includes private files: {', '.join(present)}")
    print("Prepared public website folder; no deployment performed")


if __name__ == "__main__":
    main()
