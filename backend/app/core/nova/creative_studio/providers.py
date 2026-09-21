"""Provider-neutral Creative Studio media interfaces. No secrets in code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.nova.creative_studio.flags import (
    image_provider_configured,
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


class DisabledImageProvider:
    provider_id = "image_unconfigured"

    def status(self) -> ProviderStatus:
        configured = image_provider_configured()
        if not configured:
            return ProviderStatus(
                provider_id=self.provider_id,
                kind="image",
                status=CONFIG_REQUIRED,
                message="No approved image provider credentials configured. Prompt/spec only.",
                configured=False,
            )
        # Credentials may exist but live generation is not activated in V1 without owner enable.
        return ProviderStatus(
            provider_id=self.provider_id,
            kind="image",
            status=DISABLED,
            message="Image credentials present but live image generation remains DISABLED until owner activation.",
            configured=True,
        )

    def generate(self, *, prompt: str, aspect_ratio: str) -> dict[str, Any]:
        st = self.status()
        return {
            "status": st.status,
            "message": st.message,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "url": None,
            "asset_generated": False,
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
    return DisabledImageProvider()


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
