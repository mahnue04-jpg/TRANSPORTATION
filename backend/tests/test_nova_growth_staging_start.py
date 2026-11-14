"""Pure staging launcher unit tests; never start a server or connect to a DB."""
import pytest

from app.core.nova.growth_agent import staging_start


def _env():
    return {
        "RENDER_GIT_COMMIT": "b" * 40,
        "NOVA_GA_ISOLATED_SKIP_DB_BOOTSTRAP": "true",
        "NOVA_GA_APPROVED_STAGING_SHA": "b" * 40,
        "APP_ENV": "staging",
        "AMICOR_ENVIRONMENT": "staging",
        "DATABASE_URL": "postgresql://synthetic:fake@dpg-dbqv7mmtlv9c73d7tnb0-a/nova_ga_490_dispos",
        "NOVA_STRIPE_LIVE_ENABLED": "false",
        "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED": "false",
        "PORT": "10000",
    }


def test_safe_command_contains_only_fixed_uvicorn_launch():
    command = staging_start.build_uvicorn_argv(_env())
    assert command[1:] == [
        "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", "10000", "--workers", "1",
    ]
    assert not any("pytest" in part or "alembic" in part for part in command)


@pytest.mark.parametrize("port", ["", "0", "65536", "-1", "10000; echo unsafe", "abc"])
def test_bad_port_rejected(port):
    env = _env()
    env["PORT"] = port
    with pytest.raises(ValueError, match="PORT"):
        staging_start.build_uvicorn_argv(env)


def test_wrong_commit_prevents_server_start():
    env = _env()
    env["RENDER_GIT_COMMIT"] = "c" * 40
    with pytest.raises(ValueError, match="commit"):
        staging_start.build_uvicorn_argv(env)


def test_main_exits_without_exec_on_preflight_denial(monkeypatch, capsys):
    env = _env()
    env["APP_ENV"] = "production"
    monkeypatch.setattr(staging_start.os, "environ", env)
    def forbidden_exec(*args):
        raise AssertionError("exec must not be called for denied environment")
    monkeypatch.setattr(staging_start.os, "execv", forbidden_exec)
    assert staging_start.main() == 1
    captured = capsys.readouterr()
    assert "APP_ENV" in captured.err
    assert "fake" not in captured.err


def test_main_execs_only_after_validation(monkeypatch):
    env = _env()
    monkeypatch.setattr(staging_start.os, "environ", env)
    class ExecCalled(Exception):
        pass
    def capture_exec(executable, args):
        assert executable == staging_start.sys.executable
        assert args[1:4] == ["-m", "uvicorn", "app.main:app"]
        raise ExecCalled
    monkeypatch.setattr(staging_start.os, "execv", capture_exec)
    with pytest.raises(ExecCalled):
        staging_start.main()


def test_launcher_denies_missing_isolation_flag():
    env = _env()
    env.pop("NOVA_GA_ISOLATED_SKIP_DB_BOOTSTRAP")
    with pytest.raises(ValueError, match="bootstrap bypass"):
        staging_start.build_uvicorn_argv(env)
