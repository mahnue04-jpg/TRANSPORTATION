"""Default-off casting flag. Production cannot opt in."""
import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/casting_flags.py"


def load():
    spec = importlib.util.spec_from_file_location("casting_flags_under_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reads_stay_off_unless_explicitly_enabled_outside_production(monkeypatch):
    flags = load()
    monkeypatch.delenv("NOVA_CASTING_STAGING_READS", raising=False)
    monkeypatch.delenv("AMICOR_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    assert flags.casting_staging_reads_enabled() is False
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    assert flags.casting_staging_reads_enabled() is True
    for name, value in (
        ("AMICOR_ENVIRONMENT", "production"),
        ("ENVIRONMENT", "prod"),
        ("APP_ENV", "production"),
    ):
        monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.setenv(name, value)
        assert flags.casting_production_locked() is True
        assert flags.casting_staging_reads_enabled() is False
