"""No-provider streaming download integrity checks for owner-scoped MP4s."""
import hashlib
import io

import pytest

from app.core.nova.creative_studio.router import _verified_remote_video_chunks


class TrackingBytes(io.BytesIO):
    pass


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def test_stream_sends_exact_expected_bytes_and_closes():
    data = b"abcdefghij"
    stream = TrackingBytes(data)
    chunks = list(_verified_remote_video_chunks(stream, len(data), _digest(data)))
    assert b"".join(chunks) == data
    assert stream.closed


def test_stream_rejects_truncated_content_and_closes():
    stream = TrackingBytes(b"short")
    with pytest.raises(OSError, match="ended before"):
        list(_verified_remote_video_chunks(stream, 20, _digest(b"short")))
    assert stream.closed


def test_stream_rejects_extra_content_and_closes():
    stream = TrackingBytes(b"too-long")
    with pytest.raises(OSError, match="exceeds"):
        list(_verified_remote_video_chunks(stream, 3, _digest(b"too")))
    assert stream.closed


def test_stream_rejects_corrupted_content_even_with_matching_length():
    stream = TrackingBytes(b"corrupted")
    with pytest.raises(OSError, match="checksum mismatch"):
        list(_verified_remote_video_chunks(stream, 9, _digest(b"unaltered")))
    assert stream.closed


def test_stream_closes_when_read_raises():
    class InterruptedStream(TrackingBytes):
        def read(self, count=-1):
            raise OSError("Network interrupted")

    stream = InterruptedStream(b"abc")
    with pytest.raises(OSError, match="Network interrupted"):
        list(_verified_remote_video_chunks(stream, 3, _digest(b"abc")))
    assert stream.closed


def test_stream_closes_on_client_cancellation():
    data = b"x" * (512 * 1024)
    stream = TrackingBytes(data)
    iterator = _verified_remote_video_chunks(stream, len(data), _digest(data))
    assert next(iterator)
    iterator.close()
    assert stream.closed


def test_stream_rejects_invalid_digest_and_closes():
    stream = TrackingBytes(b"hello")
    with pytest.raises(ValueError, match="Invalid verified"):
        list(_verified_remote_video_chunks(stream, 5, "bad"))
    assert stream.closed
