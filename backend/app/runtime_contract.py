import os
import re

DEFAULT_RUNTIME_VERSION = "20260607.6"

_LOCAL_FRONTEND = "http://127.0.0.1:8010/app"
_LOCAL_BACKEND = "http://127.0.0.1:8010"
_LOCAL_WEBSOCKET = "ws://127.0.0.1:8010/api/health-isf/ws/live"

_PUBLIC_URL_KEYS = ("AMICOR_PUBLIC_URL", "RENDER_EXTERNAL_URL")


def _public_base_url() -> str:
    for key in _PUBLIC_URL_KEYS:
        val = os.environ.get(key, "").strip().rstrip("/")
        if val:
            return val
    return ""


def _request_base_url(request) -> str:
    if request is None:
        return ""
    try:
        forwarded_proto = str(request.headers.get("x-forwarded-proto", "") or "").split(",")[0].strip()
        scheme = forwarded_proto or str(getattr(request.url, "scheme", "") or "https")
        host = str(
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or ""
        ).split(",")[0].strip()
        if not host:
            return ""
        hostname = host.split(":")[0].lower()
        if hostname in {"127.0.0.1", "localhost", "0.0.0.0"}:
            return ""
        return f"{scheme}://{host}".rstrip("/")
    except Exception:
        return ""


def _derive_runtime_urls(*, request=None) -> tuple[str, str, str]:
    public = _public_base_url() or _request_base_url(request)
    if public:
        backend = public
        frontend = f"{public}/app"
        ws_base = public.replace("https://", "wss://").replace("http://", "ws://")
        websocket = f"{ws_base}/api/health-isf/ws/live"
        return frontend, backend, websocket
    return (
        os.environ.get("AMICOR_CANONICAL_FRONTEND_URL", _LOCAL_FRONTEND),
        os.environ.get("AMICOR_BACKEND_URL", _LOCAL_BACKEND),
        os.environ.get("AMICOR_WEBSOCKET_URL", _LOCAL_WEBSOCKET),
    )


def _resolve_runtime_environment(*, public_base: str | None = None) -> str:
    explicit = (os.environ.get("AMICOR_ENVIRONMENT") or os.environ.get("ENVIRONMENT") or "").strip()
    if explicit:
        return explicit
    public = (public_base if public_base is not None else _public_base_url()).strip()
    db_url = os.environ.get("DATABASE_URL", "").strip().lower()
    if public.startswith("https://") and db_url and "sqlite" not in db_url:
        return "production"
    return "development"


def _resolve_build_version() -> str:
    commit = (
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or ""
    ).strip()
    if commit:
        return commit[:12]
    return os.environ.get(
        "APP_VERSION",
        os.environ.get(
            "AMICOR_BUILD_VERSION",
            os.environ.get("AMICOR_FRONTEND_BUILD_VERSION", DEFAULT_RUNTIME_VERSION),
        ),
    )


def build_runtime_contract(*, request=None) -> dict[str, str]:
    frontend_url, backend_url, websocket_url = _derive_runtime_urls(request=request)
    public_base = _public_base_url() or _request_base_url(request)
    return {
        "frontend_url": frontend_url,
        "backend_url": backend_url,
        "websocket_url": websocket_url,
        "environment": _resolve_runtime_environment(public_base=public_base),
        "build_version": _resolve_build_version(),
        "hydration_version": _resolve_build_version(),
        "developer_mode_allowed": "1"
        if os.environ.get("AMICOR_ENABLE_DEVELOPER_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
        else "0",
    }


CANONICAL_FRONTEND_URL, CANONICAL_BACKEND_URL, CANONICAL_WEBSOCKET_URL = _derive_runtime_urls()
RUNTIME_ENVIRONMENT = _resolve_runtime_environment()
DEVELOPER_MODE_ALLOWED = os.environ.get("AMICOR_ENABLE_DEVELOPER_MODE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

CANONICAL_RUNTIME_VERSION = _resolve_build_version()
FRONTEND_BUILD_VERSION = CANONICAL_RUNTIME_VERSION
HYDRATION_VERSION = CANONICAL_RUNTIME_VERSION

RUNTIME_CONTRACT = build_runtime_contract()


def inject_runtime_contract(index_html: str, *, request=None) -> str:
    """Inject runtime contract placeholders into the static app shell."""
    contract = build_runtime_contract(request=request)
    injected = (
        index_html
        .replace("__AMICOR_BUILD_VERSION__", contract["build_version"])
        .replace("__AMICOR_HYDRATION_VERSION__", contract["hydration_version"])
        .replace("__AMICOR_FRONTEND_URL__", contract["frontend_url"])
        .replace("__AMICOR_DEVELOPER_MODE_ALLOWED__", contract["developer_mode_allowed"])
    )

    # Keep static asset versions aligned with the canonical runtime version so
    # a single build bump invalidates every JS/CSS URL in the app shell.
    return re.sub(
        r"([?&]v=)[^\"'&\s>]+",
        lambda match: f"{match.group(1)}{contract['build_version']}",
        injected,
    )
