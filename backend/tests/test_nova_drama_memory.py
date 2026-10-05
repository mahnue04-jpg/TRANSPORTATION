"""Exercise drama budgets against the 512 MiB service and preserve live protection."""
import pytest
import sys
from app.core.nova.creative_studio import drama, media_runtime as runtime


@pytest.mark.parametrize("used", [276 * runtime.MIB, 306679808])
def test_drama_encoder_can_start_at_production_headroom(monkeypatch, used):
    # Include the exact cgroup usage recorded when the video segment was blocked.
    monkeypatch.setattr(runtime, 'memory_budget', lambda: (used, 512 * runtime.MIB))
    command = [sys.executable, '-c', 'pass']
    assert runtime.run_encoder(command, timeout=5).returncode == 1
    for headroom in (drama.DRAMA_AUDIO_HEADROOM, drama.DRAMA_VIDEO_HEADROOM):
        assert runtime.run_encoder(command, timeout=5, required_headroom=headroom).returncode == 0


def test_drama_still_refuses_to_start_when_memory_is_low(monkeypatch):
    monkeypatch.setattr(runtime, 'memory_budget', lambda: (330 * runtime.MIB, 512 * runtime.MIB))
    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(AssertionError('encoder must not start')))
    result = runtime.run_encoder(['ffmpeg'], timeout=5, required_headroom=drama.DRAMA_VIDEO_HEADROOM)
    assert result.returncode == 1 and 'No encoder was started' in result.stderr


def test_running_drama_encoder_stops_before_consuming_server_reserve(monkeypatch):
    budgets = iter([(276 * runtime.MIB, 512 * runtime.MIB), (420 * runtime.MIB, 512 * runtime.MIB)])
    monkeypatch.setattr(runtime, 'memory_budget', lambda: next(budgets))
    class Child:
        returncode = None
        killed = False
        def poll(self): return self.returncode
        def kill(self): self.killed = True; self.returncode = -9
        def wait(self): return self.returncode
    child = Child()
    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *a, **k: child)
    result = runtime.run_encoder(['ffmpeg'], timeout=5, required_headroom=drama.DRAMA_VIDEO_HEADROOM)
    assert child.killed and result.returncode != 0
    assert 'protect the server' in result.stderr
