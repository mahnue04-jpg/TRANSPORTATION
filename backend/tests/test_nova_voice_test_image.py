"""Test-image startup refuses production and any paid provider activation."""
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).parents[1] / "scripts/run_nova_voice_test.py"
spec = importlib.util.spec_from_file_location("nova_voice_test_start", path)
start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start)


def environment():
    return {"RENDER_EXTERNAL_HOSTNAME": start.TEST_HOST,
            "NOVA_CREATIVE_VOICE_PROVIDER": "nova_local", "NOVA_LOCAL_VOICE_ENABLED": "true",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


def test_validation_host_with_local_offline_voice_is_accepted():
    start.validate_environment(environment())


def test_start_uses_one_worker_despite_render_concurrency_default(monkeypatch):
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    for key in start.PAID_FLAGS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setenv("PORT", "10000")
    calls = []
    monkeypatch.setattr(start.os, "execvp", lambda command, args: calls.append((command, args)))
    start.main()
    assert calls == [("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0",
                                   "--port", "10000", "--workers", "1"])]


@pytest.mark.parametrize("key,value", [
    ("RENDER_EXTERNAL_HOSTNAME", "amicor-health-isf-py.onrender.com"),
    ("NOVA_CREATIVE_VOICE_PROVIDER", "openai"), ("NOVA_LOCAL_VOICE_ENABLED", "false"),
    ("HF_HUB_OFFLINE", "0"), ("TRANSFORMERS_OFFLINE", "0"),
])
def test_production_or_incorrect_runtime_settings_are_refused(key, value):
    env = environment(); env[key] = value
    with pytest.raises(RuntimeError): start.validate_environment(env)


@pytest.mark.parametrize("flag", start.PAID_FLAGS)
def test_existing_render_variables_cannot_enable_paid_features(flag):
    env = environment(); env[flag] = "true"
    with pytest.raises(RuntimeError): start.validate_environment(env)
