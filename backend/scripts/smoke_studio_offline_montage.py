"""Production-image smoke test: produce a genuine 30-second offline MP4.

Run inside the Studio Docker image, not against a customer's saved project.
All output is disposable. This does not establish publishing rights or lip sync.
"""
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.nova.creative_studio.offline_commercial import render_offline_montage


def main() -> None:
    headings = ["Hook", "Problem", "Capabilities", "Process", "Progress", "CTA"]
    scenes = [
        {
            "heading": heading,
            "duration_seconds": 5,
            "voiceover_text": f"Nova helps small businesses stay organized. Scene {index}.",
            "subtitle_text": f"Organize your work with Nova. Step {index}.",
        }
        for index, heading in enumerate(headings, start=1)
    ]
    with TemporaryDirectory(prefix="studio-image-smoke-") as work:
        mp4 = Path(work) / "thirty-second-test.mp4"
        wav = Path(work) / "test-narration.wav"
        result = render_offline_montage(scenes, output_mp4=mp4, audio_wav=wav)
        assert mp4.is_file() and mp4.stat().st_size > 10240, "MP4 missing or empty"
        assert wav.is_file() and wav.stat().st_size > 44, "WAV missing or empty"
        assert mp4.with_suffix(".srt").is_file(), "Subtitles missing"
        assert 28 <= result["duration_seconds"] <= 31, result
        assert result["audio_present"] is True, result
        assert result["captions_burned_in"] is True, result
        assert result["paid_provider_charges"] is False, result
        assert result["publish_ready"] is False, result
        artifact_dir = os.environ.get("STUDIO_SMOKE_OUTPUT_DIR")
        if artifact_dir:
            target = Path(artifact_dir)
            target.mkdir(parents=True, exist_ok=True)
            for source in (mp4, wav, mp4.with_suffix(".srt")):
                shutil.copy2(source, target / source.name)
        print("PASS 30-second offline MP4, WAV, SRT, audio present; no paid providers")


if __name__ == "__main__":
    main()
