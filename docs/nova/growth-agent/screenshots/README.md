# Receptionist pilot browser evidence (#527)

Sanitized Chromium captures from disposable local acceptance. **No secrets.**

| File | What it shows |
|------|----------------|
| `receptionist_before_login.png` | Growth page before sign-in |
| `receptionist_after_login.png` | Owner signed in; calendar Not connected |
| `receptionist_readiness_panel.png` | Owner readiness: missing/not connected vs empty queue vs SIMULATED Twilio |
| `receptionist_voice_simulator.png` | Voice simulator button → service-backed FAQ (SIMULATED) |
| `receptionist_chromium_evidence.json` | Machine-readable step results |
| `receptionist_staging_readiness.png` | Staging-prep Chromium: owner readiness Not connected |
| `receptionist_staging_owner_journey.json` | Staging-prep API+browser journey; requires `/api/health/readiness` HTTP 200 |
| `receptionist_staging_db_rehearsal.json` | Disposable PG backup/restore + Alembic receptionist upgrade evidence |
| `receptionist_staging_empty_db_rehearsal.json` | Empty-DB first deploy via `receptionist_staging_start.py --migrate-only` |
| `receptionist_staging_blueprint_validation.json` | Render Blueprint JSON Schema validation (no `releaseCommand`) |

These files are committed so reviewers can open them on GitHub without Cursor `/opt/cursor/artifacts` access.

**Not proof of live Google/Twilio or a Render deploy.** Live pilot requires `RECEPTIONIST_REAL_ACCOUNT_ACCEPTANCE.md`. Staging provision requires `RECEPTIONIST_STAGING_RELEASE_APPROVAL_527.md`.
