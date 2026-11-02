"""Local provider admission, worker cleanup and byte-preserving media output."""
import ast
from pathlib import Path
import subprocess
import sys
import wave

import pytest
import local_voice_provider as provider


@pytest.fixture
def ready(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_LOCAL_VOICE_ENABLED", "true")
    monkeypatch.setenv("NOVA_LOCAL_VOICE_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setattr(provider, "check", lambda _: {"ready_to_attempt_offline_inference": True})
    monkeypatch.setattr(provider, "_free_memory_bytes", lambda: provider.MIN_FREE_BYTES)
    monkeypatch.setattr(provider, "_media_root", lambda: (tmp_path / "media", "/media/nova-creative"))
    return tmp_path / "media"


def write_audio(command, env, log):
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert "--verify-model" in command
    assert command[command.index("--speed") + 1] == "0.87"
    script = Path(command[command.index("--script-file") + 1]).read_text()
    assert script == "Hello AMICOR"
    with wave.open(command[command.index("--output") + 1], "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(b"\x00\x20\x00\xe0" * 2400)
    return 0


def test_success_saves_complete_wav_and_provenance(ready, monkeypatch):
    monkeypatch.setattr(provider, "_run_worker", write_audio)
    result = provider.NovaLocalVoiceProvider().generate(script="Hello AMICOR")
    assert result["status"] == "GENERATED"
    assert result["voice"] == "af_heart"
    assert result["paid_provider_calls"] is False
    assert result["owner_review_required"] is True
    assert result["publish_ready"] is False
    path = ready / result["url"].rsplit("/", 1)[1]
    import hashlib
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(list(ready.glob("*.wav"))) == 1
    assert not list(ready.glob(".nova-voice-*"))


def aligned_audio(command, env, log):
    import hashlib
    import json
    write_audio(command, env, log)
    output = Path(command[command.index("--output") + 1])
    data = {"alignment_available": True, "alignment_source": "kokoro_native_token_durations",
            "duration_seconds": .2, "words": [
                {"word": "Hello", "start": 0, "end": .1},
                {"word": "AMICOR", "start": .1, "end": .2}],
            "audio_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(b"Hello AMICOR").hexdigest()}
    Path(command[command.index("--alignment-output") + 1]).write_text(json.dumps(data))
    return 0


def test_parent_attaches_only_matching_native_caption_timing(ready, monkeypatch):
    monkeypatch.setattr(provider, "_run_worker", aligned_audio)
    result = provider.NovaLocalVoiceProvider().generate(script="Hello AMICOR")
    assert result["caption_alignment"] is True
    assert result["caption_cues"] == [{"text": "Hello AMICOR", "start": 0, "end": .2}]
    assert result["presenter_alignment"] is False


@pytest.mark.parametrize("damage", ["audio", "words", "json"])
def test_bad_sidecar_never_becomes_caption_timing(ready, monkeypatch, damage):
    import json
    def worker(command, env, log):
        aligned_audio(command, env, log)
        path = Path(command[command.index("--alignment-output") + 1])
        data = json.loads(path.read_text())
        if damage == "audio": data["audio_sha256"] = "different recording"
        if damage == "words": data["words"][0]["word"] = "Changed"
        path.write_text("invalid json" if damage == "json" else json.dumps(data))
        return 0
    monkeypatch.setattr(provider, "_run_worker", worker)
    result = provider.NovaLocalVoiceProvider().generate(script="Hello AMICOR")
    assert result["status"] == "GENERATED" and result["caption_alignment"] is False
    assert "caption_cues" not in result


@pytest.mark.parametrize("condition", ["disabled", "missing_model", "low_memory", "unknown_memory", "missing_lock"])
def test_unready_provider_never_starts_worker(ready, monkeypatch, condition):
    def forbidden(*_): raise AssertionError("worker must not run")
    monkeypatch.setattr(provider, "_run_worker", forbidden)
    if condition == "disabled": monkeypatch.delenv("NOVA_LOCAL_VOICE_ENABLED")
    if condition == "missing_model": monkeypatch.setattr(provider, "check", lambda _: {"ready_to_attempt_offline_inference": False})
    if condition == "low_memory": monkeypatch.setattr(provider, "_free_memory_bytes", lambda: 512 * 1024 * 1024)
    if condition == "unknown_memory": monkeypatch.setattr(provider, "_free_memory_bytes", lambda: None)
    if condition == "missing_lock": monkeypatch.setattr(provider, "fcntl", None)
    result = provider.NovaLocalVoiceProvider().generate(script="Hello AMICOR")
    assert not result["asset_generated"]
    assert result["url"] is None
    assert not ready.exists()


def test_shared_host_lock_rejects_second_worker(ready, monkeypatch):
    ready.mkdir()
    with (ready / ".nova-local-voice.lock").open("a") as lock:
        provider.fcntl.flock(lock.fileno(), provider.fcntl.LOCK_EX | provider.fcntl.LOCK_NB)
        monkeypatch.setattr(provider, "_run_worker", lambda *_: pytest.fail("duplicate worker"))
        result = provider.NovaLocalVoiceProvider().generate(script="Hello AMICOR")
        assert "busy" in result["message"]
        assert result["url"] is None


@pytest.mark.parametrize("condition", ["failed", "timeout", "silent", "malformed"])
def test_failed_worker_leaves_no_published_or_temporary_audio(ready, monkeypatch, condition):
    def worker(command, env, log):
        output = Path(command[command.index("--output") + 1])
        if condition == "timeout":
            output.write_bytes(b"partial")
            raise subprocess.TimeoutExpired(command, 120)
        if condition == "failed": return 1
        if condition == "malformed": output.write_bytes(b"invalid"); return 0
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b"\x00\x00" * 2400)
        return 0
    monkeypatch.setattr(provider, "_run_worker", worker)
    result = provider.NovaLocalVoiceProvider().generate(script="Hello AMICOR")
    assert result["status"] == "ERROR"
    assert result["url"] is None
    assert not list(ready.glob("*.wav"))
    assert not list(ready.glob(".nova-voice-*"))


@pytest.mark.parametrize("payload", [{"script": ""}, {"script": "x" * 1601}, {"script": "Hi", "voice": "coral"}, {"script": "Hi", "presenter": True}])
def test_invalid_text_or_unconnected_presenter_never_runs(ready, monkeypatch, payload):
    monkeypatch.setattr(provider, "_run_worker", lambda *_: pytest.fail("unexpected worker"))
    assert not provider.NovaLocalVoiceProvider().generate(**payload)["asset_generated"]


@pytest.mark.parametrize("reason", ["memory", "timeout"])
def test_resource_monitor_kills_and_reaps_worker(monkeypatch, reason):
    class Child:
        returncode = None
        killed = False
        waited = False
        def poll(self): return self.returncode
        def kill(self): self.killed = True; self.returncode = -9
        def wait(self): self.waited = True
    child = Child()
    monkeypatch.setattr(provider.subprocess, "Popen", lambda *_, **__: child)
    monkeypatch.setattr(provider, "_free_memory_bytes", lambda: 1 if reason == "memory" else provider.MIN_FREE_BYTES)
    ticks = iter([0, 121])
    monkeypatch.setattr(provider.time, "monotonic", lambda: next(ticks))
    with pytest.raises((OSError, subprocess.TimeoutExpired)):
        provider._run_worker(["worker"], {}, None)
    assert child.killed and child.waited


def test_factory_preserves_default_and_never_falls_back_from_local_or_unknown(monkeypatch):
    # Compile the actual factory without importing unrelated image/video SDKs.
    source = Path(__file__).with_name("providers.py")
    if not source.exists():
        source = Path(__file__).parents[1] / "app/core/nova/creative_studio/providers.py"
    tree = ast.parse(source.read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name in {"voice_provider", "UnsupportedVoiceProvider"}]
    import os
    from provider_types import ProviderStatus, CONFIG_REQUIRED
    class External:
        provider_id = "openai_voice"
    namespace = {"os": os, "OpenAIVoiceProvider": External, "ProviderStatus": ProviderStatus,
                 "CONFIG_REQUIRED": CONFIG_REQUIRED, "Any": object, "VoiceGenerationProvider": object}
    monkeypatch.setitem(sys.modules, "app.core.nova.creative_studio.local_voice_provider", provider)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    monkeypatch.delenv("NOVA_CREATIVE_VOICE_PROVIDER", raising=False)
    assert namespace["voice_provider"]().provider_id == "openai_voice"
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PROVIDER", "nova_local")
    assert namespace["voice_provider"]().provider_id == "nova_local_voice"
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PROVIDER", "typo_local")
    result = namespace["voice_provider"]().generate(script="Hello")
    assert result["status"] == "CONFIG_REQUIRED" and not result["asset_generated"]


def test_readiness_flags_follow_selected_provider_not_external_credential(monkeypatch, tmp_path):
    import flags
    import voice_readiness
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "true")
    monkeypatch.delenv("NOVA_CREATIVE_VOICE_PROVIDER", raising=False)
    assert flags.voice_provider_configured() and flags.voice_provider_live_enabled()
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PROVIDER", "nova_local")
    monkeypatch.setenv("NOVA_LOCAL_VOICE_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(voice_readiness, "check", lambda _: {"ready_to_attempt_offline_inference": True})
    monkeypatch.delenv("NOVA_LOCAL_VOICE_ENABLED", raising=False)
    assert flags.voice_provider_configured() and not flags.voice_provider_live_enabled()
    monkeypatch.setenv("NOVA_LOCAL_VOICE_ENABLED", "true")
    assert flags.voice_provider_live_enabled()
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PROVIDER", "typo_local")
    assert not flags.voice_provider_configured() and not flags.voice_provider_live_enabled()


def test_memory_headroom_counts_only_reclaimable_inactive_file_cache(monkeypatch):
    monkeypatch.setattr(provider, "memory_budget", lambda: (3500, 4096))
    monkeypatch.setattr(provider, "_reclaimable_file_cache", lambda: 500)
    assert provider._free_memory_bytes() == 1096
    monkeypatch.setattr(provider, "_reclaimable_file_cache", lambda: 0)
    assert provider._free_memory_bytes() == 596
    monkeypatch.setattr(provider, "_reclaimable_file_cache", lambda: 9000)
    assert provider._free_memory_bytes() == 4096
