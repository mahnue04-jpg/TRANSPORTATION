"""Non-billable tests for the narrowly scoped Genova Nova voice guard."""
import hashlib
from types import SimpleNamespace

from app.core.nova.creative_studio import providers


SCRIPT = (
    "A colorful ABC coloring adventure begins here!\n"
    "Meet My First ABC Animal Coloring Adventure.\n"
    "Explore letters, animals, and coloring together.\n"
    "A creative activity for families to enjoy.\n"
    "From AMICOR Kids Learning.\n"
    "Find the paperback on Amazon today!\n"
    "Book link in the description."
)


def _guard(monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_SCOPED_TEST", "true")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_TEST_SCRIPT_SHA256", hashlib.sha256(SCRIPT.encode()).hexdigest())
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_MODEL", "gpt-4o-mini-tts")
    monkeypatch.setattr(
        providers.OpenAIVoiceProvider, "status",
        lambda self: SimpleNamespace(status=providers.AVAILABLE),
    )


def test_scoped_voice_rejects_nonmatching_script_without_provider_call(monkeypatch):
    _guard(monkeypatch)
    monkeypatch.setattr(providers, "get_client", lambda: (_ for _ in ()).throw(AssertionError("provider accessed")))
    result = providers.OpenAIVoiceProvider().generate(script=SCRIPT + " Extra.", voice="nova")
    assert result["asset_generated"] is False
    assert result["status"] == "ERROR"


def test_scoped_voice_rejects_wrong_voice_and_presenter_mode(monkeypatch):
    _guard(monkeypatch)
    monkeypatch.setattr(providers, "get_client", lambda: (_ for _ in ()).throw(AssertionError("provider accessed")))
    for params in ({"voice": "coral"}, {"voice": "nova", "presenter": True}):
        result = providers.OpenAIVoiceProvider().generate(script=SCRIPT, **params)
        assert result["asset_generated"] is False


def test_scoped_voice_request_disables_sdk_retries(monkeypatch, tmp_path):
    _guard(monkeypatch)
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_ASSET_DIR", str(tmp_path))
    claim = tmp_path / "one-attempt.claim"
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_TEST_CLAIM_FILE", str(claim))
    calls = []
    class Client:
        def with_options(self, *, max_retries):
            calls.append(("retry", max_retries))
            return self
        @property
        def audio(self):
            return self
        @property
        def speech(self):
            return self
        def create(self, **kwargs):
            calls.append(("create", kwargs))
            return SimpleNamespace(content=b"test-mp3-bytes")
    client = Client()
    monkeypatch.setattr(providers, "get_client", lambda: client)
    result = providers.OpenAIVoiceProvider().generate(script=SCRIPT, voice="nova")
    assert result["asset_generated"] is True
    assert calls[0] == ("retry", 0)
    assert calls[1][0] == "create"
    assert calls[1][1]["voice"] == "nova"
    assert calls[1][1]["input"] == SCRIPT
    assert calls[1][1]["model"] == "gpt-4o-mini-tts"
    assert claim.read_text().startswith("SCOPED_VOICE_TEST_ATTEMPTED")
    repeated = providers.OpenAIVoiceProvider().generate(script=SCRIPT, voice="nova")
    assert repeated["asset_generated"] is False
    assert "already been attempted" in repeated["message"]
    assert len(calls) == 2


def test_scoped_voice_requires_explicit_hash(monkeypatch):
    _guard(monkeypatch)
    monkeypatch.delenv("NOVA_CREATIVE_VOICE_TEST_SCRIPT_SHA256")
    monkeypatch.setattr(providers, "get_client", lambda: (_ for _ in ()).throw(AssertionError("provider accessed")))
    result = providers.OpenAIVoiceProvider().generate(script=SCRIPT, voice="nova")
    assert result["asset_generated"] is False


def test_scoped_voice_requires_persistent_claim_path(monkeypatch):
    _guard(monkeypatch)
    monkeypatch.delenv("NOVA_CREATIVE_VOICE_TEST_CLAIM_FILE", raising=False)
    monkeypatch.setattr(providers, "get_client", lambda: (_ for _ in ()).throw(AssertionError("provider accessed")))
    result = providers.OpenAIVoiceProvider().generate(script=SCRIPT, voice="nova")
    assert result["asset_generated"] is False
    assert "marker is not configured" in result["message"]
