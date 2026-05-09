# Ecosystem Architecture

## 1. Integration Model

Amicor keeps ecosystem capabilities additive to the validated runtime by layering a dedicated ecosystem API module on top of existing core routes.

Core strategy:
- Preserve current chat/runtime foundations.
- Add integration endpoints under `/api` using `app.ecosystem`.
- Persist integration state in new `platform_*` SQLAlchemy tables.

Primary integration surfaces:
- Email: `/api/email/connect`, `/api/email/send`, `/api/email/drafts`, `/api/email/inbox`
- Calendar: `/api/calendar/connect`, `/api/calendar/events`, `/api/calendar/schedule`
- Search diagnostics: `/api/search`, `/api/search/diagnostics`
- Memory evolution: `/api/memory/index`, `/api/memory/retrieve`, `/api/memory/compress`
- Workflows: `/api/workflows`, `/api/workflows/{id}/execute`, `/api/workflows/{id}/history`

## 2. Provider Strategy

Provider execution follows this reliability pattern:
- Try primary provider with circuit-breaker checks.
- Fail over to alternate providers when needed.
- Record provider latency/fallback metadata.
- Cache successful search results with TTL for cost and latency control.

Email provider order:
- OAuth provider (Gmail/Outlook) when connected.
- SMTP fallback when OAuth is unavailable or fails.

Calendar provider order:
- OAuth provider (Google/Outlook) when connected.
- Local persisted calendar events when no OAuth provider is configured.

## 3. Memory Evolution

Memory now supports both summary and semantic retrieval tracks:
- Short-form summary track: compacted conversation summaries.
- Vector track: deterministic embedding vectors stored per text chunk.
- Prioritization: each memory chunk includes `priority_score`.
- Retrieval: cosine-similarity ranking combined with priority weighting.
- Compression: long history reduction endpoint to keep context bounded.

## 4. Workflow Lifecycle

Workflow stages:
1. Create workflow template with reusable prompt + action chain.
2. Execute workflow with input payload.
3. Run action chain (chat/search/email-draft/calendar-event actions).
4. Persist execution run with step-by-step result log.
5. Inspect run history for auditability and replay readiness.

## 5. File + Document Intelligence

Upload processing now supports:
- PDF extraction (`pypdf`)
- DOCX extraction (`python-docx`)
- XLSX extraction (`openpyxl`)
- CSV/text extraction
- Image OCR/vision extraction

Additional intelligence:
- Upload categorization (invoice/report/spreadsheet/image/etc.)
- Lightweight extractive document summary
- Existing OCR diagnostics retained

## 6. Deployment Topology

Deployment artifacts are provided for:
- Render (`render.yaml`)
- Railway (`railway.toml`)
- Fly.io (`fly.toml`)
- VPS/Docker Compose (`DEPLOYMENT_ECOSYSTEM_GUIDE.md`)

Runtime assumptions:
- FastAPI app remains the single backend entrypoint.
- PostgreSQL preferred in production, SQLite supported in dev.
- OAuth/SMTP config loaded from environment variables.

## 7. Scaling Roadmap

Short-term:
- Move cache/ratelimit state to Redis.
- Encrypt stored provider tokens at rest.
- Add background workers for workflow chains.

Mid-term:
- Dedicated provider-adapter interfaces per service.
- Queue-backed retry orchestration for integrations.
- Multi-tenant workflow quotas and execution controls.

Long-term:
- Hybrid memory index (vector DB + summary graph).
- Event-driven workflow triggers (email/calendar/search updates).
- Cross-region deployment with replicated observability pipelines.
