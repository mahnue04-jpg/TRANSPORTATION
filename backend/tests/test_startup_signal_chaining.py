"""The platform status hook must preserve ASGI server shutdown."""
import signal
from app import startup


def test_shutdown_status_preserves_server_handler(monkeypatch):
    calls = []
    def server_handler(signum, frame):
        calls.append(signum)
    handlers = {signal.SIGTERM: server_handler, signal.SIGINT: server_handler}
    monkeypatch.setattr(startup, '_previous_shutdown_handlers', {})
    monkeypatch.setattr(startup, '_shutdown_requested', False)
    monkeypatch.setattr(signal, 'getsignal', lambda sig: handlers[sig])
    monkeypatch.setattr(signal, 'signal', lambda sig, fn: handlers.__setitem__(sig, fn))
    startup.register_shutdown_handlers()
    startup.register_shutdown_handlers()
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert startup.is_shutdown_requested()
    assert calls == [signal.SIGTERM]


def test_non_callable_previous_handler_is_not_called(monkeypatch):
    monkeypatch.setattr(startup, '_previous_shutdown_handlers', {signal.SIGTERM: signal.SIG_DFL})
    monkeypatch.setattr(startup, '_shutdown_requested', False)
    startup._handle_shutdown(signal.SIGTERM, None)
    assert startup.is_shutdown_requested()
