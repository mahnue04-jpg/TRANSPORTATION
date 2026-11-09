"""No-provider streaming download integrity checks for owner-scoped MP4s."""
import io

import pytest

from app.core.nova.creative_studio.router import _verified_remote_video_chunks


class TrackingBytes(io.BytesIO):
    pass


def test_stream_sends_exact_expected_bytes_and_closes():
    stream = TrackingBytes(b"abcdefghij")
    chunks = list(_verified_remote_video_chunks(stream, 10))
    assert b"".join(chunks) == b"abcdefghij"
    assert stream.closed


def test_stream_rejects_truncated_content_and_closes():
    stream = TrackingBytes(b"short")
    with pytest.raises(OSError, match="ended before"):
        list(_verified_remote_video_chunks(stream, 20))
    assert stream.closed


def test_stream_rejects_extra_content_and_closes():
    stream = TrackingBytes(b"too-long")
    with pytest.raises(OSError, match="exceeds"):
        list(_verified_remote_video_chunks(stream, 3))
    assert stream.closed


def test_stream_closes_when_read_raises():
    class InterruptedStream(TrackingBytes):
        def read(self, count=-1):
            raise OSError("Network interrupted")

    stream = InterruptedStream(b"abc")
    with pytest.raises(OSError, match="Network interrupted"):
        list(_verified_remote_video_chunks(stream, 3))
    assert stream.closed


def test_stream_closes_on_client_cancellation():
    stream = TrackingBytes(b"x" * (512 * 1024))
    iterator = _verified_remote_video_chunks(stream, 512 * 1024)
    assert next(iterator)
    iterator.close()
    assert stream.closed
