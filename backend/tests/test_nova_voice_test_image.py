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
