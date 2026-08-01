# Render Staging Deploy — Platform Ops Infrastructure

Use this checklist to deploy **Phase 53 infrastructure** to the staging Render service
(`https://amicor-health-isf-py.onrender.com`) without promoting to a separate production cut.

## Pre-deploy (local verification — must pass)

```powershell
cd backend
python scripts/phase53_infrastructure_completion.py
```

Expected local checks:
- Alembic clean DB upgrade → **PASS**
- `render_disk` storage upload/download/delete → **PASS**
- Platform Ops local staging endpoints → **PASS**

## Render staging configuration

1. **Persistent disk** (recommended)
   - Mount path: `/data/onboarding_docs`
   - Size: 1 GB minimum for onboarding documents

2. **Environment variables** (staging service)
   | Variable | Value |
   |----------|-------|
   | `AMICOR_ENVIRONMENT` | `staging` |
   | `PLATFORM_OPS_DOCUMENT_STORAGE` | `render_disk` |
   | `PLATFORM_OPS_DOCUMENT_STORAGE_PATH` | `/data/onboarding_docs` |
   | `APP_VERSION` | `2026.08.01-phase53-staging.1` |

3. **Release command** (already in `render.yaml`)
   ```
   alembic upgrade heads
   ```

## Deploy steps

1. Commit infrastructure changes (migrations, storage adapter, Platform Ops routes).
2. Push to the branch connected to Render auto-deploy.
3. Wait for Render build + release command to complete.
4. Verify:
   ```powershell
   curl https://amicor-health-isf-py.onrender.com/api/platform-ops/driver-onboarding/document-categories
   ```
   Expected: **HTTP 200** with JSON category list (not 404).

5. Re-run Phase 53 audit:
   ```powershell
   python scripts/phase53_infrastructure_completion.py
   ```
   Expected verdict: **GO**

## Post-deploy smoke

```powershell
$env:AMICOR_STAGING_URL = "https://amicor-health-isf-py.onrender.com"
python scripts/phase52_deployment_preparation.py
python scripts/phase53_infrastructure_completion.py
```

## Do not promote to production until

- [ ] Phase 53 verdict = **GO**
- [ ] Staging Platform Ops `document-categories` returns 200
- [ ] Alembic head = `20260731_driver_onboarding_s1` on staging Postgres
- [ ] Document upload/download verified on staging with `render_disk`
