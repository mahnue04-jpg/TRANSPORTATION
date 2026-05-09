#!/usr/bin/env python3
"""validate_startup.py — Pre-deployment readiness check for Amicor.

Checks:
  1. Python version (>= 3.11)
  2. Required environment variables
  3. Optional environment variable warnings
  4. Database directory is writable
  5. OpenAI API key format (basic sanity)
  6. All required Python packages are importable

Exit code 0 = all checks pass (ready to deploy).
Exit code 1 = one or more checks failed (block deployment).
"""

import os
import sys
import importlib

# ── Ensure dotenv is loaded if available ─────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed yet — that's fine for this script

PASS  = "  [PASS]"
WARN  = "  [WARN]"
FAIL  = "  [FAIL]"
HEAD  = "═" * 58


def check(label: str, ok: bool, detail: str = "", warn_only: bool = False) -> bool:
    tag    = PASS if ok else (WARN if warn_only else FAIL)
    suffix = f"  ({detail})" if detail else ""
    print(f"{tag}  {label}{suffix}")
    return ok or warn_only


def run_checks() -> bool:
    print(HEAD)
    print("  Amicor pre-deployment validation")
    print(HEAD)
    results = []

    # 1. Python version
    maj, min_ = sys.version_info[:2]
    results.append(check(
        f"Python >= 3.11   ({maj}.{min_})",
        maj == 3 and min_ >= 11,
        detail="" if (maj == 3 and min_ >= 11) else f"found {maj}.{min_}",
    ))

    # 2. Required env vars
    required = ["OPENAI_API_KEY"]
    for var in required:
        val = os.environ.get(var, "")
        results.append(check(f"Env: {var}", bool(val), detail="missing" if not val else ""))

    # 3. Optional env var warnings (not blocking)
    optional = {
        "weather_api_key": "Weather module will be disabled",
        "ALLOWED_ORIGINS":  "CORS allows all origins — unsafe in production",
        "APP_VERSION":      "Version will show as 'dev'",
    }
    for var, note in optional.items():
        val = os.environ.get(var, "")
        check(f"Env: {var}", bool(val), detail=note if not val else "", warn_only=True)

    # 4. OpenAI key format sanity check (non-empty, starts with "sk-")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    results.append(check(
        "OPENAI_API_KEY format",
        api_key.startswith("sk-") and len(api_key) > 20,
        detail="should start with 'sk-'" if not api_key.startswith("sk-") else "",
    ))

    # 5. DB directory writable
    db_path = os.environ.get("DB_FILENAME", "/data/chat.db")
    db_dir  = os.path.dirname(db_path) or "."
    try:
        os.makedirs(db_dir, exist_ok=True)
        test_file = os.path.join(db_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        results.append(check(f"DB dir writable ({db_dir})", True))
    except Exception as exc:
        results.append(check(f"DB dir writable ({db_dir})", False, detail=str(exc)))

    # 6. Required Python packages importable
    packages = [
        ("fastapi",        "fastapi"),
        ("uvicorn",        "uvicorn"),
        ("openai",         "openai"),
        ("dotenv",         "python-dotenv"),
        ("multipart",      "python-multipart"),
        ("aiofiles",       "aiofiles"),
    ]
    for module, pkg in packages:
        try:
            importlib.import_module(module)
            results.append(check(f"Package: {pkg}", True))
        except ImportError:
            results.append(check(f"Package: {pkg}", False, detail=f"pip install {pkg}"))

    # ── Summary ──────────────────────────────────────────────────────────────
    print(HEAD)
    all_ok = all(results)
    if all_ok:
        print("  ✓  All checks passed — ready to deploy.\n")
    else:
        failed = results.count(False)
        print(f"  ✗  {failed} check(s) failed — fix before deploying.\n")
    print(HEAD)
    return all_ok


if __name__ == "__main__":
    ok = run_checks()
    sys.exit(0 if ok else 1)
