"""
OCR + Image Understanding layer.

Priority chain:
  1. OpenAI Vision API (gpt-4o-mini) — best quality, requires OPENAI_API_KEY
  2. pytesseract              — local OCR, requires Tesseract binary
  3. Metadata-only fallback  — returns image format/size info only

All paths return:
  {
    "text":        str | None,   # extracted / described text
    "description": str | None,   # natural-language image description
    "method":      str,          # "vision_api" | "tesseract" | "metadata_only"
    "confidence":  float,        # 0.0–1.0
    "word_count":  int,
    "diagnostics": dict,
  }
"""
from __future__ import annotations

import base64
import importlib
import logging
import os
import struct
import zlib # type: ignore
from io import BytesIO

logger = logging.getLogger("amicor.ocr")
OPENAI_TIMEOUT_SECONDS = 30.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _image_dims(content_type: str, data: bytes) -> tuple[int, int]:
    """Best-effort image width/height extraction without Pillow."""
    try:
        if content_type == "image/png":
            # PNG: IHDR chunk at bytes 16-24
            if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", data[16:24])
                return w, h
        elif content_type in ("image/jpeg", "image/jpg"):
            # JPEG: scan for SOF marker
            i = 2
            while i < len(data) - 8:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg_len
        elif content_type == "image/webp":
            # WEBP VP8L or VP8 header
            if len(data) >= 30 and data[8:12] == b"WEBP":
                if data[12:16] == b"VP8L":
                    bits = struct.unpack("<I", data[21:25])[0]
                    w = (bits & 0x3FFF) + 1
                    h = ((bits >> 14) & 0x3FFF) + 1
                    return w, h
    except Exception:
        pass
    return 0, 0


# ── Provider 1: OpenAI Vision ──────────────────────────────────────────────────

def _openai_vision(content_type: str, data: bytes) -> dict | None: # type: ignore
    """Call OpenAI gpt-4o-mini vision endpoint."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        openai_mod = importlib.import_module("openai")
        client = openai_mod.OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS)

        data_url = f"data:{content_type};base64,{_b64(data)}"
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=800,
            timeout=OPENAI_TIMEOUT_SECONDS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Please do two things:\n"
                                "1. Extract ALL readable text from this image (OCR). "
                                "If there is no text, say so.\n"
                                "2. Provide a concise description of what the image shows.\n\n"
                                "Format your response as:\n"
                                "TEXT:\n<extracted text or 'No readable text found'>\n\n"
                                "DESCRIPTION:\n<brief description>"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
                        },
                    ],
                }
            ],
        )
        raw = completion.choices[0].message.content or ""

        # Parse TEXT / DESCRIPTION sections
        text_part = ""
        desc_part = ""
        if "TEXT:" in raw and "DESCRIPTION:" in raw:
            text_section = raw.split("TEXT:", 1)[1].split("DESCRIPTION:", 1)[0].strip()
            desc_section = raw.split("DESCRIPTION:", 1)[1].strip()
            text_part = text_section if "no readable text" not in text_section.lower() else ""
            desc_part = desc_section
        else:
            # Fallback: treat full response as description
            desc_part = raw.strip()

        return {
            "text": text_part or None,
            "description": desc_part or None,
            "method": "vision_api",
            "confidence": 0.92,
            "word_count": len((text_part + " " + desc_part).split()),
            "diagnostics": {"model": "gpt-4o-mini", "tokens": completion.usage.total_tokens if completion.usage else 0},
        } # type: ignore
    except Exception as exc:
        logger.warning("OpenAI vision call failed: %s", exc)
        return None


# ── Provider 2: pytesseract ────────────────────────────────────────────────────

def _tesseract_ocr(content_type: str, data: bytes) -> dict | None: # type: ignore
    """Run pytesseract OCR (requires tesseract binary)."""
    try:
        pytesseract = importlib.import_module("pytesseract")
        pil_image   = importlib.import_module("PIL.Image")
        img = pil_image.open(BytesIO(data))
        raw_text = pytesseract.image_to_string(img)
        text = raw_text.strip()
        return {
            "text": text or None,
            "description": f"Image processed via Tesseract OCR. Dimensions: {img.width}×{img.height}.",
            "method": "tesseract",
            "confidence": 0.75 if text else 0.3,
            "word_count": len(text.split()) if text else 0,
            "diagnostics": {"engine": "tesseract"},
        } # type: ignore
    except ImportError:
        logger.debug("pytesseract not installed — skipping")
        return None
    except Exception as exc:
        logger.warning("Tesseract OCR failed: %s", exc)
        return None


# ── Provider 3: Metadata-only fallback ────────────────────────────────────────

def _metadata_fallback(content_type: str, data: bytes) -> dict: # type: ignore
    w, h = _image_dims(content_type, data)
    size_kb = round(len(data) / 1024, 1)
    fmt = content_type.split("/")[-1].upper()
    dims_str = f"{w}×{h}" if w and h else "unknown dimensions"
    description = f"{fmt} image ({dims_str}, {size_kb} KB). Text extraction unavailable — set OPENAI_API_KEY to enable image understanding."
    return {
        "text": None,
        "description": description,
        "method": "metadata_only",
        "confidence": 0.0,
        "word_count": 0,
        "diagnostics": {
            "format": fmt,
            "width": w,
            "height": h,
            "size_kb": size_kb,
            "reason": "no_ocr_provider_available",
        },
    } # type: ignore


# ── Public API ─────────────────────────────────────────────────────────────────

def extract(content_type: str, data: bytes) -> dict: # type: ignore
    """
    Extract text and description from image bytes.

    Args:
        content_type: MIME type, e.g. "image/png"
        data:         Raw image bytes

    Returns:
        dict with keys: text, description, method, confidence, word_count, diagnostics
    """
    result = _openai_vision(content_type, data) # type: ignore
    if result:
        return result # type: ignore

    result = _tesseract_ocr(content_type, data) # type: ignore
    if result:
        return result # type: ignore

    return _metadata_fallback(content_type, data) # type: ignore


def build_context_block(filename: str | None, ocr_result: dict) -> str: # type: ignore
    """
    Format OCR result into a context string for injection into the chat prompt.

    The returned string is designed to be appended to the user's message so
    the LLM can reason about the uploaded image.
    """
    parts = [f"[Image uploaded: {filename or 'image'}]"]

    if ocr_result.get("description"): # type: ignore
        parts.append(f"Description: {ocr_result['description']}")

    if ocr_result.get("text"): # type: ignore
        truncated = ocr_result["text"][:3000] # type: ignore
        parts.append(f"Extracted text:\n{truncated}")

    method = ocr_result.get("method", "unknown") # type: ignore
    if method == "metadata_only":
        parts.append("Note: Full image analysis requires OPENAI_API_KEY.")

    return "\n".join(parts)
