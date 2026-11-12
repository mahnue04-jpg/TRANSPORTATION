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
