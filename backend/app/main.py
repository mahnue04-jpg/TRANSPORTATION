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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response

from app.database import clear_user_memory, get_chat_history, get_memory_summary, get_preferences, init_db  # type: ignore
from app.models import ChatRequest, ResetRequest   # type: ignore
from app.router import route_message              # type: ignore
from app import startup as app_startup            # type: ignore
from app import image_ocr                         # type: ignore

from app.middleware import SecurityHeadersMiddleware, RequestTracingMiddleware, log_upload  # type: ignore
from app import auth as auth_module               # type: ignore
from app import observability                     # type: ignore
from app import ecosystem as ecosystem_module     # type: ignore
from app import responses as responses_module     # type: ignore
from app import validation as validation_module   # type: ignore

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
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png", "image/jpeg", "image/webp",
})


# ── CORS ─────────────────────────────────────────────────────────────────────
def _allowed_origins() -> list: # type: ignore
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()] # type: ignore
    # Secure-by-default local dev origins; override via ALLOWED_ORIGINS in deployment.
    return [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ] # type: ignore


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

    # ── Platform DB (SQLAlchemy) ──────────────────────────────────────────
    try:
        from app.db.session import init_platform_db  # type: ignore
        init_platform_db()
        logger.info("Platform database tables ready.")
    except Exception as exc:
        logger.error("Platform DB init failed: %s", exc)

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
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTracingMiddleware)

# ── Auth router ───────────────────────────────────────────────────────────────
app.include_router(auth_module.router)
app.include_router(ecosystem_module.router)

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
    if content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        diagnostics["parser"] = "openpyxl"
        try:
            openpyxl = importlib.import_module("openpyxl")
            workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
            rows_out: list[str] = []
            for sheet in workbook.worksheets[:4]:
                rows_out.append(f"[Sheet: {sheet.title}]")
                for row in sheet.iter_rows(min_row=1, max_row=40, values_only=True):
                    values = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                    if values:
                        rows_out.append(" | ".join(values[:12]))
            return "\n".join(rows_out).strip(), diagnostics, None
        except Exception as exc:
            diagnostics["warnings"].append(f"Spreadsheet parse failed: {exc}")
            return None, diagnostics, None
    if content_type in ("image/png", "image/jpeg", "image/webp"):
        diagnostics["parser"] = "image-ocr"
        ocr_result = image_ocr.extract(content_type, content) # type: ignore
        diagnostics["ocr"] = ocr_result["diagnostics"]
        diagnostics["ocr_method"] = ocr_result["method"]
        combined = image_ocr.build_context_block(filename, ocr_result) # type: ignore
        return combined, diagnostics, ocr_result # type: ignore
    diagnostics["warnings"].append(f"No extractor available for {content_type}.")
    return None, diagnostics, None


def _categorize_upload(content_type: str, filename: str | None, extracted_text: str | None) -> str:
    name = (filename or "").lower()
    text = (extracted_text or "").lower()
    if content_type.startswith("image/"):
        return "image"
    if "spreadsheet" in content_type or name.endswith(".xlsx") or name.endswith(".csv"):
        return "spreadsheet"
    if "invoice" in name or "invoice" in text:
        return "invoice"
    if "resume" in name or "curriculum" in text:
        return "resume"
    if "report" in name or "summary" in name:
        return "report"
    if "application/pdf" == content_type:
        return "pdf_document"
    if "wordprocessingml" in content_type:
        return "docx_document"
    return "text_document"


def _summarize_document_text(text: str | None, max_len: int = 420) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    # Extractive lightweight summary for predictable runtime behavior.
    sentences = [s.strip() for s in cleaned.split(".") if s.strip()]
    if not sentences:
        return cleaned[:max_len]
    summary = ". ".join(sentences[:3]).strip()
    if len(summary) > max_len:
        summary = summary[: max_len - 3].rstrip() + "..."
    elif not summary.endswith("."):
        summary += "."
    return summary


# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/")
def root() -> dict[str, str]:
    """Root endpoint — returns basic status."""
    return {"status": "ok", "version": os.environ.get("APP_VERSION", "dev")}


@app.get("/api/health")
def health():
    """Shallow liveness check — returns 200 if the process is alive.
    
    Normalized response format:
      { ok: true, data: {...}, error: null, meta: {...} }
    """
    return responses_module.normalize_success(
        data={
            "status": "ok",
            "version": os.environ.get("APP_VERSION", "dev"),
        },
        version=os.environ.get("APP_VERSION", "dev"),
    )


@app.get("/api/health/detail")
def health_detail():
    """Deep readiness check — env validation + live DB probe.
    
    Normalized response format:
      { ok: true/false, data: {...}, error: null, meta: {...} }
    """
    report   = app_startup.startup_report() # type: ignore
    db_check = app_startup.validate_database() # type: ignore
    all_ok   = report.get("ok", False) and db_check["ok"] # type: ignore
    
    status_code = 200 if all_ok else 503
    response_data = { # type: ignore
        "status": "healthy" if all_ok else "degraded",
        "db": db_check,
        "startup": report,
        "version": os.environ.get("APP_VERSION", "dev"),
    }
    
    if all_ok:
        response = responses_module.normalize_success(
            data=response_data,
            version=os.environ.get("APP_VERSION", "dev"),
        )
    else:
        response = responses_module.normalize_error(
            error_msg="System degraded: health check failed",
            latency_ms=0,
        )
        response.data = response_data  # Include diagnostic data even on error
    
    return JSONResponse(
        status_code=status_code,
        content=responses_module.as_dict(response),
    )


# ── App shell ─────────────────────────────────────────────────────────────────
@app.get("/app")
def serve_app() -> FileResponse:
    """Serve main application UI."""
    index = os.path.join(_static_dir, "index.html")
    return FileResponse(index, media_type="text/html")


# ── Chat ──────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(request: ChatRequest) -> responses_module.NormalizedResponse:
    """Process a chat message and return AI response.
    
    Normalized response format:
      { ok: true, data: {...}, error: null, meta: {...} }
    
    Data includes: reply, tool, sources, status, capability, meta
    
    Args:
        request: Chat request with validated user_id and message
        
    Returns:
        Normalized success response with chat reply
        
    Raises:
        HTTPException 422 if validation fails
    """
    logger.debug("Chat from user=%s: %r", request.user_id, request.message[:80])
    try:
        result: dict[str, Any] = route_message(request.message, user_id=request.user_id)  # type: ignore
        response_data = {
            "reply": result["response"],
            "tool": result.get("tool", "openai"),
            "sources": result.get("sources", []),
            "status": result.get("status", "success"),
            "capability": result.get("capability", {}),
            "meta": result.get("meta", {}),
        }
        return responses_module.normalize_success(
            data=response_data,
        )
    except Exception as exc:
        logger.exception("Router error for user=%s", request.user_id)
        error_response = responses_module.normalize_error(
            error_msg=f"Chat processing failed: {str(exc)}"
        )
        return JSONResponse(
            status_code=500,
            content=responses_module.as_dict(error_response),
        ) # type: ignore


@app.get("/api/history/{user_id}")
def history(user_id: str, limit: int = 50) -> dict[str, Any]:
    """Retrieve chat history and memory for user.
    
    Args:
        user_id: User identifier (validated)
        limit: Max messages to retrieve (1-100)
        
    Returns:
        Dict with user_id, messages, and memory summary
    """
    validated_user_id = validation_module.validate_user_id(user_id)
    validated_limit = max(1, min(int(limit), 100))
    
    return {
        "user_id": validated_user_id,
        "messages": get_chat_history(validated_user_id, limit=validated_limit),
        "memory": {
            "summary": get_memory_summary(validated_user_id),
            "preferences": get_preferences(validated_user_id),
        },
    }


# ── Memory reset ──────────────────────────────────────────────────────────────
@app.post("/api/reset")
def reset_chat(req: ResetRequest) -> dict[str, str]:
    """Clear user memory and reset conversation state.
    
    Args:
        req: Reset request with validated user_id
        
    Returns:
        Dict confirming reset status
        
    Raises:
        HTTPException 422 if validation fails
        HTTPException 500 if reset fails
    """
    user_id = req.user_id
    try:
        clear_user_memory(user_id)
        logger.info("Memory cleared for user=%s", user_id)
        return {"user_id": user_id, "status": "memory cleared"}
    except Exception as exc: # type: ignore
        logger.exception("Reset error for user=%s", user_id)
        raise HTTPException(status_code=500, detail="Reset failed")


# ── File upload ───────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:  # type: ignore
    """Accept a user-uploaded document for context injection.

    - Max 10 MB.
    - Allowed: text/*, application/json, application/pdf, image/png, jpeg, webp.
    - Returns extracted UTF-8 text for text-type files (first 8 000 chars).
    
    Args:
        file: Uploaded file with validated content type and size
        
    Returns:
        Dict with extracted text, diagnostics, and metadata
        
    Raises:
        HTTPException 415 if unsupported content type
        HTTPException 413 if file too large
        HTTPException 400 if parse error
    """
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    validation_module.validate_content_type(content_type, ALLOWED_UPLOAD_TYPES) # type: ignore

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    validation_module.validate_file_size(len(content), MAX_UPLOAD_BYTES, file.filename)

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
        "upload_category": _categorize_upload(content_type, file.filename, extracted_text),
        "document_summary": _summarize_document_text(extracted_text),
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

    # Record upload metrics and persist to platform_uploads
    ocr_result_ref = response_payload.get("ocr")
    log_upload(
        filename=file.filename,
        content_type=content_type,
        size_bytes=len(content),
        ocr_method=(ocr_result_ref or {}).get("method") if ocr_result_ref else None, # type: ignore
        ocr_confidence=(ocr_result_ref or {}).get("confidence") if ocr_result_ref else None, # type: ignore
        ocr_word_count=(ocr_result_ref or {}).get("word_count") if ocr_result_ref else None, # type: ignore
    )
    observability.increment("uploads.total")
    if content_type.startswith("image/"):
        observability.increment("uploads.images")

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
async def chat_stream(request: ChatRequest) -> StreamingResponse:  # type: ignore
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
def provider_diagnostics() -> responses_module.NormalizedResponse:  # type: ignore
    """Return health and circuit-breaker state for all providers.
    
    Normalized response format:
      { ok: true, data: {...}, error: null, meta: {...} }
    
    Returns:
        Normalized response with provider diagnostics
    """
    try:
        from app.providers.resilience import all_diagnostics  # type: ignore
        providers_data = all_diagnostics() # type: ignore
        return responses_module.normalize_success(
            data={
                "providers": providers_data,
                "version": os.environ.get("APP_VERSION", "dev"),
            },
            version=os.environ.get("APP_VERSION", "dev"),
        )
    except Exception as exc:
        logger.exception("Provider diagnostics error")
        return JSONResponse(
            status_code=500,
            content=responses_module.as_dict(
                responses_module.normalize_error(
                    error_msg=f"Failed to retrieve provider diagnostics: {str(exc)}"
                )
            ),
        ) # type: ignore


# ── Admin dashboard ───────────────────────────────────────────────────────────

@app.get("/api/admin/dashboard")
def admin_dashboard() -> dict[str, Any]:  # type: ignore
    """Aggregated platform status: DB health, provider states, session counters,
    upload stats, observability metrics.
    Not auth-protected in dev mode; add require_auth in production.
    
    Returns:
        Dict with comprehensive platform status
    """
    from app.providers.resilience import all_diagnostics  # type: ignore
    from app.db.session import check_db_connection        # type: ignore

    db_ok = check_db_connection()

    # Count registered users and recent uploads from platform tables
    user_count   = 0
    upload_count = 0
    recent_logs: list = [] # type: ignore
    try:
        from app.db.session import SessionLocal   # type: ignore
        from app.db.models import User, Upload, ProviderLog  # type: ignore
        db = SessionLocal()
        try:
            user_count   = db.query(User).count()
            upload_count = db.query(Upload).count()
            recent_logs  = [ # type: ignore
                {
                    "provider": r.provider_name,
                    "success":  r.success,
                    "latency_ms": r.latency_ms,
                    "error_msg":  r.error_msg,
                    "created_at": r.created_at.isoformat(),
                }
                for r in db.query(ProviderLog)
                          .order_by(ProviderLog.id.desc())
                          .limit(20)
                          .all()
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Admin dashboard DB query failed: %s", exc)

    return {
        "status": "ok",
        "database": {
            "reachable": db_ok,
        },
        "platform": {
            "registered_users": user_count,
            "total_uploads":    upload_count,
        },
        "providers": all_diagnostics(),
        "observability": observability.get_metrics(),
        "recent_provider_logs": recent_logs,
        "version": os.environ.get("APP_VERSION", "dev"),
    } # type: ignore


@app.get("/api/admin/metrics")
def admin_metrics() -> dict[str, Any]:
    """Lightweight metrics endpoint — counters, latencies, recent errors.
    
    Returns:
        Dict with observability metrics
    """
    return observability.get_metrics()


# ── Admin UI (serves static admin.html) ───────────────────────────────────────

@app.get("/admin")
def serve_admin() -> Response:
    """Serve admin dashboard UI.
    
    Returns:
        Admin HTML page or 404 error
    """
    admin_html = os.path.join(_static_dir, "admin.html")
    if os.path.isfile(admin_html):
        return FileResponse(admin_html, media_type="text/html")
    return JSONResponse({"error": "Admin UI not found"}, status_code=404)
