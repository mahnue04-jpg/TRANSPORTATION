print("MAIN.PY LOADED")
from dotenv import load_dotenv
load_dotenv()

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.database import get_connection, init_db  # type: ignore
from app.models import ChatRequest                 # type: ignore
from app.router import route_message              # type: ignore
from app import startup as app_startup            # type: ignore

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


# ── Pydantic models ───────────────────────────────────────────────────────────
class ResetRequest(BaseModel):
    user_id: str


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
        result = route_message(request.message, user_id=request.user_id)  # type: ignore
        return {"reply": result["response"], "tool": result.get("tool", "openai")} # type: ignore
    except Exception as exc:
        logger.exception("Router error for user=%s", request.user_id)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Memory reset ──────────────────────────────────────────────────────────────
@app.post("/api/reset")
def reset_chat(req: ResetRequest):
    user_id = req.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
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

    extracted_text = None
    if content_type.startswith("text/") or content_type == "application/json":
        try:
            extracted_text = content.decode("utf-8", errors="replace")[:8000]
        except Exception:
            extracted_text = None

    logger.info(
        "Upload: filename=%r type=%s size=%d bytes",
        file.filename, content_type, len(content),
    )
    return {
        "filename":       file.filename,
        "content_type":   content_type,
        "size_bytes":     len(content),
        "extracted_text": extracted_text,
        "status":         "uploaded",
    } # type: ignore
