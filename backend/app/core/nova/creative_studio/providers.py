"""Provider-neutral Creative Studio media interfaces. No secrets in code."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import os
from pathlib import Path
import uuid
from typing import Any, Protocol

from app.ai import get_client

from app.core.nova.creative_studio.flags import (
    image_provider_configured,
    image_provider_live_enabled,
    video_provider_configured,
    voice_provider_configured,
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


class DisabledVideoProvider:
    provider_id = "video_unconfigured"

    def status(self) -> ProviderStatus:
        configured = video_provider_configured()
        return ProviderStatus(
            provider_id=self.provider_id,
            kind="video",
            status=CONFIG_REQUIRED if not configured else DISABLED,
            message=(
                "No approved video provider credentials configured."
                if not configured
                else "Video credentials present but live video generation remains DISABLED until owner activation."
            ),
            configured=configured,
        )

    def generate(self, *, brief: dict[str, Any]) -> dict[str, Any]:
        st = self.status()
        return {
            "status": st.status,
            "message": st.message,
            "brief": brief,
            "url": None,
            "asset_generated": False,
        }


class DisabledVoiceProvider:
    provider_id = "voice_unconfigured"

    def status(self) -> ProviderStatus:
        configured = voice_provider_configured()
        return ProviderStatus(
            provider_id=self.provider_id,
            kind="voice",
            status=CONFIG_REQUIRED if not configured else DISABLED,
            message=(
                "No approved voice provider credentials configured."
                if not configured
                else "Voice credentials present but live voice generation remains DISABLED until owner activation."
            ),
            configured=configured,
        )

    def generate(self, *, script: str) -> dict[str, Any]:
        st = self.status()
        return {
            "status": st.status,
            "message": st.message,
            "script": script,
            "url": None,
            "asset_generated": False,
        }


def image_provider() -> ImageGenerationProvider:
    return OpenAIImageProvider()


def video_provider() -> VideoGenerationProvider:
    return DisabledVideoProvider()


def voice_provider() -> VoiceGenerationProvider:
    return DisabledVoiceProvider()


def provider_statuses() -> list[dict[str, Any]]:
    return [
        image_provider().status().as_dict(),
        video_provider().status().as_dict(),
        voice_provider().status().as_dict(),
    ]
