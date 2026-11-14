"""Regression guard: authenticated Studio MP4 preview stays playable after metadata load.

The real browser playback test remains an owner-operated staging gate. This test
checks the shipped JavaScript for the specific premature URL revocation that
produced an inert 0:00 player despite a valid downloadable MP4.
"""
from pathlib import Path


def test_private_mp4_blob_url_lives_until_asset_list_replacement():
    js = (Path(__file__).resolve().parents[1] / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert 'var privateVideoPreviewUrls = [];' in js
    assert 'privateVideoPreviewUrls.push(objectUrl);' in js
    assert 'video.src = objectUrl;' in js
    assert 'video.load();' in js
    assert 'clearPrivateVideoPreviewUrls();\n    $("asset-list").innerHTML' in js
    assert 'clearPrivateVideoPreviewUrls();\n      $("asset-list").innerHTML' in js
    assert 'video.addEventListener("loadeddata", function () { URL.revokeObjectURL(objectUrl); }' not in js
    assert 'video.addEventListener("error", function () { URL.revokeObjectURL(objectUrl); }' not in js
    assert 'data-private-video-url=' in js
    assert 'assertDownloadUrlHasNoToken(path);' in js


def test_private_video_playback_diagnostics_are_visible_and_no_payment_is_triggered():
    js = (Path(__file__).resolve().parents[1] / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    html = (Path(__file__).resolve().parents[1] / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    assert "Load and play saved video (free)" in js
    assert 'class=\\\"hint private-video-status\\\" role=\\\"status\\\"' in js
    assert 'if (playButton) playButton.addEventListener("click"' in js
    assert 'video.addEventListener("loadedmetadata"' in js
    assert 'video.addEventListener("error"' in js
    assert 'Preview unavailable (' in js
    assert 'startPlayback && video.src && video.readyState >= 1' in js
    assert "creative.js?v=private-video-playback-diagnostics-20261112" in html
