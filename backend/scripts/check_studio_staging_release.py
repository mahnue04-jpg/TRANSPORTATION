"""Read-only AMICOR Creative Studio staging HTTP release smoke test.

Uses only unauthenticated GET requests against the exact validation host.
No passwords, bearer tokens, provider calls, database writes, or deployments.
A passing check is NOT proof of signed-in media playback or paid video generation.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


ALLOWED_HOST = "nova-studio-validation-350.onrender.com"


class ReleaseCheckError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReleaseCheckError("UNEXPECTED_REDIRECT")


def validate_origin(value: str) -> str:
    url = urllib.parse.urlsplit(value)
    if (url.scheme != "https" or url.hostname != ALLOWED_HOST
            or url.port not in (None, 443) or url.username or url.password
            or url.query or url.fragment or url.path not in ("", "/")):
        raise ReleaseCheckError("STAGING_ORIGIN_REQUIRED")
    return f"https://{ALLOWED_HOST}"


def _get(opener, origin: str, path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        origin + path, headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=20) as response:
            return int(response.status), response.read(65536)
    except urllib.error.HTTPError as exc:
        # Status only. Never log response body; unauthorized bodies may contain details.
        exc.close()
        return int(exc.code), b""
    except ReleaseCheckError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise ReleaseCheckError("STAGING_REQUEST_FAILED") from exc


def check(origin: str, opener=None) -> dict:
    origin = validate_origin(origin)
    opener = opener or urllib.request.build_opener(_NoRedirect())
    status, raw = _get(opener, origin, "/api/health/detail")
    if status != 200:
        raise ReleaseCheckError("STAGING_HEALTH_HTTP_FAILED")
    try:
        document = json.loads(raw)
        payload = document["data"]
        db = payload["db"]
        healthy = payload["status"] == "healthy" and db["ok"] is True
        backend = db["backend"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReleaseCheckError("STAGING_HEALTH_RESPONSE_INVALID") from exc
    if not healthy:
        raise ReleaseCheckError("STAGING_DATABASE_UNHEALTHY")
    if backend != "sqlite":
        # This release gate tracks existing SQLite until a reviewed, verified
        # cutover changes the expected backend. Fail rather than misreport.
        raise ReleaseCheckError("UNREVIEWED_STAGING_DATABASE_SWITCH")
    checks = {
        "staging_health": "pass",
        "current_database_backend": "sqlite",
        "project_list_requires_auth": "pending",
        "video_file_requires_auth": "pending",
    }
    protected = (
        ("/api/nova/creative/projects", "project_list_requires_auth"),
        (
            "/api/nova/creative/projects/invalid-smoke-project/"
            "assets/invalid-smoke-video/file",
            "video_file_requires_auth",
        ),
    )
    for path, name in protected:
        code, _ = _get(opener, origin, path)
        if code != 401:
            raise ReleaseCheckError("PRIVATE_ROUTE_NOT_AUTH_GATED")
        checks[name] = "pass"
    checks["customer_playback_verified"] = False
    checks["paid_generation_verified"] = False
    checks["media_storage_verified"] = False
    return checks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=f"https://{ALLOWED_HOST}")
    args = parser.parse_args(argv)
    try:
        print(json.dumps({"status": "passed", "checks": check(args.base_url)}, sort_keys=True))
        return 0
    except ReleaseCheckError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
