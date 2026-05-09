print("MAIN.PY LOADED")
from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os
import logging
import importlib
from io import BytesIO
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from zipfile import BadZipFile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.database import clear_user_memory, get_chat_history, get_memory_summary, get_preferences, init_db  # type: ignore
from app.models import ChatRequest, ResetRequest   # type: ignore
from app.router import route_message              # type: ignore
from app import startup as app_startup            # type: ignore
from app import image_ocr                         # type: ignore

# ── Logging ───────────────────────────────────────────────────────────────────
_log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("amicor.main")

# ── Upload constraints ────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_UPLOAD_TYPES = frozenset({
    "text/plain", "text/markdown", "text/csv",
    "application/json", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png", "image/jpeg", "image/webp",
})


# ── CORS ─────────────────────────────────────────────────────────────────────
def _allowed_origins() -> list: # type: ignore
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()] # type: ignore
    return ["*"]  # type: ignore # dev default — override via ALLOWED_ORIGINS in production


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────────────────────
    logger.info("Amicor starting up…")
    app_startup.register_shutdown_handlers()

    report = app_startup.run_startup_validation() # type: ignore
    if report["environment"]["missing_required"]:
        logger.critical(
            "Missing required env vars: %s — functionality will be degraded.",
            report["environment"]["missing_required"], # type: ignore
        )

    db_ok = app_startup.startup_recovery(max_retries=3, delay_s=1.0)
    if db_ok:
        try:
            init_db()
            logger.info("Database initialised.")
        except Exception as exc:
            logger.error("init_db() failed: %s", exc)
    else:
        logger.critical("Database unavailable after retries — chat persistence disabled.")

    logger.info("Amicor ready. version=%s", report.get("version", "dev")) # type: ignore

    yield  # ── APPLICATION RUNNING ──────────────────────────────────────────

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    logger.info("Amicor shutting down gracefully…")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Amicor AI Assistant",
    description="Production AI assistant backend.",
    version=os.environ.get("APP_VERSION", "dev"),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(), # type: ignore
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# Serve static files from backend/static/
_static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


def _chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += step
    return chunks


def _extract_upload_text(filename: str | None, content_type: str, content: bytes) -> tuple[str | None, dict[str, Any], dict | None]: # type: ignore
    diagnostics: dict[str, Any] = {
        "parser": "none",
        "warnings": [],
    }
    if content_type.startswith("text/") or content_type == "application/json":
        diagnostics["parser"] = "utf8-text"
        return content.decode("utf-8", errors="replace"), diagnostics, None
    if content_type == "application/pdf":
        pypdf = importlib.import_module("pypdf")

        diagnostics["parser"] = "pypdf"
        reader = pypdf.PdfReader(BytesIO(content))
        pages: list[str] = [str(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(filter(None, pages)).strip(), diagnostics, None
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        docx = importlib.import_module("docx")

        diagnostics["parser"] = "python-docx"
        document = docx.Document(BytesIO(content))
        paragraphs: list[str] = [str(paragraph.text) for paragraph in document.paragraphs if str(paragraph.text).strip()]
        return "\n".join(paragraphs).strip(), diagnostics, None
    if content_type in ("image/png", "image/jpeg", "image/webp"):
        diagnostics["parser"] = "image-ocr"
        ocr_result = image_ocr.extract(content_type, content) # type: ignore
        diagnostics["ocr"] = ocr_result["diagnostics"]
        diagnostics["ocr_method"] = ocr_result["method"]
        combined = image_ocr.build_context_block(filename, ocr_result)
        return combined, diagnostics, ocr_result # type: ignore
    diagnostics["warnings"].append(f"No extractor available for {content_type}.")
    return None, diagnostics, None


# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "version": os.environ.get("APP_VERSION", "dev")}


@app.get("/api/health")
def health():
    """Shallow liveness check — returns 200 if the process is alive."""
    return {"status": "ok", "version": os.environ.get("APP_VERSION", "dev")}


@app.get("/api/health/detail")
def health_detail():
    """Deep readiness check — env validation + live DB probe."""
    report   = app_startup.startup_report() # type: ignore
    db_check = app_startup.validate_database() # type: ignore
    all_ok   = report.get("ok", False) and db_check["ok"] # type: ignore
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status":  "healthy" if all_ok else "degraded",
            "db":      db_check,
            "startup": report,
            "version": os.environ.get("APP_VERSION", "dev"),
        },
    )


# ── App shell ─────────────────────────────────────────────────────────────────
@app.get("/app")
def serve_app():
    index = os.path.join(_static_dir, "index.html")
    return FileResponse(index, media_type="text/html")


# ── Chat ──────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(request: ChatRequest):  # type: ignore
    logger.debug("Chat from user=%s: %r", request.user_id, request.message[:80])
    try:
        result: dict[str, Any] = route_message(request.message, user_id=request.user_id)  # type: ignore
        return {
            "reply": result["response"],
            "tool": result.get("tool", "openai"),
            "sources": result.get("sources", []),
            "status": result.get("status", "success"),
            "capability": result.get("capability", {}),
            "meta": result.get("meta", {}),
        } # type: ignore
    except Exception as exc:
        logger.exception("Router error for user=%s", request.user_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/history/{user_id}")
def history(user_id: str, limit: int = 50) -> dict[str, Any]:
    if not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id required")
    return {
        "user_id": user_id,
        "messages": get_chat_history(user_id, limit=max(1, min(limit, 100))),
        "memory": {
            "summary": get_memory_summary(user_id),
            "preferences": get_preferences(user_id),
        },
    }


# ── Memory reset ──────────────────────────────────────────────────────────────
@app.post("/api/reset")
def reset_chat(req: ResetRequest):
    user_id = req.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    try:
        clear_user_memory(user_id)
        logger.info("Memory cleared for user=%s", user_id)
        return {"user_id": user_id, "status": "memory cleared"}
    except Exception as exc: # type: ignore
        logger.exception("Reset error for user=%s", user_id)
        raise HTTPException(status_code=500, detail="Reset failed")


# ── File upload ───────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)): # type: ignore
    """Accept a user-uploaded document for context injection.

    - Max 10 MB.
    - Allowed: text/*, application/json, application/pdf, image/png, jpeg, webp.
    - Returns extracted UTF-8 text for text-type files (first 8 000 chars).
    """
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type '{content_type}'. Allowed: {sorted(ALLOWED_UPLOAD_TYPES)}",
        )

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        extracted_text, diagnostics, ocr_result = _extract_upload_text(file.filename, content_type, content) # type: ignore
    except (BadZipFile, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse upload: {exc}")
    except Exception as exc:
        logger.exception("Upload parse error for %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Upload parsing failed: {exc}")

    truncated_text = extracted_text[:8000] if extracted_text else None
    chunks = _chunk_text(extracted_text or "")

    logger.info(
        "Upload: filename=%r type=%s size=%d bytes",
        file.filename, content_type, len(content),
    )

    response_payload: dict[str, Any] = {
        "filename":       file.filename,
        "content_type":   content_type,
        "size_bytes":     len(content),
        "extracted_text": truncated_text,
        "chunk_count":    len(chunks),
        "chunks":         chunks[:8],
        "diagnostics":    {
            **diagnostics,
            "text_length": len(extracted_text or ""),
            "truncated": bool(extracted_text and len(extracted_text) > 8000),
        },
        "status": "uploaded",
    }

    # Attach OCR-specific fields for images
    if ocr_result:
        response_payload["ocr"] = {
            "method":      ocr_result["method"],
            "confidence":  ocr_result["confidence"],
            "word_count":  ocr_result["word_count"],
            "description": ocr_result.get("description"), # type: ignore
            "has_text":    bool(ocr_result.get("text")), # type: ignore
        }

    return response_payload  # type: ignore


# ── Streaming chat ────────────────────────────────────────────────────────────

async def _stream_openai(message: str, user_id: str) -> AsyncIterator[str]:
    """Yield Server-Sent Event chunks for OpenAI streaming responses."""
    import os as _os
    from app.database import (  # type: ignore
        get_memory_summary, get_preferences, get_recent_messages, # type: ignore
        save_message, save_memory_summary,
    )
    from app.router import _memory_context, _extract_preferences, _summarize_history  # type: ignore

    openai_mod = importlib.import_module("openai")
    api_key = _os.getenv("OPENAI_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'content': 'OpenAI not configured.'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    client = openai_mod.OpenAI(api_key=api_key)
    history = _memory_context(user_id) + get_recent_messages(user_id, limit=10) # type: ignore
    history.append({"role": "user", "content": message}) # type: ignore

    # Save user message before streaming
    save_message(user_id, "user", message)
    prefs = _extract_preferences(message) # type: ignore
    from app.database import save_preference  # type: ignore
    for k, v in prefs.items(): # type: ignore
        save_preference(user_id, k, v) # type: ignore

    full_response = []
    try:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            stream=True,
            max_tokens=1024,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                token = delta.content
                full_response.append(token) # type: ignore
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                await asyncio.sleep(0)  # yield to event loop
    except Exception as exc:
        logger.exception("Streaming error for user=%s", user_id)
        yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    # Save completed response and update summary
    if full_response:
        assembled = "".join(full_response) # type: ignore
        save_message(user_id, "assistant", assembled)
        recent = get_recent_messages(user_id, limit=12) # type: ignore
        summary = _summarize_history(recent)
        if summary:
            save_memory_summary(user_id, summary)

    yield "data: [DONE]\n\n"


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):  # type: ignore
    """
    Streaming variant of /api/chat.
    Returns text/event-stream with SSE chunks:
      data: {"type": "token", "content": "..."}\n\n
      data: [DONE]\n\n
    Falls back to non-streaming for tool calls (weather, search, etc.)
    """
    lower = request.message.lower()
    from app.router import CAPABILITIES  # type: ignore

    # Check if a tool capability matches — if so, use standard route and emit as single event
    for name, cap in CAPABILITIES.items(): # type: ignore
        if any(t in lower for t in cap["triggers"]): # type: ignore
            try:
                result = route_message(request.message, user_id=request.user_id) # type: ignore
                payload = json.dumps({
                    "type":       "complete",
                    "reply":      result["response"],
                    "tool":       result.get("tool", name), # type: ignore
                    "sources":    result.get("sources", []), # type: ignore
                    "status":     result.get("status", "success"), # type: ignore
                    "capability": result.get("capability", {}), # type: ignore
                    "meta":       result.get("meta", {}), # type: ignore
                })
                async def _tool_stream():  # type: ignore
                    yield f"data: {payload}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_tool_stream(), media_type="text/event-stream")
            except Exception as exc:
                logger.exception("Tool stream error for user=%s", request.user_id)
                raise HTTPException(status_code=500, detail=str(exc))

    # OpenAI streaming
    return StreamingResponse(
        _stream_openai(request.message, request.user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Provider resilience diagnostics ──────────────────────────────────────────

@app.get("/api/diagnostics/providers")
def provider_diagnostics():
    """Return health and circuit-breaker state for all providers."""
    from app.providers.resilience import all_diagnostics  # type: ignore
    return {
        "providers": all_diagnostics(),
        "version": os.environ.get("APP_VERSION", "dev"),
    }
