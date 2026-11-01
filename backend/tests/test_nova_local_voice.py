"""Non-billable tests for Nova's local-only voice contract."""
from pathlib import Path

import pytest

from app.core.nova.creative_studio.local_voice import (
    UnconfiguredLocalVoiceBackend, VoiceNotReady, VoiceRequest, spoken_text,
)


def test_amico_brand_is_phonetic_for_audio_only():
    original = "Welcome to AMICOR Nova. AMICOR helps your business."
    audio = spoken_text(original)
    assert audio == "Welcome to Ammy Core Nova. Ammy Core helps your business."
    assert original == "Welcome to AMICOR Nova. AMICOR helps your business."


def test_local_backend_fails_closed_without_model(tmp_path: Path):
    output = tmp_path / "voice.wav"
    with pytest.raises(VoiceNotReady, match="No AMICOR-operated speech model"):
        UnconfiguredLocalVoiceBackend().generate_wav(
            VoiceRequest("Welcome to AMICOR Nova"), output
        )
    assert not output.exists()


def test_invalid_local_voice_requests():
    for text in ("", " " * 3, "x" * 1601):
        with pytest.raises(ValueError):
            VoiceRequest(text).validate()
