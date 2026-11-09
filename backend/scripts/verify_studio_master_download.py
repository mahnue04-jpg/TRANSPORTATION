#!/usr/bin/env python3
"""No-provider staging validation of an owner-scoped Creative Studio master MP4.

Examples:
  NOVA_STUDIO_STAGING_BEARER=... python backend/scripts/verify_studio_master_download.py \
    --base-url https://staging.example.com --project-id PROJECT --asset-id ASSET \
    --sha256 EXPECTED_64_HEX --output /tmp/staging-master.mp4

  python backend/scripts/verify_studio_master_download.py \
    --local-file /tmp/staging-master.mp4 --sha256 EXPECTED_64_HEX

Do not place bearer tokens in URLs, shell arguments or CI logs. Never call a
paid media provider, trigger an export or upload media from this verifier.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 2 * 1024 * 1024 * 1024
CHUNK = 1024 * 1024
SHA = re.compile(r"^[0-9a-fA-F]{64}$")
ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class VerificationError(Exception):
    pass


def digest_reader(reader, sink, expected_bytes: int | None, expected_sha: str) -> int:
    """Hash real file bytes during transfer and fail on truncation or tampering."""
    if not SHA.fullmatch(expected_sha):
        raise VerificationError("Invalid expected SHA-256.")
    if expected_bytes is not None and not (0 < expected_bytes <= MAX_BYTES):
        raise VerificationError("Missing or invalid positive Content-Length.")
    h = hashlib.sha256()
    received = 0
    while True:
        chunk = reader.read(CHUNK)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise VerificationError("Transfer returned non-binary data.")
        received += len(chunk)
        if received > MAX_BYTES or (expected_bytes is not None and received > expected_bytes):
            raise VerificationError("Download exceeded its verified size.")
        h.update(chunk)
        if sink is not None:
            sink.write(chunk)
    if received == 0 or (expected_bytes is not None and received != expected_bytes):
        raise VerificationError("Download incomplete or empty.")
    if h.hexdigest() != expected_sha.lower():
        raise VerificationError("Downloaded MP4 SHA-256 differs from expected source.")
    return received


def inspect_mp4(path: Path) -> dict:
    """Inspect the actual downloaded MP4 with ffprobe; ffprobe is read-only."""
    try:
        raw = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,format_name:stream=codec_type,codec_name,width,height",
             "-of", "json", str(path)],
            text=True, capture_output=True, check=True, timeout=90,
        )
        result = json.loads(raw.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise VerificationError("FFprobe failed on the completed MP4.") from exc
    streams = result.get("streams") or []
    video = next((x for x in streams if x.get("codec_type") == "video"), None)
    audio = next((x for x in streams if x.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise VerificationError("Downloaded master must have both video and audio streams.")
    try:
        duration = float((result.get("format") or {}).get("duration") or 0)
    except (ValueError, TypeError):
        duration = 0
    if not duration > 0:
        raise VerificationError("Downloaded master has no valid duration.")
    return {
        "duration_seconds": round(duration, 3),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "width": video.get("width"), "height": video.get("height"),
    }


def _download_url(base_url: str, project_id: str, asset_id: str) -> str:
    parts = urllib.parse.urlsplit(base_url)
    if (parts.scheme != "https" or not parts.netloc or parts.username
            or parts.password or parts.query or parts.fragment):
        raise VerificationError("Use an HTTPS staging origin without credentials or query parameters.")
    if not ID.fullmatch(project_id) or not ID.fullmatch(asset_id):
        raise VerificationError("Invalid project or asset identifier.")
    return (base_url.rstrip("/") + "/api/nova/creative/projects/" +
            urllib.parse.quote(project_id, safe="") + "/assets/" +
            urllib.parse.quote(asset_id, safe="") + "/file")


def download_staging_master(base_url: str, project_id: str, asset_id: str,
                            expected_sha: str, output: Path, token: str) -> int:
    if not token or "\n" in token or "\r" in token:
        raise VerificationError("Staging bearer must be supplied securely in the environment.")
    if output.exists():
        raise VerificationError("Refusing to overwrite an existing file.")
    url = _download_url(base_url, project_id, asset_id)
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + token, "Accept": "video/mp4"},
        method="GET",
    )
    # Never follow redirects: authorization headers must not be forwarded to a new host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise VerificationError("Staging download redirected unexpectedly.")
    opener = urllib.request.build_opener(NoRedirect)
    partial = output.with_name(output.name + ".partial")
    if partial.exists():
        raise VerificationError("Old partial file exists; inspect it rather than overwrite.")
    try:
        with opener.open(request, timeout=90) as response:
            if response.status != 200:
                raise VerificationError("Private staging download returned a non-200 response.")
            mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if mime != "video/mp4":
                raise VerificationError("Staging returned non-MP4 content.")
            raw_length = response.headers.get("Content-Length", "")
            if not raw_length.isdigit():
                raise VerificationError("Staging omitted exact Content-Length.")
            expected_bytes = int(raw_length)
            with partial.open("xb") as handle:
                count = digest_reader(response, handle, expected_bytes, expected_sha)
        partial.rename(output)
        return count
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--project-id")
    parser.add_argument("--asset-id")
    parser.add_argument("--local-file")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.local_file:
            if any((args.base_url, args.project_id, args.asset_id, args.output)):
                raise VerificationError("Local-file mode cannot also request a remote download.")
            target = Path(args.local_file)
            with target.open("rb") as source:
                count = digest_reader(source, None, None, args.sha256)
        else:
            if not all((args.base_url, args.project_id, args.asset_id, args.output)):
                raise VerificationError("Remote mode requires origin, project, asset and output.")
            target = Path(args.output)
            count = download_staging_master(
                args.base_url, args.project_id, args.asset_id,
                args.sha256, target, os.getenv("NOVA_STUDIO_STAGING_BEARER", ""),
            )
        media = inspect_mp4(target)
        print(json.dumps({"result": "verified", "bytes": count, "sha256": args.sha256.lower(),
                          "media": media}, sort_keys=True))
        return 0
    except (VerificationError, OSError, urllib.error.URLError) as exc:
        # Avoid echoing exception URLs/tokens/response bodies to shared logs.
        print("Verification failed. Check staging URL, protected access, file integrity and FFprobe.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
