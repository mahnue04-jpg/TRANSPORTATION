"""Studio campaign → public consented inquiry → owner CRM, with isolation gates."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import UserContext
from app.core.nova.creative_studio.db_models import NovaCreativeProject
from app.core.nova.growth_agent.campaigns import CampaignService
from app.core.nova.growth_agent.models import GROWTH_AGENT_TABLES, GaLeadEvent
from app.core.nova.growth_agent.router import router, _svc
from app.core.nova.growth_agent.service import GrowthAgentService
from app.core.nova.growth_agent.tenant import require_growth_owner
from app.db.session import Base


@pytest.fixture
def journey(monkeypatch):
    for name in ("NOVA_GROWTH_AGENT_ENABLED", "NOVA_GROWTH_AGENT_WIDGET_ENABLED", "NOVA_GROWTH_AGENT_CAMPAIGNS_ENABLED"):
        monkeypatch.setenv(name, "true")
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[*GROWTH_AGENT_TABLES, NovaCreativeProject.__table__])
    db = sessionmaker(bind=engine)()
    svc = GrowthAgentService(db)
    svc.upsert_profile("org-a", "owner-a", {
        "business_name": "Synthetic Campaign Business", "website": "https://testserver",
        "timezone": "America/Chicago", "operating_hours": {"mon_fri": "09:00-17:00"},
        "services": [{"code": "consult", "name": "Consultation", "duration_minutes": 30}],
        "faqs": [{"id": "hours", "question": "Hours?", "keywords": ["hours"], "answer": "Weekdays 9–5."}],
        "contact_email": "owner@example.invalid", "handoff_phone": "+15555550123",
        "escalation_settings": {"handoff_on_unknown": True},
    }, activate=True)
    for pid, owner in [("studio-a", "owner-a"), ("studio-b", "owner-b")]:
        db.add(NovaCreativeProject(id=pid, owner_id=owner, title="Synthetic commercial", project_type="promo_video",
                                  created_at="2026-11-14", updated_at="2026-11-14"))
    db.commit()
    widget = svc.create_widget_installation("org-a", domain="testserver")
    app = FastAPI()
    app.include_router(router)
    user = UserContext(user_id="owner-a", email="owner@example.invalid", role="admin", organization_id="org-a")
    app.dependency_overrides[require_growth_owner] = lambda: user
    app.dependency_overrides[_svc] = lambda: svc
    client = TestClient(app)
    payload = {"studio_project_id": "studio-a", "widget_token": widget["token"],
               "title": "<script>campaign</script>", "description": "Ask about our spreadsheet service."}
    yield client, svc, payload, app
    db.close()
    engine.dispose()


def create(client, payload):
    response = client.post("/api/nova/growth-agent/campaigns", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def activate(client, campaign):
    response = client.patch(f'/api/nova/growth-agent/campaigns/{campaign["id"]}',
                            json={"active": True, "content_approved": True})
    assert response.status_code == 200, response.text


def test_studio_campaign_to_consented_crm(journey):
    client, svc, payload, app = journey
    projects = client.get("/api/nova/growth-agent/campaign-projects").json()["projects"]
    assert [p["id"] for p in projects] == ["studio-a"]
    campaign = create(client, payload)
    assert campaign["status"] == "draft"
    assert client.get(campaign["inquiry_path"]).status_code == 404
    activate(client, campaign)
    landing = client.get(campaign["inquiry_path"])
    assert landing.status_code == 200
    assert "&lt;script&gt;campaign&lt;/script&gt;" in landing.text
    assert '<script>campaign</script>' not in landing.text
    assert 'frame-ancestors' in landing.headers['content-security-policy']
    assert "owner-a" not in landing.text
    chat = {"token": payload["widget_token"], "campaign_id": campaign["id"], "message": "Hours?"}
    anonymous = client.post("/api/nova/growth-agent/widget/chat", headers={"Origin": "http://testserver"}, json=chat)
    assert anonymous.status_code == 200, anonymous.text
    assert not svc.list_leads("org-a")
    chat.update(conversation_id=anonymous.json()["conversation_id"], visitor_email="synthetic@example.invalid",
                visitor_name="Synthetic visitor", consent_transactional=True)
    for _ in range(2):
        response = client.post("/api/nova/growth-agent/widget/chat", headers={"Origin": "http://testserver"}, json=chat)
        assert response.status_code == 200, response.text
        assert response.json()["grounded"]
    lead = svc.list_leads("org-a")[0]
    assert lead["campaign_sources"] == [{"campaign_id": campaign["id"], "studio_project_id": "studio-a"}]
    assert svc.get_conversation("org-a", anonymous.json()["conversation_id"])["contact_id"] == lead["id"]
    assert svc.db.query(GaLeadEvent).filter_by(event_type="campaign.inquiry").count() == 1
    assert not svc.list_leads("org-b")
    from app.core.nova.growth_agent.flags import live_flags
    assert all(not v for k, v in live_flags().items() if k.startswith("REAL_"))


def test_campaign_review_pause_and_kill_switch(journey):
    client, svc, payload, _ = journey
    c = create(client, payload)
    path = f'/api/nova/growth-agent/campaigns/{c["id"]}'
    assert client.patch(path, json={"active": True}).status_code == 400
    activate(client, c)
    client.patch(path, json={"active": False})
    assert client.get(c["inquiry_path"]).status_code == 404
    activate(client, c)
    svc.set_agent_state("org-a", disabled=True)
    assert client.get(c["inquiry_path"]).status_code == 404


def test_campaign_owner_tenant_and_origin_boundaries(journey):
    client, svc, payload, app = journey
    assert client.post("/api/nova/growth-agent/campaigns", json={**payload, "studio_project_id": "studio-b"}).status_code == 404
    c = create(client, payload)
    activate(client, c)
    assert client.get(c["inquiry_path"], headers={"Host": "evil.example"}).status_code == 403
    other = UserContext(user_id="owner-b", email="b@example.invalid", role="admin", organization_id="org-b")
    app.dependency_overrides[require_growth_owner] = lambda: other
    assert client.get("/api/nova/growth-agent/campaigns").json()["campaigns"] == []
    assert client.patch(f'/api/nova/growth-agent/campaigns/{c["id"]}', json={"active": False}).status_code == 404
    assert client.post("/api/nova/growth-agent/campaigns", json=payload).status_code == 404


def test_campaign_flags_rotation_and_consent(journey, monkeypatch):
    client, svc, payload, _ = journey
    c = create(client, payload)
    activate(client, c)
    body = {"token": payload["widget_token"], "campaign_id": c["id"], "message": "Hours?", "visitor_email": "no-consent@example.invalid"}
    assert client.post("/api/nova/growth-agent/widget/chat", headers={"Origin": "http://testserver"}, json=body).status_code == 403
    assert not svc.list_leads("org-a")
    monkeypatch.setenv("NOVA_GROWTH_AGENT_CAMPAIGNS_ENABLED", "false")
    assert client.get(c["inquiry_path"]).status_code == 404
    monkeypatch.setenv("NOVA_GROWTH_AGENT_CAMPAIGNS_ENABLED", "true")
    from app.core.nova.growth_agent.models import GaWidgetInstallation
    svc.db.query(GaWidgetInstallation).filter_by(domain="testserver").update({"token_hash": "rotated"})
    svc.db.commit()
    assert client.get(c["inquiry_path"]).status_code == 404


def test_campaign_cannot_use_another_installation(journey):
    client, svc, payload, _ = journey
    c = create(client, payload)
    activate(client, c)
    widget = svc.create_widget_installation("org-a", domain="different.example")
    response = client.post("/api/nova/growth-agent/widget/chat", headers={"Origin": "https://different.example"},
                           json={"token": widget["token"], "campaign_id": c["id"], "message": "Hello"})
    assert response.status_code == 404


def test_campaign_migration_production_lock(monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    path = Path(__file__).parents[1] / "migrations/versions/20261114_nova_ga_campaigns.py"
    spec = importlib.util.spec_from_file_location("campaign_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            monkeypatch.setenv("APP_ENV", "production")
            migration.upgrade()
            assert "nova_ga_campaigns" not in inspect(conn).get_table_names()
            monkeypatch.setenv("APP_ENV", "test")
            migration.upgrade()
            assert "nova_ga_campaigns" in inspect(conn).get_table_names()
            migration.downgrade()
            assert "nova_ga_campaigns" not in inspect(conn).get_table_names()
    engine.dispose()
