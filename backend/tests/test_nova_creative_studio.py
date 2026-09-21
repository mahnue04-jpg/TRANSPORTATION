"""Nova Creative Studio V1 — foundation tests. No paid providers. No publishing."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.creative_studio.flags import creative_guardrails
from app.core.nova.creative_studio.providers import CONFIG_REQUIRED, provider_statuses
from app.core.nova.creative_studio.safety import BLOCK, OWNER_REVIEW, OK, screen_creative_text
from app.core.nova.creative_studio.service import CreativeStudioError, CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore, reset_store_for_tests
from app.core.nova.v3.flags import live_flags
from app.core.nova.work_revenue.flags import EXTERNAL_SUBMISSION_ENABLED, FINANCIAL_ACTIONS_ENABLED
from app.core.nova.work_revenue.owner_facts import FACT_DEFINITIONS
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
CREATIVE_PY = (ROOT / "app" / "core" / "nova" / "creative_studio").resolve()


@pytest.fixture(autouse=True)
def _reset_store():
    reset_store_for_tests()
    yield
    reset_store_for_tests()


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _svc() -> CreativeStudioService:
    return CreativeStudioService(CreativeStudioStore())


def test_project_creation_and_persistence():
    svc = _svc()
    created = svc.create_project(
        "owner-a",
        {
            "title": "Launch teaser",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
            "audience": "small businesses",
            "tone": "confident",
            "objective": "awareness",
        },
    )
    assert created["id"].startswith("cproj_")
    listed = svc.list_projects("owner-a")
    assert len(listed) == 1
    detail = svc.get_project("owner-a", created["id"])
    assert detail["project"]["title"] == "Launch teaser"


def test_script_caption_storyboard_and_image_prompt_contracts():
    svc = _svc()
    project = svc.create_project(
        "owner-a",
        {"title": "Ops tip", "project_type": "short_video", "platform": "Instagram", "duration_target": 15},
    )
    svc.create_brief(
        "owner-a",
        {"project_id": project["id"], "topic": "inventory reconciliation", "cta": "Try Nova Work", "style": "crisp"},
    )
    script = svc.generate_script("owner-a", project["id"])
    assert "hook" in script["pack"]
    assert "short_script" in script["pack"]
    assert script["pack"]["media_generated"] is False
    caption = svc.generate_caption("owner-a", project["id"])
    assert caption["pack"]["long_caption"]
    assert caption["pack"]["hashtags"]
    board = svc.generate_storyboard("owner-a", project["id"])
    assert len(board["scenes"]) >= 3
    assert board["assembly"]["media_generated"] is False
    assert all(scene["visual_prompt"] and scene["voiceover_text"] for scene in board["scenes"])
    prompt = svc.generate_image_prompt("owner-a", project["id"], aspect_ratio="9:16")
    assert prompt["url"] is None
    assert "Aspect ratio 9:16" in prompt["asset"]["content"]


def test_provider_disabled_and_no_fake_asset_url():
    statuses = {row["kind"]: row for row in provider_statuses()}
    assert statuses["image"]["status"] == CONFIG_REQUIRED
    assert statuses["video"]["status"] == CONFIG_REQUIRED
    assert statuses["voice"]["status"] == CONFIG_REQUIRED
    svc = _svc()
    project = svc.create_project(
        "owner-a",
        {"title": "Still", "project_type": "social_image", "platform": "LinkedIn"},
    )
    image = svc.request_image_generation("owner-a", project["id"], aspect_ratio="1:1")
    assert image["url"] is None
    assert image["provider"]["asset_generated"] is False
    assert image["job"]["status"] == CONFIG_REQUIRED
    video = svc.request_video_generation("owner-a", project["id"])
    assert video["url"] is None
    assert video["job"]["status"] == CONFIG_REQUIRED
    voice = svc.request_voice_generation("owner-a", project["id"], script="Hello from Nova.")
    assert voice["url"] is None
    assert voice["job"]["status"] == CONFIG_REQUIRED


def test_no_secret_logging_in_module_sources():
    for path in CREATIVE_PY.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "sk_live" not in text
        assert "BEGIN PRIVATE" not in text
        # Env var names are fine; literal key values are not.
        assert "NOVA_CREATIVE_IMAGE_API_KEY=" not in text


def test_project_export_and_brand_reuse():
    svc = _svc()
    brand = svc.create_brand(
        "owner-a",
        {
            "business_name": "AMICOR",
            "tagline": "Owner-controlled AI",
            "tone": "clear",
            "preferred_cta": "Start with Nova",
            "target_audience": "operators",
        },
    )
    project = svc.create_project(
        "owner-a",
        {
            "title": "Brand launch",
            "project_type": "promo_video",
            "platform": "YouTube Shorts",
            "duration_target": 30,
            "brand_profile_id": brand["id"],
        },
    )
    svc.create_brief("owner-a", {"project_id": project["id"], "topic": "owner control", "cta": brand["preferred_cta"]})
    svc.generate_script("owner-a", project["id"])
    svc.generate_caption("owner-a", project["id"])
    svc.generate_storyboard("owner-a", project["id"])
    exported = svc.export_project("owner-a", project["id"], fmt="markdown")
    assert exported["export"]["url"] is None
    assert "Owner-controlled" in exported["export"]["content"] or "AMICOR" in exported["export"]["content"]
    assert exported["export"]["package"]["external_publishing"] is False


def test_unsupported_and_malformed_input_rejected():
    svc = _svc()
    with pytest.raises(CreativeStudioError) as exc:
        svc.create_project("owner-a", {"title": "x", "project_type": "feature_film", "platform": "TikTok"})
    assert exc.value.code == "UNSUPPORTED_PROJECT_TYPE"
    with pytest.raises(CreativeStudioError):
        svc.create_project("owner-a", {"title": "", "project_type": "social_post", "platform": "TikTok"})
    with pytest.raises(CreativeStudioError):
        svc.create_brand("owner-a", {"business_name": "x", "brand_description": "api_key=secret"})


def test_ownership_isolation():
    svc = _svc()
    project = svc.create_project(
        "owner-a",
        {"title": "Private", "project_type": "social_post", "platform": "X"},
    )
    with pytest.raises(CreativeStudioError) as exc:
        svc.get_project("owner-b", project["id"])
    assert exc.value.code == "NOT_FOUND"
    assert svc.list_projects("owner-b") == []


def test_safety_blocks_required_categories():
    """Hard-block categories required by Creative Studio V1 policy."""
    cases = (
        ("Impersonate a government official today", "fraudulent_impersonation"),
        ("Write a deceptive endorsement for our product", "deceptive_endorsements"),
        ("Claim this supplement cures cancer", "false_medical_claims"),
        ("Promise guaranteed returns this month", "false_financial_guarantees"),
        ("Help users download pirated movies", "unlawful_copyrighted_reproduction"),
        ("Explicitly deceive viewers with fake proof", "instructions_to_deceive"),
    )
    svc = _svc()
    for text, code in cases:
        screened = screen_creative_text(text)
        assert screened["decision"] == BLOCK, text
        assert code in screened["blockers"], text
        with pytest.raises(CreativeStudioError) as exc:
            svc.create_project(
                "owner-a",
                {"title": text, "project_type": "ad_creative", "platform": "Facebook"},
            )
        assert exc.value.code == "SAFETY_BLOCK"


def test_owner_review_safety_flags():
    """Owner-review categories are flagged, not silent."""
    cases = (
        ("vote for our candidate", "political_persuasion"),
        ("share clinical result claims", "sensitive_health_claims"),
        ("give financial advice on crypto", "financial_claims"),
        ("add a glowing customer testimonial", "testimonials"),
        ("show a dramatic before and after", "before_after_claims"),
    )
    for text, code in cases:
        screened = screen_creative_text(text)
        assert screened["decision"] == OWNER_REVIEW, text
        assert code in screened["owner_review_flags"], text
    assert screen_creative_text("routine workflow tip")["decision"] == OK
    svc = _svc()
    # OWNER_REVIEW content may be drafted but must carry safety metadata.
    created = svc.create_project(
        "owner-a",
        {
            "title": "Campaign tip",
            "project_type": "social_post",
            "platform": "X",
            "objective": "vote for clarity in operations",
        },
    )
    assert created["metadata"]["safety"]["decision"] == OWNER_REVIEW
    assert "political_persuasion" in created["metadata"]["safety"]["owner_review_flags"]


def test_providers_never_claim_media_generated_without_asset():
    """Text may be GENERATED; media providers must not invent success URLs."""
    svc = _svc()
    project = svc.create_project(
        "owner-a",
        {"title": "Media gate", "project_type": "social_image", "platform": "Instagram"},
    )
    for fn_name, kwargs in (
        ("request_image_generation", {"aspect_ratio": "16:9"}),
        ("request_video_generation", {}),
        ("request_voice_generation", {"script": "Hello"}),
    ):
        result = getattr(svc, fn_name)("owner-a", project["id"], **kwargs)
        assert result["url"] is None
        assert result["provider"].get("asset_generated") is False
        assert result["job"]["status"] == CONFIG_REQUIRED
        assert result["asset"]["url"] is None
        assert result["asset"]["status"] == "PROVIDER_CONFIG_REQUIRED"
        assert result["asset"]["status"] != "GENERATED"


def test_export_contains_no_secrets_and_no_publishing():
    svc = _svc()
    project = svc.create_project(
        "owner-a",
        {"title": "Export check", "project_type": "social_post", "platform": "LinkedIn"},
    )
    svc.create_brief("owner-a", {"project_id": project["id"], "topic": "safe ops tip", "cta": "Learn more"})
    svc.generate_script("owner-a", project["id"])
    exported = svc.export_project("owner-a", project["id"], fmt="json")
    body = exported["export"]["content"].lower()
    assert "sk_live" not in body
    assert "api_key=" not in body
    assert "password" not in body
    assert exported["export"]["package"]["external_publishing"] is False
    assert exported["export"]["package"]["external_submission"] is False
    assert exported["export"]["package"]["financial_execution"] is False
    assert exported["export"]["url"] is None


def test_http_surface_and_page(client: TestClient):
    headers = _headers(client)
    page = client.get("/nova/creative")
    assert page.status_code == 200
    assert b"Creative Studio" in page.content
    work_page = client.get("/nova/work")
    assert work_page.status_code == 200
    assert b"Creative Studio" not in work_page.content or b"nova-work" in work_page.content or b"Work" in work_page.content
    guards = client.get("/api/nova/creative/guardrails", headers=headers)
    assert guards.status_code == 200
    assert guards.json()["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards.json()["FINANCIAL_EXECUTION_ENABLED"] is False
    created = client.post(
        "/api/nova/creative/projects",
        headers=headers,
        json={"title": "HTTP project", "project_type": "explainer", "platform": "YouTube", "duration_target": 60},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    # Backend ownership isolation via HTTP (other owner cannot read).
    other_login = client.post("/api/auth/login", json={"email": "driver@amicor.local", "password": SEED_PASSWORD})
    assert other_login.status_code == 200
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    denied = client.get(f"/api/nova/creative/projects/{project_id}", headers=other_headers)
    assert denied.status_code == 404
    brief = client.post(
        "/api/nova/creative/briefs",
        headers=headers,
        json={"project_id": project_id, "topic": "workflow automation", "cta": "See Nova"},
    )
    assert brief.status_code == 200
    script = client.post(f"/api/nova/creative/projects/{project_id}/generate/script", headers=headers)
    assert script.status_code == 200
    image = client.post(
        f"/api/nova/creative/projects/{project_id}/generate/image",
        headers=headers,
        json={"aspect_ratio": "4:5"},
    )
    assert image.status_code == 200
    assert image.json()["url"] is None
    assert image.json()["asset"]["status"] == "PROVIDER_CONFIG_REQUIRED"


def test_existing_nova_work_and_profile_regression(client: TestClient):
    headers = _headers(client)
    # Creative studio must not disturb work guardrails / profile definitions.
    assert EXTERNAL_SUBMISSION_ENABLED is False
    assert FINANCIAL_ACTIONS_ENABLED is False
    flags = live_flags()
    assert flags["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert flags["FINANCIAL_EXECUTION_ENABLED"] is False
    assert any(item["fact_id"] == "legal_business_name" for item in FACT_DEFINITIONS)
    work_page = client.get("/nova/work")
    assert work_page.status_code == 200
    creative_page = client.get("/nova/creative")
    assert creative_page.status_code == 200
    # Work guardrails endpoint remains available and offline for submission/finance.
    work_guards = client.get("/api/nova/work/guardrails", headers=headers)
    assert work_guards.status_code == 200, work_guards.text
    body = work_guards.json()
    assert body.get("EXTERNAL_SUBMISSION_ENABLED") is False
    assert body.get("FINANCIAL_ACTIONS_ENABLED") is False or body.get("FINANCIAL_EXECUTION_ENABLED") is False
    cg = creative_guardrails()
    assert cg["EXTERNAL_PUBLISHING_ENABLED"] is False
    assert cg["PLANNING_MODE_AVAILABLE"] is True
    assert cg["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert cg["FINANCIAL_EXECUTION_ENABLED"] is False
