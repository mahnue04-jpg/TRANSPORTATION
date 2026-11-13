"""Opt-in, locally operated Kokoro speech adapter.

No model downloads, paid API calls or import-time inference. The caller must
supply an already initialized and license-reviewed Kokoro pipeline.
"""
from array import array
from pathlib import Path
import wave

from .local_voice import VoiceNotReady, VoiceRequest, spoken_text
from .local_voice_alignment import native_chunk_words, script_alignment


class KokoroLocalBackend:
    def __init__(self, pipeline=None):
        self.pipeline = pipeline

    def generate_wav(self, request: VoiceRequest, destination: Path, *, alignment_output: Path | None = None) -> Path:
        request.validate()
        if self.pipeline is None:
            raise VoiceNotReady("Local Kokoro pipeline is not configured; no audio generated.")
        output = Path(destination)
        if output.exists():
            raise FileExistsError("Refusing to overwrite existing narration.")
        if alignment_output is not None and alignment_output.exists():
            raise FileExistsError("Refusing to overwrite existing caption timing.")
        # Use an actual Kokoro voice ID; do not send our generic speaker label.
        voice_id = "af_heart" if request.speaker == "professional_female" else request.speaker
        try:
            kwargs = {"voice": voice_id}
            if request.speed != 1.0:
                kwargs["speed"] = request.speed
            chunks = self.pipeline(spoken_text(request.text), **kwargs)
            values = array("h")
            native_words, alignment_error = [], False
            for chunk in chunks:
                _, _, audio = chunk
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu()
                if hasattr(audio, "tolist"):
                    audio = audio.tolist()
                if alignment_output is not None:
                    try:
                        native_words.extend(native_chunk_words(
                            getattr(chunk, "tokens", None), len(values) / 24000, len(audio) / 24000))
                    except (AttributeError, TypeError, ValueError):
                        alignment_error = True
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
        if alignment_output is not None:
            import hashlib
            import json
            alignment = {"alignment_available": False}
            if not alignment_error:
                try:
                    alignment = script_alignment(request.text, native_words, len(values) / 24000)
                except (KeyError, TypeError, ValueError):
                    pass
            alignment.update(audio_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                             script_sha256=hashlib.sha256(request.text.encode("utf-8")).hexdigest())
            alignment_output.write_text(json.dumps(alignment, allow_nan=False), encoding="utf-8")
        return output
