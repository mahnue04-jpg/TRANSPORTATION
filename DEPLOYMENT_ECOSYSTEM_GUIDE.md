# Deployment Ecosystem Guide

## Production Environment Checklist

- Set `OPENAI_API_KEY`, `SECRET_KEY`, and `DATABASE_URL`.
- Set OAuth client secrets for Gmail/Outlook if email/calendar integrations are enabled.
- Set `ALLOWED_ORIGINS` to production domains.
- Run migrations: `cd backend && alembic upgrade head`.

## Railway

- Import repository.
- Ensure `railway.toml` is detected.
- Add env vars from `.env.template`.
- Verify `/api/health` after deploy.

## Render

- Create web service using `render.yaml`.
- Set root directory to `backend` and Python environment.
- Configure managed PostgreSQL and pass `DATABASE_URL`.

## Fly.io

- Set app name in `fly.toml`.
- Build image and deploy with `fly deploy`.
- Set secrets with `fly secrets set`.

## VPS (Docker Compose)

- Use `docker-compose.prod.yml` and update `.env` secrets.
- Run: `docker compose -f docker-compose.prod.yml up -d --build`.
- Confirm API and nginx health endpoints.

## Post-deploy Validation

- `npm run test:production`
- `npm run test:ecosystem`
- `npm run test:integrations`
- `npm run benchmark:providers`
