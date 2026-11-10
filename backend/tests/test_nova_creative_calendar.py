"""Focused calendar CRUD check. No provider, billing or publishing calls."""
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.calendar import router
from app.core.nova.creative_studio.db_models import NovaCreativeProject
from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
from app.core.nova.router import require_nova_access
from app.db.session import get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_content_calendar_owner_crud_and_no_publishing(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'calendar.db'}")
    ensure_nova_creative_schema(engine)
    owner = {"id": "owner-one"}
    with Session(engine) as db:
        db.add(NovaCreativeProject(
            id="calendar-project", owner_id="owner-one",
            title="Social series", project_type="short_video", platform="TikTok",
            created_at="2026-11-08T00:00:00+00:00", updated_at="2026-11-08T00:00:00+00:00",
        ))
        db.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id=owner["id"], email="owner@example.invalid",
        role="staff", organization_id="test-org",
    )

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = session

    base = "/api/nova/creative/projects/calendar-project/calendar"
    with TestClient(app) as client:
        created = client.post(base, json={
            "topic": "The next story episode",
            "content_mode": "drama",
            "channels": ["TikTok", "YouTube Shorts"],
            "scheduled_at": "2026-11-09T10:00:00-06:00",
        })
        assert created.status_code == 200, created.text
        entry = created.json()
        assert entry["status"] == "draft"
        assert entry["publishing_enabled"] is False
        assert entry["scheduled_at"] == "2026-11-09T16:00:00+00:00"
        assert client.patch(base + "/" + entry["id"], json={"status": "approved"}).status_code == 422
        approved = client.patch(base + "/" + entry["id"], json={
            "script": "An original episode opens with a mystery.",
            "status": "approved",
        })
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert client.get(base).json()["count"] == 1
        owner["id"] = "other-owner"
        assert client.get(base).status_code == 404
        assert client.patch(base + "/" + entry["id"], json={"topic": "steal"}).status_code == 404
        owner["id"] = "owner-one"
        canceled = client.post(base + "/" + entry["id"] + "/cancel")
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"
        assert client.patch(base + "/" + entry["id"], json={"status": "approved"}).status_code == 409
    engine.dispose()
