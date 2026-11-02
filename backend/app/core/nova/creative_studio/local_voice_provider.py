"""Explicitly selected local Studio voice, isolated in a bounded child process.

No paid fallback or implicit model installation. Existing provider selection
is unchanged unless NOVA_CREATIVE_VOICE_PROVIDER=nova_local is configured.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import wave

try:
    import fcntl
except ImportError:  # Local workers require Linux/POSIX file locking.
    fcntl = None

from .local_voice import VoiceRequest
from .media_runtime import memory_budget
from .narration_qa import inspect_narration_wav
from .provider_types import ProviderStatus, AVAILABLE, CONFIG_REQUIRED, DISABLED, ERROR
from .voice_readiness import check

MIN_FREE_BYTES = 2304 * 1024 * 1024
STOP_RESERVE_BYTES = 256 * 1024 * 1024


class VoiceCapacityError(OSError):
    pass


def _reclaimable_file_cache() -> int:
    for filename, field in (("/sys/fs/cgroup/memory.stat", "inactive_file"),
                            ("/sys/fs/cgroup/memory/memory.stat", "total_inactive_file")):
        try:
            values = dict(line.split() for line in Path(filename).read_text().splitlines())
            if field in values:
                return max(0, int(values[field]))
        except (OSError, ValueError):
            continue
    return 0


def _free_memory_bytes() -> int | None:
    budget = memory_budget()
    if budget is not None:
        # Inactive file cache is reclaimable by the kernel; count neither
        # anonymous model memory nor active file pages as available capacity.
        used, limit = budget
        reclaimable = min(max(0, used), _reclaimable_file_cache())
        return max(0, min(limit, limit - used + reclaimable))
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _run_worker(command, env, log):
    started = time.monotonic()
    child = subprocess.Popen(command, env=env, stdout=log, stderr=log)
    try:
        while child.poll() is None:
            free = _free_memory_bytes()
            if free is None or free < STOP_RESERVE_BYTES:
                raise VoiceCapacityError("Local voice memory reserve reached")
            if time.monotonic() - started > 120:
                raise subprocess.TimeoutExpired(command, 120)
            time.sleep(0.1)
        return child.returncode
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def _media_root():
    from .providers import _creative_media_root_and_prefix
    return _creative_media_root_and_prefix()


class NovaLocalVoiceProvider:
    provider_id = "nova_local_voice"

    def status(self) -> ProviderStatus:
        def state(code, message, configured=False):
            return ProviderStatus(self.provider_id, "voice", code, message, configured)
        if os.getenv("NOVA_LOCAL_VOICE_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return state(DISABLED, "Nova local voice is OFF until explicitly enabled on a validated host.")
        model_dir = os.getenv("NOVA_LOCAL_VOICE_MODEL_DIR", "").strip()
        if not model_dir or not Path(model_dir).is_absolute() or fcntl is None:
            return state(CONFIG_REQUIRED, "Nova local voice needs a preloaded model directory and POSIX worker locking.")
        try:
            ready = check(Path(model_dir))["ready_to_attempt_offline_inference"]
        except OSError:
            ready = False
        if not ready:
            return state(CONFIG_REQUIRED, "Nova local voice model or offline language dependencies are missing.")
        free = _free_memory_bytes()
        if free is None or free < MIN_FREE_BYTES:
            return state(DISABLED, "Nova local voice needs at least 2304 MiB of free memory before starting.", True)
        return state(AVAILABLE, "Nova local narration is available with the reviewed af_heart stock voice. Presenter alignment is separate.", True)

    def generate(self, *, script: str, voice: str | None = None, presenter: bool = False) -> dict:
        def failed(status, message):
            return {"status": status, "message": message, "script": script,
                    "url": None, "asset_generated": False, "paid_provider_calls": False}
        state = self.status()
        if state.status != AVAILABLE:
            return failed(state.status, state.message)
        # Never pretend that OpenAI voice IDs or unaligned captions are local.
        if presenter or voice not in {None, "af_heart", "professional_female"}:
            return failed(CONFIG_REQUIRED, "Use Generate Voice for Nova local narration. This provider has one stock voice; presenter caption alignment is not connected yet.")
        try:
            request = VoiceRequest(script, speed=0.87)
            request.validate()
        except (TypeError, ValueError):
            return failed(ERROR, "Local narration needs 1–1600 characters of text.")
        root, prefix = _media_root()
        try:
            root.mkdir(parents=True, exist_ok=True)
            with (root / ".nova-local-voice.lock").open("a") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return failed(DISABLED, "Nova local voice is busy. No second worker was started.")
                # Admission is checked again while holding the shared host lock.
                state = self.status()
                if state.status != AVAILABLE:
                    return failed(state.status, state.message)
                with tempfile.TemporaryDirectory(prefix=".nova-voice-", dir=root) as work:
                    work = Path(work)
                    script_file, output = work / "script.txt", work / "narration.wav"
                    script_file.write_text(request.text, encoding="utf-8")
                    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                               OMP_NUM_THREADS="2", MKL_NUM_THREADS="2",
                               NOVA_LOCAL_VOICE_PARENT_PID=str(os.getpid()))
                    command = [sys.executable, str(Path(__file__).with_name("local_voice_worker.py")),
                               "--model-dir", os.environ["NOVA_LOCAL_VOICE_MODEL_DIR"],
                               "--output", str(output), "--script-file", str(script_file),
                               "--speed", str(request.speed), "--verify-model"]
                    with tempfile.TemporaryFile() as log:
                        returncode = _run_worker(command, env, log)
                    if returncode or not output.is_file():
                        return failed(ERROR, "Nova local voice worker failed. No paid fallback was used.")
                    report = inspect_narration_wav(output, max_seconds=120)
                    if not report.valid_for_narration or report.peak_fraction >= 1.0:
                        return failed(ERROR, "Nova local narration did not pass WAV validation.")
                    sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
                    filename = "nova-local-" + uuid.uuid4().hex + ".wav"
                    output.replace(root / filename)
                return {"status": "GENERATED", "message": "Nova local narration saved for review.",
                        "script": script, "url": prefix + "/" + filename, "asset_generated": True,
                        "provider_id": self.provider_id, "model": "hexgrad/Kokoro-82M",
                        "voice": "af_heart", "speed": request.speed, "mime_type": "audio/wav",
                        "duration_seconds": report.seconds, "sha256": sha256,
                        "paid_provider_calls": False, "publish_ready": False,
                        "owner_review_required": True, "presenter_alignment": False}
        except subprocess.TimeoutExpired:
            return failed(ERROR, "Nova local voice timed out; the worker was stopped. No paid fallback was used.")
        except VoiceCapacityError:
            return failed(ERROR, "Nova stopped local narration to protect server memory. A host with more capacity is needed.")
        except (OSError, ValueError, KeyError, wave.Error, EOFError):
            return failed(ERROR, "Nova local narration could not be saved. No paid fallback was used.")
