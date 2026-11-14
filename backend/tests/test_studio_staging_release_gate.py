"""No-network tests for the fail-closed Studio staging release gate."""
import importlib.util
import io
from pathlib import Path
import urllib.error

import pytest

spec = importlib.util.spec_from_file_location(
    "studio_release_gate",
    Path(__file__).resolve().parents[1] / "scripts/check_studio_staging_release.py",
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Response:
    def __init__(self, code, body=b""):
        self.status = code
        self.body = io.BytesIO(body)

    def read(self, n=-1):
        return self.body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, health=b'{"data":{"status":"healthy","db":{"ok":true,"backend":"sqlite"}}}',
                 project_code=401, video_code=401):
        self.health = health
        self.project_code = project_code
        self.video_code = video_code
        self.paths = []

    def open(self, request, timeout=20):
        assert request.get_method() == "GET"
        assert not request.has_header("Authorization")
        path = request.full_url.partition("onrender.com")[2]
        self.paths.append(path)
        if path == "/api/health/detail":
            return Response(200, self.health)
        code = self.video_code if "/assets/" in path else self.project_code
        raise urllib.error.HTTPError(request.full_url, code, "Denied", None, None)


@pytest.mark.parametrize("origin", [
    "http://nova-studio-validation-350.onrender.com",
    "https://evil.example.org",
    "https://nova-studio-validation-350.onrender.com.evil.example.org",
    "https://user:pass@nova-studio-validation-350.onrender.com",
    "https://nova-studio-validation-350.onrender.com?token=secret",
    "https://nova-studio-validation-350.onrender.com/other",
])
def test_only_exact_https_staging_origin_allowed(origin):
    with pytest.raises(gate.ReleaseCheckError, match="STAGING_ORIGIN_REQUIRED"):
        gate.validate_origin(origin)


def test_healthy_sqlite_and_both_private_routes_pass_without_provider_calls():
    fake = FakeOpener()
    result = gate.check("https://nova-studio-validation-350.onrender.com", fake)
    assert len(fake.paths) == 3
    assert result["staging_health"] == "pass"
    assert result["project_list_requires_auth"] == "pass"
    assert result["video_file_requires_auth"] == "pass"
    assert result["customer_playback_verified"] is False
    assert result["paid_generation_verified"] is False


@pytest.mark.parametrize("project_code,video_code", [
    (200, 401), (401, 200), (403, 401), (401, 404),
])
def test_private_route_must_return_exact_401(project_code, video_code):
    with pytest.raises(gate.ReleaseCheckError, match="PRIVATE_ROUTE_NOT_AUTH_GATED"):
        gate.check("https://nova-studio-validation-350.onrender.com",
                   FakeOpener(project_code=project_code, video_code=video_code))


def test_health_invalid_json_fails_closed():
    with pytest.raises(gate.ReleaseCheckError, match="STAGING_HEALTH_RESPONSE_INVALID"):
        gate.check("https://nova-studio-validation-350.onrender.com", FakeOpener(health=b"{}"))


def test_health_critical_fails_closed():
    health = b'{"data":{"status":"healthy","db":{"ok":false,"backend":"sqlite"}}}'
    with pytest.raises(gate.ReleaseCheckError, match="STAGING_DATABASE_UNHEALTHY"):
        gate.check("https://nova-studio-validation-350.onrender.com", FakeOpener(health=health))


def test_unreviewed_postgres_switch_fails_closed():
    health = b'{"data":{"status":"healthy","db":{"ok":true,"backend":"postgresql"}}}'
    with pytest.raises(gate.ReleaseCheckError, match="UNREVIEWED_STAGING_DATABASE_SWITCH"):
        gate.check("https://nova-studio-validation-350.onrender.com", FakeOpener(health=health))
