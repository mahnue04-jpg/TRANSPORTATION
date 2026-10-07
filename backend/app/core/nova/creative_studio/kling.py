"""Kling 2.5 Turbo through fal's durable queue; owner activation required."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from app.core.nova.creative_studio.flags import video_provider_live_enabled
from app.core.nova.creative_studio.providers import (
    AVAILABLE, CONFIG_REQUIRED, DISABLED, ERROR, ProviderStatus, RunwayVideoProvider,
)

MODEL = "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"
QUEUE = "https://queue.fal.run/"
TOKEN_PREFIX = "fal-kling25:"


class _SafeKlingError(RuntimeError):
    """Only fixed, application-owned messages may reach the UI."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FalKlingVideoProvider(RunwayVideoProvider):
    """Reuse local media encoding/storage; never use the Runway API."""
    provider_id = "fal_kling_video"

    def _key(self):
        return str(os.getenv("FAL_KEY") or "").strip()

    def status(self):
        if not self._key():
            return ProviderStatus(self.provider_id, "video", CONFIG_REQUIRED,
                                  "Connect a funded fal account to enable Kling video.", False)
        if not video_provider_live_enabled():
            return ProviderStatus(self.provider_id, "video", DISABLED,
                                  "Kling is configured; owner activation is required.", True)
        return ProviderStatus(self.provider_id, "video", AVAILABLE,
                              "Nova Studio Kling video generation is available.", True)

    def _request_json(self, method, url, *, payload=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "queue.fal.run":
            raise _SafeKlingError("Invalid fal queue URL.")
        req = urllib.request.Request(url, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Key {self._key()}", "Content-Type": "application/json"})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=45) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            # Provider bodies may echo input or credentials; don't expose them.
            reasons = {401: "fal API key was rejected", 402: "fal account needs credits",
                       403: "fal access denied; check account permissions or funding",
                       422: "Kling rejected the scene input", 429: "fal is rate limiting requests"}
            raise _SafeKlingError(reasons.get(exc.code, f"fal request failed (HTTP {exc.code})")) from None
        except (urllib.error.URLError, TimeoutError):
            raise _SafeKlingError("fal connection interrupted; do not resubmit until queue usage is checked.") from None

    def _encode_task(self, response):
        task = {key: response.get(key) for key in ("request_id", "status_url", "response_url")}
        self._validate_task(task)
        return TOKEN_PREFIX + base64.urlsafe_b64encode(json.dumps(task).encode()).decode()

    def _validate_task(self, task):
        request_id = task.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 200:
            raise _SafeKlingError("Missing fal request id.")
        for key in ("status_url", "response_url"):
            value = task.get(key)
            if not isinstance(value, str):
                raise _SafeKlingError("Missing fal queue tracking URL.")
            url = urllib.parse.urlsplit(value)
            if (url.scheme != "https" or url.netloc != "queue.fal.run"
                    or not url.path.startswith("/fal-ai/kling-video/requests/")
                    or request_id not in url.path.split("/")
                    or url.query or url.fragment):
                raise _SafeKlingError("Invalid fal queue tracking URL.")

    def generate(self, *, brief):
        result = {"brief": brief, "url": None, "asset_generated": False,
                  "provider": self.provider_id, "model": MODEL,
                  "duration_seconds": 5, "generation_mode": "image_to_motion",
                  "watermark_free": False}
        state = self.status()
        if state.status != AVAILABLE:
            return dict(result, status=state.status, message=state.message)
        token = str(brief.get("resume_task_id") or "")
        try:
            if token:
                if not token.startswith(TOKEN_PREFIX) or len(token) > 4000:
                    raise _SafeKlingError("This saved task does not belong to Kling.")
                task = json.loads(base64.urlsafe_b64decode(token[len(TOKEN_PREFIX):]))
                self._validate_task(task)
            else:
                image = self._prompt_image_value(brief.get("prompt_image_url"))
                if not image:
                    raise _SafeKlingError("Nova could not load source artwork for Kling.")
                submitted = self._request_json("POST", QUEUE + MODEL, payload={
                    "prompt": str(brief.get("prompt_text") or brief.get("objective") or "Cinematic scene")[:2500],
                    "image_url": image, "duration": "5",
                })
                token = self._encode_task(submitted)
                task = json.loads(base64.urlsafe_b64decode(token[len(TOKEN_PREFIX):]))
                if brief.get("persist_task_before_poll"):
                    return dict(result, status="PROCESSING", task_id=token,
                                message="Kling task submitted; its queue reference is saved.")
            # Queue status timeouts preserve the saved reference rather than resubmit.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    status = self._request_json("GET", task["status_url"])
                except RuntimeError:
                    return dict(result, status="PROCESSING", task_id=token,
                                message="Kling queue could not be checked; retry checking the saved task.")
                if status.get("status") == "COMPLETED":
                    if status.get("error"):
                        return dict(result, status=ERROR, task_id=token,
                                    message="Kling generation failed. Review fal usage before starting another shot.")
                    try:
                        output = self._request_json("GET", task["response_url"])
                        url = (output.get("video") or {}).get("url")
                        if not isinstance(url, str) or not url.startswith("https://"):
                            raise ValueError("Kling returned no video output.")
                        saved = self._save_remote_video(url)
                    except Exception:
                        return dict(result, status="PROCESSING", task_id=token,
                                    message="Kling output is not saved yet; retry the same task to recover it.")
                    return dict(result, status="GENERATED", task_id=token, url=saved,
                                asset_generated=True, message="Kling motion clip generated and saved.")
                if status.get("status") not in {"IN_QUEUE", "IN_PROGRESS"}:
                    return dict(result, status="PROCESSING", task_id=token,
                                message="Kling returned an unfamiliar queue state; keep this task for review.")
                time.sleep(5)
            return dict(result, status="PROCESSING", task_id=token,
                        message="Kling is generating; continue checking this saved task.")
        except _SafeKlingError as exc:
            reason = str(exc).rstrip(".")
            return dict(result, status=ERROR, task_id=token or None,
                        message=f"Kling request failed: {reason}. Check fal usage before retrying.")
        except (RuntimeError, ValueError, TypeError, KeyError):
            return dict(result, status=ERROR, task_id=token or None,
                        message="Kling request could not proceed. Check fal key, funding, input and queue usage before retrying.")


LIPSYNC_MODEL = "fal-ai/kling-video/lipsync/audio-to-video"
LIPSYNC_TOKEN_PREFIX = "fal-kling-lipsync:"


class FalKlingLipSyncProvider(FalKlingVideoProvider):
    """Apply narration to an existing presenter clip without Render-side encoding."""
    provider_id = "fal_kling_lipsync"

    def _public_media_url(self, value):
        raw = str(value or "").strip()
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

    def _encode_lipsync_task(self, response):
        task = {key: response.get(key) for key in ("request_id", "status_url", "response_url")}
        self._validate_task(task)
        return LIPSYNC_TOKEN_PREFIX + base64.urlsafe_b64encode(json.dumps(task).encode()).decode()

    def _decode_lipsync_task(self, token):
        if not token.startswith(LIPSYNC_TOKEN_PREFIX) or len(token) > 4000:
            raise _SafeKlingError("This saved task does not belong to Kling LipSync.")
        task = json.loads(base64.urlsafe_b64decode(token[len(LIPSYNC_TOKEN_PREFIX):]))
        self._validate_task(task)
        return task

    def generate_lipsync(self, *, video_url, audio_url, resume_task_id=None):
        result = {
            "url": None,
            "asset_generated": False,
            "provider": self.provider_id,
            "model": LIPSYNC_MODEL,
            "generation_mode": "audio_to_video_lipsync",
            "watermark_free": False,
        }
        state = self.status()
        if state.status != AVAILABLE:
            return dict(result, status=state.status, message=state.message)

        video = self._public_media_url(video_url)
        audio = self._public_media_url(audio_url)
        if not video or not audio:
            return dict(
                result,
                status=ERROR,
                message="Nova could not expose the presenter video and narration to Kling LipSync.",
            )

        token = str(resume_task_id or "").strip()
        try:
            if token:
                task = self._decode_lipsync_task(token)
            else:
                submitted = self._request_json("POST", QUEUE + LIPSYNC_MODEL, payload={
                    "video_url": video,
                    "audio_url": audio,
                })
                token = self._encode_lipsync_task(submitted)
                task = self._decode_lipsync_task(token)

            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                status = self._request_json("GET", task["status_url"])
                provider_state = str(status.get("status") or "").upper()
                if provider_state == "COMPLETED":
                    if status.get("error"):
                        return dict(
                            result,
                            status=ERROR,
                            task_id=token,
                            message="Kling LipSync generation failed. Review fal usage before retrying.",
                        )
                    output = self._request_json("GET", task["response_url"])
                    url = (output.get("video") or {}).get("url")
                    if not isinstance(url, str) or not url.startswith("https://"):
                        return dict(
                            result,
                            status=ERROR,
                            task_id=token,
                            message="Kling LipSync completed but returned no video output.",
                        )
                    saved = self._save_remote_video(url)
                    return dict(
                        result,
                        status="GENERATED",
                        task_id=token,
                        url=saved,
                        asset_generated=True,
                        message="Kling LipSync presenter generated and saved.",
                    )
                if provider_state not in {"IN_QUEUE", "IN_PROGRESS"}:
                    return dict(
                        result,
                        status="PROCESSING",
                        task_id=token,
                        message="Kling LipSync returned an unfamiliar queue state; keep the saved task for review.",
                    )
                time.sleep(5)

            return dict(
                result,
                status="PROCESSING",
                task_id=token,
                message="Kling LipSync is still generating; resume this saved task instead of submitting another.",
            )
        except _SafeKlingError as exc:
            return dict(
                result,
                status=ERROR,
                task_id=token or None,
                message=f"Kling LipSync request failed: {str(exc).rstrip('.')}.",
            )
        except (RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return dict(
                result,
                status=ERROR,
                task_id=token or None,
                message="Kling LipSync could not proceed. Keep the saved task and review fal usage before retrying.",
            )
