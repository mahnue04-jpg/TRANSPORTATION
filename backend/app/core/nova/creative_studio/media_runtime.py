"""Shared media capacity and cgroup-aware encoder protection."""
from __future__ import annotations

import functools
import logging
from pathlib import Path
import subprocess
import tempfile
import threading
import time

logger = logging.getLogger(__name__)
_media_lock = threading.RLock()
MIB = 1024 * 1024
ENCODER_HEADROOM = 256 * MIB
SERVER_RESERVE = 96 * MIB


def memory_budget() -> tuple[int, int] | None:
    for used_path, limit_path in (
        ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
        ("/sys/fs/cgroup/memory/memory.usage_in_bytes", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        try:
            used = int(Path(used_path).read_text().strip())
            limit = int(Path(limit_path).read_text().strip())
            if 0 < limit < 1 << 60:
                return used, limit
        except (OSError, ValueError):
            continue
    return None


def serialized_media(fn):
    """Images, scene motion and final promos share one reentrant capacity slot."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with _media_lock:
            logger.info("CREATIVE_MEDIA_BEGIN phase=%s memory_budget=%s", fn.__name__, memory_budget())
            try:
                return fn(*args, **kwargs)
            finally:
                logger.info("CREATIVE_MEDIA_END phase=%s memory_budget=%s", fn.__name__, memory_budget())
    return wrapped


def run_encoder(
    cmd: list[str],
    *,
    timeout: int,
    required_headroom: int | None = None,
) -> subprocess.CompletedProcess:
    """Bound logs and abort the encoder while memory remains for web traffic."""
    budget = memory_budget()
    headroom = ENCODER_HEADROOM if required_headroom is None else max(SERVER_RESERVE, int(required_headroom))
    if budget and budget[1] - budget[0] < headroom:
        message = "Nova paused video rendering: insufficient server memory headroom. No encoder was started."
        logger.warning("CREATIVE_ENCODER_MEMORY_BLOCKED memory_budget=%s", budget)
        return subprocess.CompletedProcess(cmd, 1, "", message)
    started = time.monotonic()
    stopped_for_memory = False
    peak = budget[0] if budget else 0
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(cmd, stdout=output, stderr=output)
        try:
            while child.poll() is None:
                budget = memory_budget()
                if budget:
                    peak = max(peak, budget[0])
                    if budget[1] - budget[0] < SERVER_RESERVE:
                        stopped_for_memory = True
                        child.kill()
                        logger.warning("CREATIVE_ENCODER_MEMORY_STOPPED memory_budget=%s", budget)
                        break
                if time.monotonic() - started > timeout:
                    raise subprocess.TimeoutExpired(cmd, timeout)
                time.sleep(0.02)
            child.wait()
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
        output.seek(0, 2)
        output.seek(max(0, output.tell() - 16384))
        detail = output.read().decode("utf-8", errors="replace")
    logger.info("CREATIVE_ENCODER_END peak_cgroup_bytes=%s returncode=%s", peak, child.returncode)
    if stopped_for_memory:
        detail = "Nova stopped video rendering to protect the server from its memory limit. The render did not complete."
    return subprocess.CompletedProcess(cmd, child.returncode or (1 if stopped_for_memory else 0), "", detail)
