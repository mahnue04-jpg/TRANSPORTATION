"""Opt-in, locally operated Kokoro speech adapter.

No model downloads, paid API calls or import-time inference. The caller must
supply an already initialized and license-reviewed Kokoro pipeline.
"""
from array import array
from pathlib import Path
import wave

from .local_voice import VoiceNotReady, VoiceRequest, spoken_text


class KokoroLocalBackend:
    def __init__(self, pipeline=None):
        self.pipeline = pipeline

    def generate_wav(self, request: VoiceRequest, destination: Path) -> Path:
        request.validate()
        if self.pipeline is None:
            raise VoiceNotReady("Local Kokoro pipeline is not configured; no audio generated.")
        output = Path(destination)
        if output.exists():
            raise FileExistsError("Refusing to overwrite existing narration.")
        # Use an actual Kokoro voice ID; do not send our generic speaker label.
        voice_id = "af_heart" if request.speaker == "professional_female" else request.speaker
        try:
            chunks = self.pipeline(spoken_text(request.text), voice=voice_id)
            values = array("h")
            for _, _, audio in chunks:
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu()
                if hasattr(audio, "tolist"):
                    audio = audio.tolist()
                for sample in audio:
                    value = max(-1.0, min(1.0, float(sample)))
                    values.append(int(value * 32767))
        except Exception as exc:
            raise VoiceNotReady("Local Kokoro inference failed; no external fallback used.") from exc
        if not values:
            raise VoiceNotReady("Local speech model returned no samples.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(values.tobytes())
        return output
