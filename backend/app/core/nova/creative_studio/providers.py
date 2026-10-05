"""Provider-neutral Creative Studio media interfaces. No secrets in code."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
import re
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Protocol
from xml.sax.saxutils import escape as escape_xml
from openai import APITimeoutError

try:
    from runwayml import RunwayML
except Exception:  # pragma: no cover - surfaced by provider status/generation path
    RunwayML = None  # type: ignore[assignment]

from app.ai import get_client

from app.core.nova.creative_studio.flags import (
    image_provider_configured,
    image_provider_live_enabled,
    selected_video_provider,
    video_provider_configured,
    video_provider_live_enabled,
    voice_provider_configured,
    voice_provider_live_enabled,
    talking_presenter_provider_configured,
    talking_presenter_provider_live_enabled,
)



def _creative_media_root_and_prefix() -> tuple[Path, str]:
    configured = str(os.getenv("NOVA_CREATIVE_MEDIA_DIR") or "").strip()
    if configured:
        root = Path(configured)
        prefix = str(os.getenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX") or "/media/nova-creative").rstrip("/")
        return root, prefix

    persistent_parent = Path("/data/onboarding_docs")
    if persistent_parent.exists():
        return persistent_parent / "nova_creative_media", "/media/nova-creative"

    root = Path(__file__).resolve().parents[4] / "static" / "generated" / "nova-creative"
    return root, "/static/generated/nova-creative"


def _resolve_creative_media_url(value: str | None) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    root, prefix = _creative_media_root_and_prefix()
    if raw.startswith(prefix + "/"):
        return root / raw.rsplit("/", 1)[-1]
    if raw.startswith("/static/generated/nova-creative/"):
        backend_root = Path(__file__).resolve().parents[4]
        return backend_root / raw.lstrip("/")
    return None

AVAILABLE = "AVAILABLE"
CONFIG_REQUIRED = "CONFIG_REQUIRED"
DISABLED = "DISABLED"
ERROR = "ERROR"

IMAGE_ASPECTS = ("1:1", "4:5", "9:16", "16:9")


@dataclass
class ProviderStatus:
    provider_id: str
    kind: str
    status: str
    message: str
    configured: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind,
            "status": self.status,
            "message": self.message,
            "configured": self.configured,
        }


class ImageGenerationProvider(Protocol):
    provider_id: str

    def status(self) -> ProviderStatus:
        ...

    def generate(self, *, prompt: str, aspect_ratio: str) -> dict[str, Any]:
        ...


class VideoGenerationProvider(Protocol):
    provider_id: str

    def status(self) -> ProviderStatus:
        ...

    def generate(self, *, brief: dict[str, Any]) -> dict[str, Any]:
        ...


class VoiceGenerationProvider(Protocol):
    provider_id: str

    def status(self) -> ProviderStatus:
        ...

    def generate(self, *, script: str, voice: str | None = None, presenter: bool = False) -> dict[str, Any]:
        ...


class TalkingPresenterProvider(Protocol):
    provider_id: str

    def status(self) -> ProviderStatus:
        ...

    def generate(self, *, presenter_image_url: str, script: str, audio_url: str | None = None) -> dict[str, Any]:
        ...


class OpenAIImageProvider:
    provider_id = "openai_image"

    def status(self) -> ProviderStatus:
        if not image_provider_configured():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="image",
                status=CONFIG_REQUIRED,
                message="The existing OpenAI server credential is not configured.",
                configured=False,
            )
        if not image_provider_live_enabled():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="image",
                status=DISABLED,
                message="Image provider is configured but live generation is OFF until owner activation.",
                configured=True,
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            kind="image",
            status=AVAILABLE,
            message="Nova Studio image generation is available.",
            configured=True,
        )

    @staticmethod
    def _size(aspect_ratio: str) -> str:
        return {
            "1:1": "1024x1024",
            "4:5": "1024x1536",
            "9:16": "1024x1536",
            "16:9": "1536x1024",
        }.get(aspect_ratio, "1024x1024")

    def generate(self, *, prompt: str, aspect_ratio: str) -> dict[str, Any]:
        st = self.status()
        if st.status != AVAILABLE:
            return {
                "status": st.status,
                "message": st.message,
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "url": None,
                "asset_generated": False,
            }
        model = str(os.getenv("NOVA_CREATIVE_IMAGE_MODEL") or "gpt-image-2").strip()
        # Image generation can exceed the shared 30-second chat timeout.
        # Use one bounded attempt; automatic retries may duplicate paid work.
        client = get_client().with_options(timeout=300.0, max_retries=0)
        try:
            result = client.images.generate(
                model=model,
                prompt=prompt,
                size=self._size(aspect_ratio),
                n=1,
            )
        except APITimeoutError:
            return {
                "status": "ERROR",
                "message": "Image generation timed out after waiting up to 300 seconds. No image was saved. The provider may still have processed the request; review usage before retrying.",
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "url": None,
                "asset_generated": False,
            }
        rows = list(getattr(result, "data", None) or [])
        row = rows[0] if rows else None
        image_url = str(getattr(row, "url", "") or "").strip() or None
        encoded = str(getattr(row, "b64_json", "") or "").strip() or None
        if not image_url and encoded:
            try:
                binary = base64.b64decode(encoded)
            except Exception as exc:
                raise RuntimeError("Image provider returned invalid image data") from exc
            configured_dir = str(os.getenv("NOVA_CREATIVE_IMAGE_ASSET_DIR") or "").strip()
            if configured_dir:
                root = Path(configured_dir)
                public_prefix = str(
                    os.getenv("NOVA_CREATIVE_IMAGE_PUBLIC_PREFIX")
                    or "/media/nova-creative"
                ).rstrip("/")
            else:
                root, public_prefix = _creative_media_root_and_prefix()
            root.mkdir(parents=True, exist_ok=True)
            filename = f"nova-{uuid.uuid4().hex}.png"
            (root / filename).write_bytes(binary)
            image_url = f"{public_prefix}/{filename}"
        if not image_url:
            return {
                "status": ERROR,
                "message": "Image provider returned no image asset.",
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "url": None,
                "asset_generated": False,
            }
        return {
            "status": "GENERATED",
            "message": "Image generated successfully.",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "url": image_url,
            "asset_generated": True,
            "model": model,
        }


class RunwayVideoProvider:
    provider_id = "runway_video"

    def _key(self) -> str:
        return str(
            os.getenv("RUNWAYML_API_SECRET")
            or os.getenv("NOVA_CREATIVE_VIDEO_API_KEY")
            or ""
        ).strip()

    def status(self) -> ProviderStatus:
        if not video_provider_configured():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="video",
                status=CONFIG_REQUIRED,
                message="Runway video credential is not configured.",
                configured=False,
            )
        if not video_provider_live_enabled():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="video",
                status=DISABLED,
                message="Runway video is configured but live generation is OFF until owner activation.",
                configured=True,
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            kind="video",
            status=AVAILABLE,
            message="Nova Studio AI video generation is available.",
            configured=True,
        )

    def _request_json(self, method: str, url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key()}",
                "X-Runway-Version": "2024-11-06",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = detail[:1200]
            try:
                parsed = json.loads(detail)
                primary = str(
                    parsed.get("error")
                    or parsed.get("message")
                    or parsed.get("detail")
                    or "Runway validation failed"
                )
                issues = parsed.get("issues") or []
                issue_text = "; ".join(
                    f"{'.'.join(str(x) for x in (item.get('path') or [])) or 'request'}: {item.get('message')}"
                    for item in issues
                    if isinstance(item, dict) and item.get("message")
                )
                message = f"{primary}" + (f" — {issue_text}" if issue_text else "")
            except Exception:
                pass
            raise RuntimeError(f"Runway API error ({exc.code}): {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Runway API connection failed: {exc.reason}") from exc

    def _save_remote_video(self, url: str) -> str:
        configured_dir = str(os.getenv("NOVA_CREATIVE_VIDEO_ASSET_DIR") or "").strip()
        if configured_dir:
            root = Path(configured_dir)
            public_prefix = str(
                os.getenv("NOVA_CREATIVE_VIDEO_PUBLIC_PREFIX")
                or "/media/nova-creative"
            ).rstrip("/")
        else:
            root, public_prefix = _creative_media_root_and_prefix()
        root.mkdir(parents=True, exist_ok=True)
        filename = f"nova-{uuid.uuid4().hex}.mp4"
        target = root / filename
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                with target.open("wb") as output:
                    while chunk := resp.read(1024 * 1024):
                        output.write(chunk)
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise RuntimeError("Runway generated video but Nova could not save the MP4 asset.") from exc
        return f"{public_prefix}/{filename}"

    def _prompt_image_value(self, value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.startswith("data:image/"):
            return raw
        if raw.startswith("https://"):
            return raw

        # Prefer sending generated local images inline as data URIs. This avoids
        # Runway having to fetch an ephemeral Render static URL that can return
        # 404 across instances or after a deploy.
        local_path = _resolve_creative_media_url(raw)
        if local_path is not None:
            try:
                data = local_path.read_bytes()
            except OSError:
                data = b""
            if data:
                suffix = local_path.suffix.lower()
                mime = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }.get(suffix, "image/png")
                encoded = base64.b64encode(data).decode("ascii")
                return f"data:{mime};base64,{encoded}"

        # Last-resort public URL for non-local assets.
        if raw.startswith("/"):
            base = str(
                os.getenv("AMICOR_PUBLIC_URL")
                or os.getenv("RENDER_EXTERNAL_URL")
                or ""
            ).strip().rstrip("/")
            if base.startswith("https://"):
                return base + raw
        return None

    def generate(self, *, brief: dict[str, Any]) -> dict[str, Any]:
        st = self.status()
        if st.status != AVAILABLE:
            return {
                "status": st.status,
                "message": st.message,
                "brief": brief,
                "url": None,
                "asset_generated": False,
            }

        prompt_text = str(
            brief.get("prompt_text")
            or brief.get("objective")
            or brief.get("title")
            or "Professional small-business operations promo video"
        ).strip()
        platform = str(brief.get("platform") or "").strip().lower()
        requested_aspect = str(brief.get("aspect_ratio") or "").strip()
        ratio = {
            "9:16": "720:1280",
            "16:9": "1280:720",
            "1:1": "1024:1024",
        }.get(requested_aspect)
        if ratio is None:
            ratio = "720:1280" if platform in {"tiktok", "instagram", "youtube shorts"} else "1280:720"
        duration = int(str(os.getenv("NOVA_CREATIVE_VIDEO_DURATION_SECONDS") or "5"))
        if duration < 2 or duration > 10:
            duration = 5
        model = str(os.getenv("NOVA_CREATIVE_VIDEO_MODEL") or "gen4.5").strip()

        task_id = str(brief.get("resume_task_id") or "").strip()
        prompt_image = self._prompt_image_value(brief.get("prompt_image_url"))
        if not task_id:
            if not prompt_image:
                return {
                    "status": ERROR,
                    "message": "Nova could not load the generated source image for Runway motion generation.",
                    "brief": brief,
                    "url": None,
                    "asset_generated": False,
                    "model": model,
                    "duration_seconds": duration,
                    "ratio": ratio,
                }
            if RunwayML is None:
                return {
                    "status": ERROR,
                    "message": "Runway Python SDK is not installed on the server.",
                    "brief": brief,
                    "url": None,
                    "asset_generated": False,
                    "model": model,
                    "duration_seconds": duration,
                    "ratio": ratio,
                }
            try:
                client = RunwayML(api_key=self._key())
                created = client.image_to_video.create(
                    model=model,
                    prompt_image=prompt_image,
                    prompt_text=prompt_text[:1000],
                    ratio=ratio,
                    duration=duration,
                )
            except Exception as exc:
                return {
                    "status": ERROR,
                    "message": f"Runway motion generation error: {exc}",
                    "brief": brief,
                    "url": None,
                    "asset_generated": False,
                    "model": model,
                    "duration_seconds": duration,
                    "ratio": ratio,
                }

            task_id = str(
                getattr(created, "id", None)
                or (created.get("id") if isinstance(created, dict) else "")
                or ""
            ).strip()
            if not task_id:
                return {
                    "status": ERROR,
                    "message": "Runway did not return a motion-video task id.",
                    "brief": brief,
                    "url": None,
                    "asset_generated": False,
                }

            # Let the background service commit the remote task ID before any
            # polling/download. A process restart can then reconnect to it.
            if brief.get("persist_task_before_poll"):
                return {
                    "status": "PROCESSING", "task_id": task_id,
                    "message": "Runway task submitted; reconnecting to saved task.",
                    "brief": brief, "url": None, "asset_generated": False,
                    "provider": self.provider_id,
                }

        wait_seconds = int(str(os.getenv("NOVA_CREATIVE_VIDEO_WAIT_SECONDS") or "90"))
        deadline = time.monotonic() + max(15, wait_seconds)
        task: dict[str, Any] = {"id": task_id, "status": "PENDING"}

        while time.monotonic() < deadline:
            time.sleep(5)
            try:
                task = self._request_json("GET", f"https://api.dev.runwayml.com/v1/tasks/{task_id}")
            except RuntimeError as exc:
                return {
                    "status": ERROR,
                    "message": str(exc),
                    "brief": brief,
                    "url": None,
                    "asset_generated": False,
                    "task_id": task_id,
                }

            state = str(task.get("status") or "").upper()
            if state == "SUCCEEDED":
                outputs = list(task.get("output") or [])
                if not outputs:
                    return {
                        "status": ERROR,
                        "message": "Runway completed the task but returned no video output.",
                        "brief": brief,
                        "url": None,
                        "asset_generated": False,
                        "task_id": task_id,
                    }
                saved_url = self._save_remote_video(str(outputs[0]))
                return {
                    "status": "GENERATED",
                    "message": "AI video generated successfully.",
                    "brief": brief,
                    "url": saved_url,
                    "asset_generated": True,
                    "model": model,
                    "task_id": task_id,
                    "duration_seconds": duration,
                    "ratio": ratio,
                    "generation_mode": "image_to_motion",
                    "watermark_free": str(os.getenv("NOVA_CREATIVE_VIDEO_WATERMARK_FREE_OUTPUT") or "").strip().lower() in {"1", "true", "yes", "on"},
                }

            if state in {"FAILED", "CANCELED"}:
                return {
                    "status": ERROR,
                    "message": str(task.get("failure") or task.get("failureCode") or f"Runway task {state.lower()}."),
                    "brief": brief,
                    "url": None,
                    "asset_generated": False,
                    "task_id": task_id,
                }

        return {
            "status": "PROCESSING",
            "message": "Runway is still generating this motion clip. Click Generate Real AI Video again to continue checking the same task.",
            "brief": brief,
            "url": None,
            "asset_generated": False,
            "task_id": task_id,
            "model": model,
            "duration_seconds": duration,
            "ratio": ratio,
            "generation_mode": "text_to_video",
        }


class OpenAIVoiceProvider:
    provider_id = "openai_voice"

    def status(self) -> ProviderStatus:
        if not voice_provider_configured():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="voice",
                status=CONFIG_REQUIRED,
                message="The existing OpenAI server credential is not configured.",
                configured=False,
            )
        if not voice_provider_live_enabled():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="voice",
                status=DISABLED,
                message="Voice provider is configured but live generation is OFF until owner activation.",
                configured=True,
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            kind="voice",
            status=AVAILABLE,
            message="Nova Studio voice generation is available.",
            configured=True,
        )

    def generate(self, *, script: str, voice: str | None = None, presenter: bool = False) -> dict[str, Any]:
        st = self.status()
        if st.status != AVAILABLE:
            return {
                "status": st.status,
                "message": st.message,
                "script": script,
                "url": None,
                "asset_generated": False,
            }
        clean = str(script or "").strip()
        if not clean:
            return {
                "status": ERROR,
                "message": "No voiceover script is available.",
                "script": clean,
                "url": None,
                "asset_generated": False,
            }
        model = str(os.getenv("NOVA_CREATIVE_VOICE_MODEL") or "gpt-4o-mini-tts").strip()
        voice = str(voice or os.getenv("NOVA_CREATIVE_VOICE_NAME") or "alloy").strip()
        if voice not in {"alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"}:
            raise ValueError("Unsupported Studio voice")
        speech_args = dict(model=model, voice=voice, input=clean[:4000], response_format="mp3")
        if presenter and model.startswith("gpt-4o-mini-tts"):
            speech_args['instructions'] = (
                'Speak as a young adult woman in her early thirties, with a clear feminine voice. '
                'Warm, confident, friendly professional delivery. Clear diction and natural pacing. '
                'Use a bright conversational speaking tone, never whisper or use a low male register. '
                'Read every word exactly. Pronounce AMICOR as AM ih core. Do not add any words.'
            )
        response = get_client().audio.speech.create(**speech_args)
        binary = getattr(response, "content", None)
        if binary is None and hasattr(response, "read"):
            binary = response.read()
        if not binary:
            raise RuntimeError("Voice provider returned no audio data.")

        configured_dir = str(os.getenv("NOVA_CREATIVE_VOICE_ASSET_DIR") or "").strip()
        if configured_dir:
            root = Path(configured_dir)
            public_prefix = str(
                os.getenv("NOVA_CREATIVE_VOICE_PUBLIC_PREFIX")
                or "/media/nova-creative"
            ).rstrip("/")
        else:
            root, public_prefix = _creative_media_root_and_prefix()
        root.mkdir(parents=True, exist_ok=True)
        filename = f"nova-{uuid.uuid4().hex}.mp3"
        (root / filename).write_bytes(bytes(binary))
        presenter_result = {}
        if presenter:
            from app.core.nova.creative_studio.presenter_media import normalize_narration, caption_cues
            normalized, loudness = normalize_narration(root / filename)
            filename = normalized.name
            with normalized.open('rb') as audio_file:
                transcript = get_client().audio.transcriptions.create(
                    model='whisper-1', file=audio_file, response_format='verbose_json',
                    timestamp_granularities=['word'], language='en', prompt=clean[:4000],
                )
            data = transcript.model_dump() if hasattr(transcript, 'model_dump') else transcript
            cues = caption_cues(clean, data.get('words') or [], float(data['duration']))
            presenter_result = {'caption_cues': cues, 'loudness': loudness, 'presenter_audio_version': 1}
        return {
            "status": "GENERATED",
            "message": "Voice narration generated successfully.",
            "script": clean,
            "url": f"{public_prefix}/{filename}",
            "asset_generated": True,
            "model": model,
            "voice": voice,
            **presenter_result,
        }



class DidTalkingPresenterProvider:
    provider_id = "d-id"

    def _key(self) -> str:
        return str(os.getenv("DID_API_KEY") or "").strip()

    def _authorization(self) -> str:
        key = self._key()
        return key if key.lower().startswith("basic ") else f"Basic {key}"

    def status(self) -> ProviderStatus:
        selected = str(os.getenv("NOVA_TALKING_PRESENTER_PROVIDER") or "").strip().lower()
        if selected and selected not in {"d-id", "did", "d_id"}:
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="talking_presenter",
                status=CONFIG_REQUIRED,
                message=f"Talking presenter provider '{selected}' is not supported.",
                configured=False,
            )
        if not talking_presenter_provider_configured():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="talking_presenter",
                status=CONFIG_REQUIRED,
                message="D-ID talking presenter credential is not configured.",
                configured=False,
            )
        if not talking_presenter_provider_live_enabled():
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="talking_presenter",
                status=DISABLED,
                message="D-ID is configured but live talking-presenter generation is OFF until owner activation.",
                configured=True,
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            kind="talking_presenter",
            status=AVAILABLE,
            message="Nova Studio D-ID talking-presenter generation is available.",
            configured=True,
        )

    def _request_json(self, method: str, url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._authorization(),
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = f"D-ID API request failed with HTTP {exc.code}."
            try:
                parsed = json.loads(detail)
                provider_message = parsed.get("message") or parsed.get("error") or parsed.get("description")
                if provider_message:
                    message += f" {str(provider_message)[:600]}"
            except Exception:
                pass
            raise RuntimeError(message) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"D-ID API connection failed: {exc.reason}") from exc

    def _public_source_url(self, value: str) -> str | None:
        raw = str(value or "").strip()
        if raw.startswith(("https://", "http://")):
            return raw
        if raw.startswith("/"):
            base = str(
                os.getenv("AMICOR_PUBLIC_URL")
                or os.getenv("RENDER_EXTERNAL_URL")
                or ""
            ).strip().rstrip("/")
            if base.startswith(("https://", "http://")):
                return base + raw
        return None

    def _save_remote_video(self, url: str) -> str:
        root, public_prefix = _creative_media_root_and_prefix()
        root.mkdir(parents=True, exist_ok=True)
        filename = f"nova-presenter-{uuid.uuid4().hex}.mp4"
        target = root / filename
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                with target.open("wb") as output:
                    while chunk := resp.read(1024 * 1024):
                        output.write(chunk)
            if not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError("empty download")
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise RuntimeError("D-ID generated the presenter video but Nova could not save the MP4 asset.") from exc
        return f"{public_prefix}/{filename}"

    def generate(self, *, presenter_image_url: str, script: str, audio_url: str | None = None) -> dict[str, Any]:
        st = self.status()
        if st.status != AVAILABLE:
            return {
                "status": st.status,
                "message": st.message,
                "url": None,
                "asset_generated": False,
                "provider": self.provider_id,
            }

        source_url = self._public_source_url(presenter_image_url)
        clean_script = str(script or "").strip()
        if not source_url:
            return {
                "status": ERROR,
                "message": "Nova could not provide D-ID with a public presenter image URL.",
                "url": None,
                "asset_generated": False,
                "provider": self.provider_id,
            }
        if not clean_script:
            return {
                "status": ERROR,
                "message": "Talking presenter script is empty.",
                "url": None,
                "asset_generated": False,
                "provider": self.provider_id,
            }

        tts_provider = str(
            os.getenv("NOVA_CREATIVE_DID_TTS_PROVIDER") or "microsoft"
        ).strip() or "microsoft"
        voice_id = str(
            os.getenv("NOVA_CREATIVE_DID_VOICE_ID") or "en-US-JennyNeural"
        ).strip() or "en-US-JennyNeural"
        speech_rate = str(
            os.getenv("NOVA_CREATIVE_DID_SPEECH_RATE") or "0.92"
        ).strip() or "0.92"
        spoken_script = clean_script[:4000]
        use_ssml = tts_provider.lower() == "microsoft"
        if use_ssml:
            # Escape user text, then substitute each brand mention once. Two
            # successive replacements nested <sub> tags and broke synthesis.
            spoken_script = escape_xml(spoken_script)
            spoken_script = re.sub(
                r"\bAMICOR(?:\s+Nova)?\b",
                lambda match: '<sub alias="AM ih core' + (' Nova' if 'Nova' in match.group(0) else '') + '">' + match.group(0) + '</sub>',
                spoken_script,
            )
        provider_config: dict[str, Any] = {
            "type": tts_provider,
            "voice_id": voice_id,
            "voice_config": {"rate": speech_rate},
        }
        did_script: dict[str, Any] = {
            "type": "text", "ssml": use_ssml, "input": spoken_script,
            "provider": provider_config,
        }
        if audio_url:
            public_audio_url = self._public_source_url(audio_url)
            if not public_audio_url:
                return {"status": ERROR, "message": "Nova could not provide a public narration audio URL.",
                        "url": None, "asset_generated": False, "provider": self.provider_id}
            did_script = {"type": "audio", "audio_url": public_audio_url}
        created = self._request_json(
            "POST", "https://api.d-id.com/talks",
            payload={"source_url": source_url, "script": did_script},
        )
        talk_id = str(created.get("id") or "").strip()
        if not talk_id:
            return {
                "status": ERROR,
                "message": "D-ID did not return a talk id.",
                "url": None,
                "asset_generated": False,
                "provider": self.provider_id,
            }

        wait_seconds = int(str(os.getenv("NOVA_CREATIVE_TALKING_PRESENTER_WAIT_SECONDS") or "300"))
        poll_seconds = float(str(os.getenv("NOVA_CREATIVE_TALKING_PRESENTER_POLL_SECONDS") or "3"))
        deadline = time.monotonic() + max(15, min(wait_seconds, 600))
        last: dict[str, Any] = created

        while time.monotonic() < deadline:
            state = str(last.get("status") or "").strip().lower()
            if state == "done":
                result_url = str(last.get("result_url") or "").strip()
                if not result_url:
                    return {
                        "status": ERROR,
                        "message": "D-ID finished the talk but returned no video URL.",
                        "url": None,
                        "asset_generated": False,
                        "provider": self.provider_id,
                        "talk_id": talk_id,
                    }
                saved_url = self._save_remote_video(result_url)
                return {
                    "status": "GENERATED",
                    "message": "Talking presenter generated successfully.",
                    "url": saved_url,
                    "asset_generated": True,
                    "provider": self.provider_id,
                    "talk_id": talk_id,
                    "watermark_free": str(os.getenv("NOVA_CREATIVE_DID_WATERMARK_FREE_OUTPUT") or "").strip().lower() in {"1", "true", "yes", "on"},
                }
            if state in {"error", "failed", "rejected"}:
                return {
                    "status": ERROR,
                    "message": "D-ID could not generate the talking presenter.",
                    "url": None,
                    "asset_generated": False,
                    "provider": self.provider_id,
                    "talk_id": talk_id,
                }
            time.sleep(max(0.1, min(poll_seconds, 10.0)))
            last = self._request_json("GET", f"https://api.d-id.com/talks/{talk_id}")

        return {
            "status": ERROR,
            "message": "D-ID talking presenter timed out before completion.",
            "url": None,
            "asset_generated": False,
            "provider": self.provider_id,
            "talk_id": talk_id,
        }


def image_provider() -> ImageGenerationProvider:
    return OpenAIImageProvider()


def video_provider() -> VideoGenerationProvider:
    selected = selected_video_provider()
    if selected in {"fal", "kling", "fal_kling"}:
        from app.core.nova.creative_studio.kling import FalKlingVideoProvider
        return FalKlingVideoProvider()
    return RunwayVideoProvider()


def voice_provider() -> VoiceGenerationProvider:
    return OpenAIVoiceProvider()


def talking_presenter_provider() -> TalkingPresenterProvider:
    selected = str(os.getenv("NOVA_TALKING_PRESENTER_PROVIDER") or "d-id").strip().lower()
    if selected in {"d-id", "did", "d_id", ""}:
        return DidTalkingPresenterProvider()
    return DidTalkingPresenterProvider()


def provider_statuses() -> list[dict[str, Any]]:
    return [
        image_provider().status().as_dict(),
        video_provider().status().as_dict(),
        voice_provider().status().as_dict(),
        talking_presenter_provider().status().as_dict(),
    ]
