"""Launch the isolated Nova Operations sample in a local browser.

Usage from backend/:
    python -m scripts.launch_nova_operations_demo

Requires the project's installed FastAPI/Uvicorn dependencies. The launcher
never connects to a Render environment or application database and opens
only a loopback HTTP port. It processes built-in synthetic sample data.
"""
from __future__ import annotations

import os
import secrets
import sys
from urllib.parse import urlsplit

FORBIDDEN = (
    "RENDER", "RENDER_SERVICE_NAME", "RENDER_EXTERNAL_URL",
    "DATABASE_URL", "AMICOR_ENVIRONMENT", "APP_ENV",
)


def demo_environment(source: dict[str, str]) -> dict[str, str]:
    """Build an isolated, allowlisted environment rather than inheriting secrets."""
    for key in ("DATABASE_URL", "RENDER", "RENDER_SERVICE_NAME", "RENDER_EXTERNAL_URL"):
        if source.get(key):
            raise RuntimeError(f"Refusing to launch: {key} indicates a deployed or DB-connected environment")
    return {
        "PATH": source.get("PATH", ""),
        "HOME": source.get("HOME", ""),
        "PYTHONPATH": source.get("PYTHONPATH", ""),
        "VIRTUAL_ENV": source.get("VIRTUAL_ENV", ""),
        "SYSTEMROOT": source.get("SYSTEMROOT", ""),
        "APP_ENV": "demo",
        "AMICOR_ENVIRONMENT": "demo",
        "NOVA_DEMO_STANDALONE": "true",
        "NOVA_DEMO_OWNER_USER": "sample-owner",
        "NOVA_DEMO_OWNER_PASSWORD": secrets.token_urlsafe(32),
    }


def main() -> int:
    try:
        settings = demo_environment(dict(os.environ))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print("\nAMICOR Nova — local synthetic Operations demo", flush=True)
    print("No customer uploads. No Render deployment. No production database.", flush=True)
    print("Address: http://127.0.0.1:8765/api/nova/work/operations/synthetic-acceptance/ui", flush=True)
    print("Demo username: " + settings["NOVA_DEMO_OWNER_USER"], flush=True)
    print("One-time demo password: " + settings["NOVA_DEMO_OWNER_PASSWORD"], flush=True)
    print("Press Ctrl+C to end the session. Do not share this local password.", flush=True)

    # os.execve replaces this process, passing only allowlisted environment
    # variables; the password remains out of command-line arguments.
    executable = sys.executable
    os.execve(executable, [
        executable, "-m", "uvicorn", "scripts.nova_operations_standalone_demo:app",
        "--host", "127.0.0.1", "--port", "8765",
    ], settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
