import os
import re

DEFAULT_RUNTIME_VERSION = "20260607.6"

CANONICAL_FRONTEND_URL = os.environ.get("AMICOR_CANONICAL_FRONTEND_URL", "http://127.0.0.1:8010/app")
CANONICAL_BACKEND_URL = os.environ.get("AMICOR_BACKEND_URL", "http://127.0.0.1:8010")
CANONICAL_WEBSOCKET_URL = os.environ.get("AMICOR_WEBSOCKET_URL", "ws://127.0.0.1:8010/api/health-isf/ws/live")
RUNTIME_ENVIRONMENT = os.environ.get("AMICOR_ENVIRONMENT", os.environ.get("ENVIRONMENT", "development"))
DEVELOPER_MODE_ALLOWED = os.environ.get("AMICOR_ENABLE_DEVELOPER_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}

CANONICAL_RUNTIME_VERSION = os.environ.get(
    "AMICOR_BUILD_VERSION",
    os.environ.get("AMICOR_FRONTEND_BUILD_VERSION", DEFAULT_RUNTIME_VERSION),
)
FRONTEND_BUILD_VERSION = CANONICAL_RUNTIME_VERSION
HYDRATION_VERSION = CANONICAL_RUNTIME_VERSION

RUNTIME_CONTRACT = {
    "frontend_url": CANONICAL_FRONTEND_URL,
    "backend_url": CANONICAL_BACKEND_URL,
    "websocket_url": CANONICAL_WEBSOCKET_URL,
    "environment": RUNTIME_ENVIRONMENT,
    "build_version": FRONTEND_BUILD_VERSION,
    "hydration_version": HYDRATION_VERSION,
    "developer_mode_allowed": "1" if DEVELOPER_MODE_ALLOWED else "0",
}


def inject_runtime_contract(index_html: str) -> str:
    """Inject runtime contract placeholders into the static app shell."""
    injected = (
        index_html
        .replace("__AMICOR_BUILD_VERSION__", FRONTEND_BUILD_VERSION)
        .replace("__AMICOR_HYDRATION_VERSION__", HYDRATION_VERSION)
        .replace("__AMICOR_FRONTEND_URL__", CANONICAL_FRONTEND_URL)
        .replace("__AMICOR_DEVELOPER_MODE_ALLOWED__", "1" if DEVELOPER_MODE_ALLOWED else "0")
    )

    # Keep static asset versions aligned with the canonical runtime version so
    # a single build bump invalidates every JS/CSS URL in the app shell.
    return re.sub(
        r"([?&]v=)[^\"'&\s>]+",
        lambda match: f"{match.group(1)}{FRONTEND_BUILD_VERSION}",
        injected,
    )
