import base64
import os
import re
from typing import Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from pydantic import BaseModel, Field

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

router = APIRouter(
    prefix="/api/voice",
    tags=["voice"],
    dependencies=[Depends(get_current_user)],
)

OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "nova")
OPENAI_TTS_SPEED = float(os.getenv("OPENAI_TTS_SPEED", "0.97"))
OPENAI_TTS_VOICE_FALLBACKS = [
    v.strip() for v in os.getenv("OPENAI_TTS_VOICE_FALLBACKS", "nova,shimmer,alloy").split(",") if v.strip()
]
OPENAI_TTS_INSTRUCTIONS = os.getenv(
    "OPENAI_TTS_INSTRUCTIONS",
    "Speak naturally and warmly, like a knowledgeable friend having a real conversation. "
    "Use a relaxed, expressive tone with gentle variation in pitch and pace. "
    "Pause briefly after commas and longer after periods. "
    "Never sound robotic, monotone, or as if reading from a list.",
)
OPENAI_TTS_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TTS_TIMEOUT_SECONDS", "15"))

ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.45"))
ELEVENLABS_SIMILARITY_BOOST = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.8"))
ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.3"))
ELEVENLABS_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").strip().lower() not in {"0", "false", "no"}

AZURE_SPEECH_VOICE = os.getenv("AZURE_SPEECH_VOICE", "en-US-JennyNeural")
AZURE_SPEECH_RATE = os.getenv("AZURE_SPEECH_RATE", "-4%")
AZURE_SPEECH_PITCH = os.getenv("AZURE_SPEECH_PITCH", "+0st")
VOICE_ENABLE_NATURAL_PACING = os.getenv("VOICE_ENABLE_NATURAL_PACING", "true").strip().lower() not in {"0", "false", "no"}

INTERNAL_SPEECH_PATTERNS = [
    r"\bprovider_error\b",
    r"\bmeta\.intent\b",
    r"\bsports_live_data\b",
    r"\bshort_term_memory\b",
    r"\borchestr(?:ation|ator)\b",
    r"\brouting labels?\b",
]

ABBREVIATIONS = {
    "e.g.": "for example",
    "i.e.": "that is",
    "vs.": "versus",
    "ETA": "estimated time of arrival",
    "ASAP": "as soon as possible",
    "API": "A P I",
    "URL": "link",
}

TECHNICAL_TO_CONVERSATIONAL = {
    "provider failed": "that source is unavailable right now",
    "degraded": "temporarily limited",
    "partial": "partially available",
    "circuit open": "temporarily unavailable",
    "latency": "response delay",
    "orchestration": "coordination",
    "pipeline": "flow",
}


class VoiceSpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    mode: str = Field(default="Warm Conversational", max_length=64)
    preferred_provider: Optional[str] = Field(default=None, max_length=64)


class VoiceSpeakResponse(BaseModel):
    provider: str
    mime_type: str
    audio_b64: str


class VoiceProvidersResponse(BaseModel):
    primary: str
    fallback: str
    secondary: str
    browser_fallback_only: bool
    available: dict # type: ignore


class SynthesisError(Exception):
    pass


def _sanitize_for_voice(text: str) -> str:
    out = str(text or "")
    out = re.sub(r"```[\s\S]*?```", " ", out)
    out = re.sub(r"`[^`]*`", " ", out)
    out = re.sub(r"<[^>]+>", " ", out)
    out = re.sub(r"https?://\S+", " ", out)
    out = re.sub(r"\[[^\]]+\]\([^\)]+\)", " ", out)
    out = re.sub(r"[_*#~>|]+", " ", out)
    out = re.sub(r"\b(?:meta|provider|route|routing|intent)\.[a-z_]+\b", " ", out, flags=re.IGNORECASE)
    for pattern in INTERNAL_SPEECH_PATTERNS:
        out = re.sub(pattern, " ", out, flags=re.IGNORECASE)
    for k, v in ABBREVIATIONS.items():
        out = out.replace(k, v)
    for k, v in TECHNICAL_TO_CONVERSATIONAL.items():
        out = re.sub(re.escape(k), v, out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r"\s+([,.;!?])", r"\1", out)
    if VOICE_ENABLE_NATURAL_PACING:
        # Light pacing normalization improves conversational cadence without changing meaning.
        out = re.sub(r";", ". ", out)
        out = re.sub(r"([.!?])(\S)", r"\1 \2", out)
        out = re.sub(r"\(([^)]{1,60})\)", r", \1,", out)
        out = re.sub(r"\b(can not)\b", "cannot", out, flags=re.IGNORECASE)
        out = re.sub(r"\b(do not)\b", "don't", out, flags=re.IGNORECASE)
        out = re.sub(r"\b(does not)\b", "doesn't", out, flags=re.IGNORECASE)
        out = re.sub(r"\b(will not)\b", "won't", out, flags=re.IGNORECASE)
        out = re.sub(r"\b(I am)\b", "I'm", out)
        # Convert bullet-like separators into short spoken pauses.
        out = re.sub(r"\s[-*]\s", ", ", out)
        # Avoid long monotone runs by nudging pauses every ~22 words when needed.
        words = out.split(" ")
        if len(words) > 26:
            chunks = [" ".join(words[i:i + 22]).strip() for i in range(0, len(words), 22)]
            out = ". ".join([c.rstrip(".,; ") for c in chunks if c])
        out = re.sub(r"\s+", " ", out).strip()
    if not out:
        out = "I have a quick update for you."
    return out


def _openai_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and OpenAI is not None


def _elevenlabs_available() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY")) and bool(ELEVENLABS_VOICE_ID)


def _azure_available() -> bool:
    return bool(os.getenv("AZURE_SPEECH_KEY")) and bool(os.getenv("AZURE_SPEECH_REGION"))


def _synthesize_openai(text: str) -> Tuple[bytes, str]:
    if not _openai_available():
        raise SynthesisError("openai unavailable")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=OPENAI_TTS_TIMEOUT_SECONDS)  # type: ignore

    voices_to_try = [OPENAI_TTS_VOICE] + [v for v in OPENAI_TTS_VOICE_FALLBACKS if v != OPENAI_TTS_VOICE]
    for voice in voices_to_try:
        try:
            # OpenAI audio API can return either bytes-like response or an object with read()/stream_to_file.
            create_kwargs: dict = dict( # type: ignore
                model=OPENAI_TTS_MODEL,
                voice=voice,
                input=text,
                response_format="mp3",
                speed=OPENAI_TTS_SPEED,
            )
            # gpt-4o-mini-tts / gpt-4o-tts support a free-text instructions field
            # that dramatically improves naturalness; ignore for tts-1/tts-1-hd.
            if OPENAI_TTS_MODEL.startswith("gpt-4o") and OPENAI_TTS_INSTRUCTIONS:
                create_kwargs["instructions"] = OPENAI_TTS_INSTRUCTIONS
            resp = client.audio.speech.create(**create_kwargs)  # type: ignore
            if isinstance(resp, bytes):
                return resp, "audio/mpeg"
            if hasattr(resp, "read"):
                data = resp.read()
                if data:
                    return data, "audio/mpeg"
            if hasattr(resp, "content") and resp.content:
                return resp.content, "audio/mpeg"
        except Exception:
            continue
    raise SynthesisError("openai returned empty audio")


def _synthesize_elevenlabs(text: str) -> Tuple[bytes, str]:
    if not _elevenlabs_available():
        raise SynthesisError("elevenlabs unavailable")
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id = ELEVENLABS_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    payload = { # type: ignore
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": ELEVENLABS_STABILITY,
            "similarity_boost": ELEVENLABS_SIMILARITY_BOOST,
            "style": ELEVENLABS_STYLE,
            "use_speaker_boost": ELEVENLABS_SPEAKER_BOOST,
        },
    }
    r = requests.post(
        url,
        json=payload, # type: ignore
        headers={"xi-api-key": api_key, "Accept": "audio/mpeg"},
        timeout=OPENAI_TTS_TIMEOUT_SECONDS,
    )
    if r.status_code >= 400 or not r.content:
        raise SynthesisError("elevenlabs synthesis failed")
    return r.content, "audio/mpeg"


def _synthesize_azure(text: str) -> Tuple[bytes, str]:
    if not _azure_available():
        raise SynthesisError("azure unavailable")
    key = os.getenv("AZURE_SPEECH_KEY", "")
    region = os.getenv("AZURE_SPEECH_REGION", "")
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    ssml = (
        "<speak version='1.0' xml:lang='en-US'>"
        f"<voice xml:lang='en-US' name='{AZURE_SPEECH_VOICE}'>"
        f"<prosody rate='{AZURE_SPEECH_RATE}' pitch='{AZURE_SPEECH_PITCH}'>"
        f"{text}"
        "</prosody></voice></speak>"
    )
    r = requests.post(
        url,
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "AmicorVoice/1.0",
        },
        timeout=OPENAI_TTS_TIMEOUT_SECONDS,
    )
    if r.status_code >= 400 or not r.content:
        raise SynthesisError("azure synthesis failed")
    return r.content, "audio/mpeg"


def _provider_chain(preferred_provider: Optional[str]) -> list[str]:
    preferred = (preferred_provider or "").strip().lower()
    default_chain = ["openai_realtime_voice", "elevenlabs_conversational", "azure_neural_voice"]
    if preferred and preferred in default_chain:
        return [preferred] + [p for p in default_chain if p != preferred]
    return default_chain


@router.get("/providers", response_model=VoiceProvidersResponse)
def voice_providers() -> VoiceProvidersResponse:
    available = {
        "openai_realtime_voice": _openai_available(),
        "elevenlabs_conversational": _elevenlabs_available(),
        "azure_neural_voice": _azure_available(),
        "browser_native": True,
    }
    return VoiceProvidersResponse(
        primary="openai_realtime_voice",
        fallback="elevenlabs_conversational",
        secondary="azure_neural_voice",
        browser_fallback_only=True,
        available=available,
    )


@router.post("/speak", response_model=VoiceSpeakResponse)
def voice_speak(request: VoiceSpeakRequest) -> VoiceSpeakResponse:
    text = _sanitize_for_voice(request.text)
    chain = _provider_chain(request.preferred_provider)

    for provider in chain:
        try:
            if provider == "openai_realtime_voice":
                data, mime = _synthesize_openai(text)
            elif provider == "elevenlabs_conversational":
                data, mime = _synthesize_elevenlabs(text)
            elif provider == "azure_neural_voice":
                data, mime = _synthesize_azure(text)
            else:
                continue
            return VoiceSpeakResponse(provider=provider, mime_type=mime, audio_b64=base64.b64encode(data).decode("ascii"))
        except Exception:
            continue

    raise HTTPException(
        status_code=503,
        detail="No conversational voice provider is currently available.",
    )
