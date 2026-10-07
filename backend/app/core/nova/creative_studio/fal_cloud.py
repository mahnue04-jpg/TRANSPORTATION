"""Cloud media post-processing through fal queue APIs.

Keeps expensive video transforms off the small Render web instance. All calls are
owner-triggered through Creative Studio routes and preserve resumable queue tokens
so retries do not submit duplicate paid jobs.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.core.nova.creative_studio.providers import RunwayVideoProvider

QUEUE = "https://queue.fal.run/"
TOKEN_PREFIX = "fal-cloud:"


class FalCloudError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FalCloudProcessor:
    def __init__(self) -> None:
        self._saver = RunwayVideoProvider()

    def _key(self) -> str:
        return str(os.getenv("FAL_KEY") or "").strip()

    def available(self) -> bool:
        return bool(self._key())

    def _public_url(self, value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.startswith("https://"):
            return raw
        if raw.startswith("/"):
            base = str(
                os.getenv("AMICOR_PUBLIC_URL")
                or os.getenv("RENDER_EXTERNAL_URL")
                or ""
            ).strip().rstrip("/")
            if base.startswith("https://"):
                return base + raw
        return None

    def _request_json(self, method: str, url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "queue.fal.run":
            raise FalCloudError("Invalid fal queue URL.")
        req = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": f"Key {self._key()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=45) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            reasons = {
                401: "fal API key was rejected",
                402: "fal account needs credits",
                403: "fal access denied; check account permissions or funding",
                422: "fal rejected the media input",
                429: "fal is rate limiting requests",
            }
            raise FalCloudError(reasons.get(exc.code, f"fal request failed (HTTP {exc.code})")) from None
        except (urllib.error.URLError, TimeoutError):
            raise FalCloudError("fal connection interrupted; keep the saved task and retry status later.") from None

    def _encode_task(self, model: str, response: dict[str, Any]) -> str:
        task = {
            "model": model,
            "request_id": response.get("request_id"),
            "status_url": response.get("status_url"),
            "response_url": response.get("response_url"),
        }
        self._validate_task(task)
        return TOKEN_PREFIX + base64.urlsafe_b64encode(json.dumps(task).encode()).decode()

    def _decode_task(self, token: str, model: str) -> dict[str, Any]:
        if not token.startswith(TOKEN_PREFIX) or len(token) > 6000:
            raise FalCloudError("Saved fal task is invalid.")
        try:
            task = json.loads(base64.urlsafe_b64decode(token[len(TOKEN_PREFIX):]))
        except Exception as exc:
            raise FalCloudError("Saved fal task could not be decoded.") from exc
        self._validate_task(task)
        if task.get("model") != model:
            raise FalCloudError("Saved fal task belongs to another media stage.")
        return task

    def _validate_task(self, task: dict[str, Any]) -> None:
        request_id = task.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 200:
            raise FalCloudError("Missing fal request id.")
        model = task.get("model")
        if not isinstance(model, str) or not model.startswith(("fal-ai/", "veed/")):
            raise FalCloudError("Invalid fal model.")
        for key in ("status_url", "response_url"):
            value = task.get(key)
            if not isinstance(value, str):
                raise FalCloudError("Missing fal queue tracking URL.")
            parsed = urllib.parse.urlsplit(value)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "queue.fal.run"
                or request_id not in parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise FalCloudError("Invalid fal queue tracking URL.")

    def run(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        resume_task_id: str | None = None,
        wait_seconds: int = 75,
    ) -> dict[str, Any]:
        if not self.available():
            return {
                "status": "CONFIG_REQUIRED",
                "message": "Connect a funded fal account to enable cloud video post-processing.",
                "asset_generated": False,
                "url": None,
                "provider": "fal_cloud",
                "model": model,
            }

        try:
            token = str(resume_task_id or "").strip()
            if token:
                task = self._decode_task(token, model)
            else:
                submitted = self._request_json("POST", QUEUE + model, payload=payload)
                token = self._encode_task(model, submitted)
                task = self._decode_task(token, model)

            deadline = time.monotonic() + max(15, int(wait_seconds))
            while time.monotonic() < deadline:
                status = self._request_json("GET", task["status_url"])
                state = str(status.get("status") or "").upper()
                if state == "COMPLETED":
                    if status.get("error"):
                        return {
                            "status": "ERROR",
                            "message": "fal cloud processing failed. Review provider usage before resubmitting.",
                            "asset_generated": False,
                            "url": None,
                            "provider": "fal_cloud",
                            "model": model,
                            "task_id": token,
                        }
                    output = self._request_json("GET", task["response_url"])
                    remote = ((output.get("video") or {}).get("url"))
                    if not isinstance(remote, str) or not remote.startswith("https://"):
                        return {
                            "status": "ERROR",
                            "message": "fal completed but returned no video output.",
                            "asset_generated": False,
                            "url": None,
                            "provider": "fal_cloud",
                            "model": model,
                            "task_id": token,
                        }
                    saved = self._saver._save_remote_video(remote)
                    return {
                        "status": "GENERATED",
                        "message": "fal cloud video processing completed and Nova saved the result.",
                        "asset_generated": True,
                        "url": saved,
                        "provider": "fal_cloud",
                        "model": model,
                        "task_id": token,
                    }
                if state not in {"IN_QUEUE", "IN_PROGRESS"}:
                    return {
                        "status": "PROCESSING",
                        "message": "fal returned an unfamiliar queue state; keep this saved task for review.",
                        "asset_generated": False,
                        "url": None,
                        "provider": "fal_cloud",
                        "model": model,
                        "task_id": token,
                    }
                time.sleep(4)
            return {
                "status": "PROCESSING",
                "message": "fal is still processing; resume this saved task instead of submitting again.",
                "asset_generated": False,
                "url": None,
                "provider": "fal_cloud",
                "model": model,
                "task_id": token,
            }
        except FalCloudError as exc:
            return {
                "status": "ERROR",
                "message": f"fal cloud processing could not proceed: {str(exc).rstrip('.')}.",
                "asset_generated": False,
                "url": None,
                "provider": "fal_cloud",
                "model": model,
                "task_id": str(resume_task_id or "") or None,
            }

    def lip_sync(self, *, video_url: str, audio_url: str, resume_task_id: str | None = None) -> dict[str, Any]:
        model = "fal-ai/kling-video/lipsync/audio-to-video"
        video = self._public_url(video_url)
        audio = self._public_url(audio_url)
        if not video or not audio:
            return {
                "status": "ERROR",
                "message": "Nova could not expose the presenter video and narration to the cloud lip-sync service.",
                "asset_generated": False,
                "url": None,
                "provider": "fal_cloud",
                "model": model,
            }
        return self.run(
            model=model,
            payload={"video_url": video, "audio_url": audio},
            resume_task_id=resume_task_id,
        )

    def auto_subtitle(self, *, video_url: str, resume_task_id: str | None = None) -> dict[str, Any]:
        model = "fal-ai/workflow-utilities/auto-subtitle"
        video = self._public_url(video_url)
        if not video:
            return {
                "status": "ERROR",
                "message": "Nova could not expose the talking-presenter video to the cloud subtitle service.",
                "asset_generated": False,
                "url": None,
                "provider": "fal_cloud",
                "model": model,
            }
        return self.run(
            model=model,
            payload={
                "video_url": video,
                "language": "en",
                "font_name": "Montserrat",
            },
            resume_task_id=resume_task_id,
        )

    def merge_videos(self, *, video_urls: list[str], resume_task_id: str | None = None) -> dict[str, Any]:
        model = "fal-ai/ffmpeg-api/merge-videos"
        public_urls = [self._public_url(url) for url in video_urls]
        if not public_urls or any(not url for url in public_urls):
            return {
                "status": "ERROR",
                "message": "Nova could not expose all scene videos to the cloud merge service.",
                "asset_generated": False,
                "url": None,
                "provider": "fal_cloud",
                "model": model,
            }
        return self.run(
            model=model,
            payload={"video_urls": public_urls, "resolution": "landscape_16_9"},
            resume_task_id=resume_task_id,
            wait_seconds=120,
        )
