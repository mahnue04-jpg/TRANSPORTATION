"""Provider-neutral Creative Studio media interfaces. No secrets in code."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Protocol

from app.ai import get_client

from app.core.nova.creative_studio.flags import (
    image_provider_configured,
    image_provider_live_enabled,
    video_provider_configured,
    video_provider_live_enabled,
    voice_provider_configured,
    voice_provider_live_enabled,
)

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

    def generate(self, *, script: str) -> dict[str, Any]:
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
        result = get_client().images.generate(
            model=model,
            prompt=prompt,
            size=self._size(aspect_ratio),
            n=1,
        )
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
                    or "/static/generated/nova-creative"
                ).rstrip("/")
            else:
                root = Path(__file__).resolve().parents[4] / "static" / "generated" / "nova-creative"
                public_prefix = "/static/generated/nova-creative"
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
            message = detail[:800]
            try:
                parsed = json.loads(detail)
                message = str(
                    parsed.get("error")
                    or parsed.get("message")
                    or parsed.get("detail")
                    or message
                )
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
                or "/static/generated/nova-creative"
            ).rstrip("/")
        else:
            root = Path(__file__).resolve().parents[4] / "static" / "generated" / "nova-creative"
            public_prefix = "/static/generated/nova-creative"
        root.mkdir(parents=True, exist_ok=True)
        filename = f"nova-{uuid.uuid4().hex}.mp4"
        target = root / filename
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                target.write_bytes(resp.read())
        except Exception as exc:
            raise RuntimeError("Runway generated video but Nova could not save the MP4 asset.") from exc
        return f"{public_prefix}/{filename}"

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
        ratio = "720:1280" if platform in {"tiktok", "instagram", "youtube shorts"} else "1280:720"
        duration = int(str(os.getenv("NOVA_CREATIVE_VIDEO_DURATION_SECONDS") or "5"))
        if duration not in {5, 10}:
            duration = 5
        model = str(os.getenv("NOVA_CREATIVE_VIDEO_MODEL") or "gen4.5").strip()

        try:
            created = self._request_json(
                "POST",
                "https://api.dev.runwayml.com/v1/image_to_video",
                payload={
                    "model": model,
                    "promptText": prompt_text[:1000],
                    "ratio": ratio,
                    "duration": duration,
                },
            )
        except RuntimeError as exc:
            return {
                "status": ERROR,
                "message": str(exc),
                "brief": brief,
                "url": None,
                "asset_generated": False,
                "model": model,
                "duration_seconds": duration,
                "ratio": ratio,
            }
        task_id = str(created.get("id") or "").strip()
        if not task_id:
            return {
                "status": ERROR,
                "message": "Runway did not return a video task id.",
                "brief": brief,
                "url": None,
                "asset_generated": False,
            }

        deadline = time.monotonic() + int(str(os.getenv("NOVA_CREATIVE_VIDEO_WAIT_SECONDS") or "90"))
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
                    break
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
            "status": ERROR,
            "message": "Runway video generation is still processing. Try Generate AI Video again shortly.",
            "brief": brief,
            "url": None,
            "asset_generated": False,
            "task_id": task_id,
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

    def generate(self, *, script: str) -> dict[str, Any]:
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
        voice = str(os.getenv("NOVA_CREATIVE_VOICE_NAME") or "alloy").strip()
        response = get_client().audio.speech.create(
            model=model,
            voice=voice,
            input=clean[:4000],
            response_format="mp3",
        )
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
                or "/static/generated/nova-creative"
            ).rstrip("/")
        else:
            root = Path(__file__).resolve().parents[4] / "static" / "generated" / "nova-creative"
            public_prefix = "/static/generated/nova-creative"
        root.mkdir(parents=True, exist_ok=True)
        filename = f"nova-{uuid.uuid4().hex}.mp3"
        (root / filename).write_bytes(bytes(binary))
        return {
            "status": "GENERATED",
            "message": "Voice narration generated successfully.",
            "script": clean,
            "url": f"{public_prefix}/{filename}",
            "asset_generated": True,
            "model": model,
            "voice": voice,
        }


def image_provider() -> ImageGenerationProvider:
    return OpenAIImageProvider()


def video_provider() -> VideoGenerationProvider:
    return RunwayVideoProvider()


def voice_provider() -> VoiceGenerationProvider:
    return OpenAIVoiceProvider()


def provider_statuses() -> list[dict[str, Any]]:
    return [
        image_provider().status().as_dict(),
        video_provider().status().as_dict(),
        voice_provider().status().as_dict(),
    ]
