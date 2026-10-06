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
from app.core.nova.creative_studio.store import CreativeStudioStore, DbCreativeStudioStore, reset_store_for_tests
from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
from app.core.nova.v3.flags import live_flags
from app.core.nova.work_revenue.flags import EXTERNAL_SUBMISSION_ENABLED, FINANCIAL_ACTIONS_ENABLED
from app.core.nova.work_revenue.owner_facts import FACT_DEFINITIONS
from app.db.session import SessionLocal, engine
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
    ensure_nova_creative_schema(engine)
    return TestClient(app)


def _headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _svc() -> CreativeStudioService:
    return CreativeStudioService(CreativeStudioStore())


def _db_svc() -> tuple[CreativeStudioService, object]:
    db = SessionLocal()
    return CreativeStudioService(DbCreativeStudioStore(db)), db


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
    svc.generate_storyboard("owner-a", project["id"])
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
    svc.generate_storyboard("owner-a", project["id"])
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


def test_generation_quality_amicor_tiktok_contract():
    """AMICOR example: natural copy, no topic paste, useful hashtags, brand casing."""
    from app.core.nova.creative_studio.generation import assemble_short_video, generate_content_pack

    topic = "How AMICOR Nova helps small business owners save time and get work done with AI"
    audience = "small business owners"
    tone = "professional and friendly"
    cta = "Learn more about AMICOR Nova"
    pack = generate_content_pack(
        topic=topic,
        audience=audience,
        objective="awareness",
        tone=tone,
        platform="TikTok",
        cta=cta,
        duration_target=30,
        brand_name="AMICOR",
    )
    hook = pack["hook"]
    assert "What if How" not in hook
    assert topic not in hook
    assert topic not in pack["short_script"]
    assert topic not in pack["long_caption"]
    assert topic not in pack["voiceover_script"]
    assert "Point:" not in pack["short_script"]
    assert "Proof angle:" not in pack["short_script"]
    assert "Hook:" not in pack["short_script"]
    assert "AMICOR" in pack["title"]
    assert "AI" in pack["title"]
    assert "Amicor Nova Helps" not in pack["title"]
    assert " With Ai" not in pack["title"]
    weak = {"#how", "#helps", "#small", "#get", "#done", "#with", "#and"}
    tags_l = {t.lower() for t in pack["hashtags"]}
    assert not (tags_l & weak)
    assert any("amicor" in t.lower() for t in pack["hashtags"])
    assert any("ai" in t.lower() or "business" in t.lower() for t in pack["hashtags"])
    assert pack["subtitle_caption_text"] == pack["voiceover_script"]
    words = len(pack["voiceover_script"].split())
    assert 12 <= words <= 90
    assert pack["media_generated"] is False

    board = assemble_short_video(
        topic=topic,
        audience=audience,
        platform="TikTok",
        duration_target=30,
        style="Modern, professional, energetic",
        tone=tone,
        cta=cta,
        brand_name="AMICOR",
    )
    assert len(board["scenes"]) >= 3
    topic_hits = sum(1 for s in board["scenes"] if topic in s["description"] or topic in s["voiceover_text"])
    assert topic_hits == 0
    assert all(s["subtitle_text"] == s["voiceover_text"] for s in board["scenes"])
    assert board["media_generated"] is False
    assert board["video_provider_status"] == CONFIG_REQUIRED

    # Service path still wires through.
    svc = _svc()
    project = svc.create_project(
        "owner-a",
        {
            "title": "AMICOR Creative Test",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
            "audience": audience,
            "tone": tone,
        },
    )
    svc.create_brief(
        "owner-a",
        {
            "project_id": project["id"],
            "topic": topic,
            "cta": cta,
            "style": "Modern, professional, energetic",
            "audience": audience,
            "tone": tone,
        },
    )
    script = svc.generate_script("owner-a", project["id"])
    assert "What if How" not in script["pack"]["hook"]
    caption = svc.generate_caption("owner-a", project["id"])
    assert topic not in caption["pack"]["long_caption"]
    story = svc.generate_storyboard("owner-a", project["id"])
    assert all(topic not in s["voiceover_text"] for s in story["scenes"])


def test_linkedin_copy_is_more_professional_than_tiktok():
    from app.core.nova.creative_studio.generation import generate_content_pack

    topic = "How AMICOR Nova helps small business owners save time and get work done with AI"
    tiktok = generate_content_pack(
        topic=topic,
        audience="small business owners",
        objective="awareness",
        tone="professional and friendly",
        platform="TikTok",
        cta="Learn more about AMICOR Nova",
        duration_target=30,
    )
    linkedin = generate_content_pack(
        topic=topic,
        audience="small business owners",
        objective="awareness",
        tone="professional and friendly",
        platform="LinkedIn",
        cta="Learn more about AMICOR Nova",
        duration_target=30,
    )
    assert tiktok["hook"].startswith("What if")
    assert not linkedin["hook"].startswith("What if")
    assert "AMICOR" in linkedin["hook"] or "AMICOR" in linkedin["title"]


def test_create_project_empty_title_rejected_by_backend():
    svc = _svc()
    with pytest.raises(CreativeStudioError) as exc:
        svc.create_project("owner-a", {"title": "   ", "project_type": "social_post", "platform": "TikTok"})
    assert exc.value.code == "INVALID_INPUT"


def test_create_project_ux_static_contract(client: TestClient):
    """Native HTML required must not block the JS submit handler before banners run."""
    page = client.get("/nova/creative")
    assert page.status_code == 200
    html = page.content.decode("utf-8")
    assert 'id="project-form"' in html
    assert "novalidate" in html
    assert 'id="project-title"' in html
    assert 'id="project-create-btn"' in html
    # Title must not use native required (that blocked the banner path).
    assert 'id="project-title" required' not in html
    assert 'id="project-title" name="title" required' not in html
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert "Project title is required." in js
    assert 'showBanner("Project created"' in js
    assert "createBtn.disabled = true" in js
    assert "createBtn.disabled = false" in js
    assert "await refreshProjects()" in js
    assert "Session expired. Sign in again. (401)" in js
    assert "Access denied. (403)" in js
    assert "Validation failed. (422)" in js or "(422)" in js
    assert 'res.status >= 500' in js
    assert 'detailText(body, "Temporary system error. (" + res.status + ")")' in js
    assert "Network error." in js
    work = client.get("/nova/work")
    assert work.status_code == 200
    assert b"nova-work" in work.content or b"Work" in work.content


def test_generate_actions_http_contracts(client: TestClient):
    """Caption / storyboard / image-prompt / export APIs succeed (UI should not appear dead)."""
    headers = _headers(client)
    created = client.post(
        "/api/nova/creative/projects",
        headers=headers,
        json={
            "title": "Action contract",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
            "audience": "small business owners",
            "tone": "professional and friendly",
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    brief = client.post(
        "/api/nova/creative/briefs",
        headers=headers,
        json={
            "project_id": project_id,
            "topic": "How AMICOR Nova helps small business owners save time and get work done with AI",
            "cta": "Learn more about AMICOR Nova",
            "style": "Modern, professional, energetic",
        },
    )
    assert brief.status_code == 200
    script = client.post(f"/api/nova/creative/projects/{project_id}/generate/script", headers=headers)
    assert script.status_code == 200
    assert "What if How" not in script.json()["pack"]["hook"]
    caption = client.post(f"/api/nova/creative/projects/{project_id}/generate/caption", headers=headers)
    assert caption.status_code == 200, caption.text
    assert caption.json()["pack"]["long_caption"]
    assert caption.json()["pack"]["hashtags"]
    storyboard = client.post(f"/api/nova/creative/projects/{project_id}/generate/storyboard", headers=headers)
    assert storyboard.status_code == 200, storyboard.text
    assert len(storyboard.json()["scenes"]) >= 3
    prompt = client.post(
        f"/api/nova/creative/projects/{project_id}/generate/image-prompt",
        headers=headers,
        json={"aspect_ratio": "9:16"},
    )
    assert prompt.status_code == 200, prompt.text
    assert prompt.json()["url"] is None
    exported = client.post(
        f"/api/nova/creative/projects/{project_id}/export",
        headers=headers,
        json={"format": "markdown"},
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["export"]["url"] is None
    assert exported.json()["export"]["package"]["external_publishing"] is False
    detail = client.get(f"/api/nova/creative/projects/{project_id}", headers=headers)
    assert detail.status_code == 200
    kinds = {a["kind"] for a in detail.json()["assets"]}
    assert "caption" in kinds or "hashtags" in kinds
    assert "storyboard" in kinds or "scene" in kinds
    assert "image_prompt" in kinds
    assert "export" in kinds


def test_generate_actions_ux_static_contract(client: TestClient):
    """Generate controls must show working state and never look silently dead."""
    page = client.get("/nova/creative")
    assert page.status_code == 200
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert 'working: "Working: Generate Caption..."' in js
    assert 'working: "Working: Generate Storyboard..."' in js
    assert 'working: "Working: Generate Image Prompt..."' in js
    assert 'working: "Working: Export Project Package..."' in js
    assert 'ok: "Caption generated."' in js
    assert 'ok: "Storyboard generated."' in js
    assert 'ok: "Image prompt generated."' in js
    assert 'ok: "Project package exported."' in js
    assert "button.disabled = true" in js
    assert "button.disabled = false" in js
    assert "await refreshAssets()" in js
    assert "await refreshProjects()" in js
    assert "renderOutput(body)" in js
    assert "Not found. Check the selected project. (404)" in js
    assert "Session expired. Sign in again. (401)" in js
    css = (ROOT / "static" / "nova-creative" / "creative.css").read_text(encoding="utf-8")
    assert "button:disabled" in css
    work = client.get("/nova/work")
    assert work.status_code == 200


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


def test_db_project_brief_brand_asset_scene_job_persistence_and_restart():
    """Create records, close session (restart simulation), reload and verify persistence."""
    svc1, db1 = _db_svc()
    try:
        brand = svc1.create_brand(
            "owner-persist",
            {
                "business_name": "AMICOR",
                "tagline": "Owner-controlled AI",
                "preferred_cta": "Learn more about AMICOR Nova",
                "target_audience": "small business owners",
            },
        )
        project = svc1.create_project(
            "owner-persist",
            {
                "title": "Persistent Creative Test",
                "project_type": "short_video",
                "platform": "TikTok",
                "duration_target": 30,
                "audience": "small business owners",
                "tone": "professional and friendly",
                "brand_profile_id": brand["id"],
            },
        )
        project_id = project["id"]
        svc1.create_brief(
            "owner-persist",
            {
                "project_id": project_id,
                "topic": "How AMICOR Nova helps small business owners save time and get work done with AI",
                "cta": "Learn more about AMICOR Nova",
                "style": "Modern, professional, energetic",
            },
        )
        script = svc1.generate_script("owner-persist", project_id)
        caption = svc1.generate_caption("owner-persist", project_id)
        story = svc1.generate_storyboard("owner-persist", project_id)
        prompt = svc1.generate_image_prompt("owner-persist", project_id, aspect_ratio="9:16")
        exported = svc1.export_project("owner-persist", project_id, fmt="markdown")
        assert script["pack"]["media_generated"] is False
        assert caption["pack"]["hashtags"]
        assert len(story["scenes"]) >= 3
        assert prompt["url"] is None
        assert exported["export"]["package"]["external_publishing"] is False
        assert exported["export"]["package"]["external_submission"] is False
        assert exported["export"]["package"]["financial_execution"] is False
    finally:
        db1.close()

    # Restart simulation: new session/store must still see records.
    svc2, db2 = _db_svc()
    try:
        listed = svc2.list_projects("owner-persist")
        assert any(p["id"] == project_id for p in listed)
        detail = svc2.get_project("owner-persist", project_id)
        assert detail["project"]["title"] == "Persistent Creative Test"
        assert detail["brief"] is not None
        assert detail["brand"] is not None
        assert detail["brand"]["business_name"] == "AMICOR"
        kinds = {a["kind"] for a in detail["assets"]}
        assert "script" in kinds
        assert "caption" in kinds or "hashtags" in kinds
        assert "storyboard" in kinds
        assert "image_prompt" in kinds
        assert "export" in kinds
        assert len(detail["scenes"]) >= 3
        assert detail["scenes"][0]["voiceover_text"]
        assert detail["scenes"][0]["subtitle_text"] == detail["scenes"][0]["voiceover_text"]
        assert detail["jobs"]
        rebuilt = svc2.export_project("owner-persist", project_id, fmt="json")
        assert rebuilt["export"]["package"]["external_publishing"] is False
        assert "AMICOR" in rebuilt["export"]["content"] or rebuilt["export"]["package"]["script"]
        # Cross-owner inaccessible
        with pytest.raises(CreativeStudioError) as exc:
            svc2.get_project("other-owner", project_id)
        assert exc.value.code == "NOT_FOUND"
        assert svc2.list_projects("other-owner") == []
        assert svc2.store.list_assets(project_id, "other-owner") == []
        assert svc2.store.list_scenes(project_id, "other-owner") == []
    finally:
        db2.close()


def test_http_persistence_survives_new_service_session(client: TestClient):
    headers = _headers(client)
    created = client.post(
        "/api/nova/creative/projects",
        headers=headers,
        json={
            "title": "HTTP persistent",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    assert client.post(
        "/api/nova/creative/briefs",
        headers=headers,
        json={"project_id": project_id, "topic": "workflow tip", "cta": "Learn more"},
    ).status_code == 200
    assert client.post(f"/api/nova/creative/projects/{project_id}/generate/script", headers=headers).status_code == 200
    # Fresh DB session read path
    db = SessionLocal()
    try:
        svc = CreativeStudioService(DbCreativeStudioStore(db))
        # Resolve owner_id from project list using HTTP then verify DB owner isolation by id presence
        detail = client.get(f"/api/nova/creative/projects/{project_id}", headers=headers)
        assert detail.status_code == 200
        assert any(a["kind"] == "script" for a in detail.json()["assets"])
        # Direct store ownership: unknown owner sees nothing
        assert svc.store.get_project(project_id, "not-the-owner") is None
    finally:
        db.close()


def test_image_generation_saves_provider_url_and_ui_renders_media(monkeypatch):
    from app.core.nova.creative_studio import service as service_module

    class FakeImageProvider:
        provider_id = "fake_image"

        def generate(self, *, prompt: str, aspect_ratio: str):
            return {
                "status": "GENERATED",
                "message": "generated",
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "url": "/static/generated/nova-creative/test-image.png",
                "asset_generated": True,
                "model": "test-model",
            }

    monkeypatch.setattr(service_module, "image_provider", lambda: FakeImageProvider())
    svc = _svc()
    project = svc.create_project(
        "owner-a",
        {"title": "Image persistence", "project_type": "social_image", "platform": "Instagram"},
    )
    result = svc.request_image_generation(
        "owner-a",
        project["id"],
        aspect_ratio="1:1",
        prompt="A clean business operations dashboard",
    )
    assert result["url"] == "/static/generated/nova-creative/test-image.png"
    assert result["asset"]["url"] == result["url"]
    assert result["asset"]["status"] == "GENERATED"
    assert result["provider"]["asset_generated"] is True

    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "nova-creative" / "creative.css").read_text(encoding="utf-8")
    assert 'row.kind === "image" && row.url' in js
    assert "generated-media" in js
    assert "Generating image..." in js
    assert ".generated-media img" in css


def test_brand_safe_image_prompt_and_aspect_selector_static_contract() -> None:
    from app.core.nova.creative_studio.generation import generate_content_pack

    pack = generate_content_pack(
        topic="AMICOR Nova helping small business owners organize work with AI",
        audience="small business owners",
        objective="awareness",
        tone="professional and modern",
        platform="Instagram",
        cta="Learn more about AMICOR Nova",
        brand_name="AMICOR Nova",
    )
    prompt = pack["image_prompt"].lower()
    assert "do not include any brand name, company name, logo, wordmark" in prompt
    assert "upper-left brand-safe area" in prompt

    html = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "nova-creative" / "creative.css").read_text(encoding="utf-8")
    assert 'id="image-aspect"' in html
    assert 'value="1:1"' in html
    assert 'value="4:5"' in html
    assert 'value="9:16"' in html
    assert 'value="16:9"' in html
    assert '$("image-aspect").value' in js
    assert "/static/branding/amicor-logo-full.png" in js
    assert "official-brand-overlay" in js
    assert ".official-brand-overlay" in css


def test_brand_safe_image_prompt_excludes_model_brand_text() -> None:
    from app.core.nova.creative_studio.generation import generate_content_pack

    pack = generate_content_pack(
        topic="AMICOR Nova helping small business owners organize work with AI",
        audience="small business owners",
        objective="awareness",
        tone="professional and friendly",
        platform="Instagram",
        cta="Learn more about AMICOR Nova",
        brand_name="AMICOR Nova",
    )
    prompt = pack["image_prompt"]
    assert "brand 'AMICOR Nova'" not in prompt
    assert "specifically do not render the words AMICOR or Nova" in prompt
    assert "no text or objects" in prompt


def test_creative_ui_has_branded_png_export_contract() -> None:
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert "downloadBrandedImage" in js
    assert 'Download branded PNG' in js
    assert "/static/branding/amicor-logo-full.png" in js
    assert 'canvas.toDataURL("image/png")' in js
    assert "Branded PNG prepared with the official AMICOR logo." in js


def test_creative_ui_has_first_real_promo_video_export_contract() -> None:
    html = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert "local branded image-animation fallback" in html
    assert "Provider status" in html
    assert "async function createPromoVideo" in js
    assert "MediaRecorder" in js
    assert "captureStream" in js
    assert "Create 8s branded video" in js
    assert 'video/webm' in js
    assert "-promo.webm" in js


def test_creative_ui_exposes_live_video_and_voice_actions() -> None:
    html = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert "8. Generate Next AI Scene" in html
    assert "9. Generate Voice" in html
    assert "Download AI video" in js
    assert "Download voice" in js
    assert "<video controls playsinline" in js
    assert "<audio controls" in js


def test_media_provider_owner_gates_are_explicit() -> None:
    flags = (CREATIVE_PY / "flags.py").read_text(encoding="utf-8")
    providers = (CREATIVE_PY / "providers.py").read_text(encoding="utf-8")
    assert "NOVA_CREATIVE_VIDEO_LIVE_ENABLED" in flags
    assert "NOVA_CREATIVE_VOICE_LIVE_ENABLED" in flags
    assert "RUNWAYML_API_SECRET" in flags
    assert "class RunwayVideoProvider" in providers
    assert "class OpenAIVoiceProvider" in providers
    assert "client.image_to_video.create" in providers
    assert "audio.speech.create" in providers


def test_did_talking_presenter_provider_success(monkeypatch, tmp_path):
    from app.core.nova.creative_studio import providers
    monkeypatch.setenv("DID_API_KEY", "test-user:test-secret")
    monkeypatch.setenv("NOVA_TALKING_PRESENTER_PROVIDER", "d-id")
    monkeypatch.setenv("NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    provider = providers.DidTalkingPresenterProvider()
    replies = iter([
        {"id": "talk-1", "status": "created"},
        {"id": "talk-1", "status": "done", "result_url": "https://example.invalid/talk.mp4"},
    ])
    requests = []

    def fake_request(method, url, *, payload=None):
        requests.append((method, url, payload))
        return next(replies)

    monkeypatch.setattr(provider, "_request_json", fake_request)
    monkeypatch.setattr(provider, "_save_remote_video", lambda url: "/media/nova-creative/presenter.mp4")
    monkeypatch.setattr(providers.time, "sleep", lambda *_: None)
    result = provider.generate(
        presenter_image_url="https://example.invalid/presenter.png",
        script="AMICOR Nova helps with research & reports <for review>. AMICOR prepares drafts.",
    )
    assert result["status"] == "GENERATED"
    assert result["asset_generated"] is True
    assert result["url"].endswith("presenter.mp4")
    assert result["talk_id"] == "talk-1"
    post_payload = requests[0][2]
    assert post_payload["script"]["provider"] == {
        "type": "microsoft",
        "voice_id": "en-US-JennyNeural",
        "voice_config": {"rate": "0.92"},
    }
    assert post_payload["script"]["ssml"] is True
    assert "AM ih core Nova" in post_payload["script"]["input"]
    from xml.etree import ElementTree
    markup = ElementTree.fromstring("<speak>" + post_payload["script"]["input"] + "</speak>")
    assert len(markup.findall("sub")) == 2
    assert not markup.findall(".//sub/sub")
    assert "research & reports <for review>" in "".join(markup.itertext())


def test_did_talking_presenter_requires_live_enable(monkeypatch):
    from app.core.nova.creative_studio import providers
    monkeypatch.setenv("DID_API_KEY", "test-user:test-secret")
    monkeypatch.setenv("NOVA_TALKING_PRESENTER_PROVIDER", "d-id")
    monkeypatch.delenv("NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED", raising=False)
    status = providers.DidTalkingPresenterProvider().status()
    assert status.status == "DISABLED"
    assert status.configured is True


def test_did_talking_presenter_timeout_is_safe(monkeypatch):
    from app.core.nova.creative_studio import providers
    monkeypatch.setenv("DID_API_KEY", "test-user:test-secret")
    monkeypatch.setenv("NOVA_TALKING_PRESENTER_PROVIDER", "d-id")
    monkeypatch.setenv("NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_TALKING_PRESENTER_WAIT_SECONDS", "15")
    provider = providers.DidTalkingPresenterProvider()
    monkeypatch.setattr(provider, "_request_json", lambda *args, **kwargs: {"id": "talk-2", "status": "created"})
    ticks = iter([0.0, 20.0])
    monkeypatch.setattr(providers.time, "monotonic", lambda: next(ticks))
    result = provider.generate(
        presenter_image_url="https://example.invalid/presenter.png",
        script="Hello.",
    )
    assert result["status"] == "ERROR"
    assert "timed out" in result["message"].lower()
    assert result["asset_generated"] is False


def test_did_authorization_is_not_exposed_in_status(monkeypatch):
    from app.core.nova.creative_studio import providers
    secret = "test-user:super-secret-value"
    monkeypatch.setenv("DID_API_KEY", secret)
    monkeypatch.setenv("NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED", "true")
    provider = providers.DidTalkingPresenterProvider()
    status = provider.status().as_dict()
    assert secret not in str(status)
    assert "super-secret-value" not in str(status)


def test_presenter_mode_controls_and_payload_contract() -> None:
    html = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    router = (CREATIVE_PY / "router.py").read_text(encoding="utf-8")

    assert 'id="presenter-mode"' in html
    assert 'value="head"' in html
    assert 'value="half_body"' in html
    assert 'value="full_body"' in html
    assert 'id="presenter-motion-style"' in html
    assert 'id="presenter-framing"' in html
    assert 'id="presenter-output-preset"' in html

    assert 'presenter_mode:' in js
    assert 'motion_style:' in js
    assert 'framing:' in js
    assert 'output_preset:' in js

    assert 'payload.presenter_mode == "head"' in router
    assert '"half_body"' in router
    assert '"full_body"' in router
    assert 'motion_provider.generate' in router
    assert '"quality_state"' in router
    assert '"publish_ready"' in router
    assert "Nova preserves provider AI disclosure watermarks" in router
    assert "DEMO_READY_WITH_PROVIDER_WATERMARK" in router


def test_presenter_provider_watermark_readiness_is_explicit() -> None:
    providers = (CREATIVE_PY / "providers.py").read_text(encoding="utf-8")
    router = (CREATIVE_PY / "router.py").read_text(encoding="utf-8")
    service = (CREATIVE_PY / "service.py").read_text(encoding="utf-8")
    assert "NOVA_CREATIVE_DID_WATERMARK_FREE_OUTPUT" in providers
    assert "NOVA_CREATIVE_VIDEO_WATERMARK_FREE_OUTPUT" in providers
    assert '"watermark_free"' in providers
    assert "DEMO_READY_WITH_PROVIDER_WATERMARK" in router
    assert '"demo_ready": demo_ready' in router
    assert '"provider_watermark_preserved"' in router
    assert "_presenter_demo_eligible" in service
    assert 'bool(metadata.get("demo_ready"))' in service
    assert '"legacy_did_demo_passthrough"' in service


def test_brand_defaults_and_production_presets_static_contract() -> None:
    html = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")

    assert 'id="load-amicor-brand-defaults"' in html
    assert 'id="production-preset"' in html
    assert 'value="vertical_short"' in html
    assert 'value="social_square"' in html
    assert 'value="youtube_web"' in html

    assert 'business_name: "AMICOR Nova"' in js
    assert 'tagline: "AI help for everyday business operations"' in js
    assert 'preferred_cta: "Start free today"' in js
    assert "applyAmicorBrandDefaults" in js
    assert "applyProductionPreset" in js
    assert 'imageAspect.value = "9:16"' in js
    assert 'imageAspect.value = "1:1"' in js
    assert 'imageAspect.value = "16:9"' in js
    assert 'presenterOutput.value = "9:16"' in js
    assert 'presenterOutput.value = "16:9"' in js


def test_export_includes_social_media_production_package() -> None:
    from app.core.nova.creative_studio.export import export_project_package

    payload = {
        "project": {"title": "Promo", "platform": "YouTube", "status": "ACTIVE"},
        "brief": {"cta": "Start free today"},
        "brand": {"business_name": "AMICOR Nova"},
        "scenes": [],
        "assets": [
            {"id": "img1", "kind": "image", "title": "Artwork", "status": "GENERATED", "url": "/media/art.png", "metadata": {}},
            {"id": "aud1", "kind": "audio", "title": "Voice", "status": "GENERATED", "url": "/media/voice.mp3", "metadata": {}},
            {"id": "cap1", "kind": "caption", "title": "Caption", "status": "GENERATED", "content": "Save time. Stay in control.", "metadata": {}},
            {"id": "tag1", "kind": "hashtags", "title": "Tags", "status": "GENERATED", "content": "#AMICOR #AI", "metadata": {}},
            {"id": "vid1", "kind": "video", "title": "Final AMICOR Nova promo", "status": "GENERATED", "url": "/media/final.mp4", "metadata": {"final_promo": True}},
            {"id": "pres1", "kind": "presenter_video", "title": "Presenter", "status": "GENERATED", "url": "/media/presenter.mp4", "metadata": {"publish_ready": True, "quality_state": "PUBLISH_READY"}},
        ],
    }

    exported = export_project_package(payload, fmt="json")
    package = exported["package"]
    social = package["social_media_package"]
    checklist = package["delivery_checklist"]

    assert social["production_ready"] is True
    assert social["final_video"]["url"] == "/media/final.mp4"
    assert social["presenter_video"]["publish_ready"] is True
    assert social["thumbnail_or_artwork"]["url"] == "/media/art.png"
    assert social["voice_audio"]["url"] == "/media/voice.mp3"
    assert social["caption_copy"] == "Save time. Stay in control."
    assert social["cta"] == "Start free today"
    assert checklist["video_ready"] is True
    assert checklist["presenter_ready"] is True
    assert checklist["thumbnail_ready"] is True
    assert checklist["voice_ready"] is True


def test_creative_ui_has_production_readiness_panel() -> None:
    html = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "nova-creative" / "creative.css").read_text(encoding="utf-8")

    assert 'id="production-readiness"' in html
    assert "Production readiness" in html
    assert "renderProductionReadiness" in js
    assert '"PUBLISH_READY"' in js
    assert '"PREVIEW_ONLY"' in js
    assert "READY FOR OWNER REVIEW" in js
    assert "NEEDS WORK" in js
    assert "Build Final Promo" in js
    assert ".readiness-grid" in css
    assert ".readiness-summary.ready" in css
    assert ".readiness-item.missing" in css


@pytest.mark.parametrize("mode,expected_framing", [("half_body", "waist_up"), ("full_body", "full_frame")])
def test_body_presenter_routes_to_motion_without_claiming_speech(monkeypatch, mode, expected_framing):
    from types import SimpleNamespace
    from app.auth import UserContext
    import importlib
    studio_router = importlib.import_module("app.core.nova.creative_studio.router")

    svc = _svc()
    project = svc.create_project("owner-a", {"title": "Body demo", "project_type": "short_video"})
    calls = []
    monkeypatch.setattr(studio_router, "get_service", lambda db: svc)
    monkeypatch.setattr(svc, "request_image_generation", lambda *args, **kwargs: {
        "url": "https://example.test/source.png", "asset": {"id": "image-a"},
    })
    def generate(*, brief):
        calls.append(brief)
        return {"status": "GENERATED", "asset_generated": True, "url": "https://example.test/body.mp4", "watermark_free": True}
    monkeypatch.setattr(studio_router, "video_provider", lambda: SimpleNamespace(
        status=lambda: SimpleNamespace(status="AVAILABLE"), generate=generate,
    ))
    def unexpected_head():
        pytest.fail("Body motion must not invoke the talking-head provider")
    monkeypatch.setattr(studio_router, "talking_presenter_provider", unexpected_head)
    result = studio_router.prepare_talking_presenter_preview(
        project["id"], studio_router.PresenterIn(script="Hello from Nova", presenter_mode=mode, framing="close_up"),
        UserContext(user_id="owner-a", email="owner@example.test", role="admin"), None,
    )
    assert len(calls) == 1
    assert calls[0]["prompt_image_url"] == "https://example.test/source.png"
    assert ("head-to-toe" if mode == "full_body" else "waist-up") in calls[0]["prompt_text"]
    assert result["framing"] == expected_framing
    assert result["lip_sync"] is False
    assert result["talking_presenter"] is False
    assert result["publish_ready"] is False
    assert result["quality_state"] == "PREVIEW_ONLY"
    assert result["body_motion_review_required"] is True


def test_unavailable_body_provider_does_not_generate_paid_source_image(monkeypatch):
    from types import SimpleNamespace
    from app.auth import UserContext
    import importlib
    studio_router = importlib.import_module("app.core.nova.creative_studio.router")

    svc = _svc()
    project = svc.create_project("owner-a", {"title": "Body demo", "project_type": "short_video"})
    monkeypatch.setattr(studio_router, "get_service", lambda db: svc)
    monkeypatch.setattr(studio_router, "video_provider", lambda: SimpleNamespace(
        status=lambda: SimpleNamespace(status="CONFIG_REQUIRED", message="Configure motion provider"),
    ))
    def unexpected_image(*args, **kwargs):
        pytest.fail("Unavailable motion provider must not spend on a source image")
    monkeypatch.setattr(svc, "request_image_generation", unexpected_image)
    result = studio_router.prepare_talking_presenter_preview(
        project["id"], studio_router.PresenterIn(script="Hello", presenter_mode="full_body"),
        UserContext(user_id="owner-a", email="owner@example.test", role="admin"), None,
    )
    assert result["status"] == "CONFIG_REQUIRED"
    assert result["publish_ready"] is False


def test_creative_ui_readiness_panel_has_next_actions() -> None:
    js = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "nova-creative" / "creative.css").read_text(encoding="utf-8")

    assert "Next action" in js
    assert "Do this next" in js
    assert 'data-next-action' in js
    assert 'build-final-promo' in js
    assert 'preview-talking-presenter' in js
    assert 'generate-image' in js
    assert 'generate-voice' in js
    assert 'generate-caption' in js
    assert 'brand-profile' in js
    assert '.next-action-card' in css
    assert '.readiness-action' in css


@pytest.mark.parametrize("matching", [True, False])
def test_head_presenter_reuses_only_matching_narration(monkeypatch, matching):
    monkeypatch.setenv("NOVA_TALKING_PRESENTER_PROVIDER", "d-id")
    from types import SimpleNamespace
    from app.auth import UserContext
    import importlib
    studio_router = importlib.import_module("app.core.nova.creative_studio.router")
    svc = _svc()
    project = svc.create_project("owner-a", {"title": "Narrated demo", "project_type": "explainer"})
    svc._save_text_asset(owner_id="owner-a", project_id=project["id"], kind="image", title="Portrait", content="Genova presenter v2. Photorealistic young Black woman presenter.", status="GENERATED", url="https://example.test/portrait.png", metadata={})
    audio = svc._save_text_asset(
        owner_id="owner-a", project_id=project["id"], kind="audio", title="Narration",
        content="Current script" if matching else "Old script", status="GENERATED",
        url="/media/narration.mp3",
        metadata={"provider_result": {"voice": "shimmer", "caption_cues": [{"text": "Current script", "start": 0.0, "end": 1.0}], "presenter_audio_version": 2}},
    )
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return {"status": "GENERATED", "url": "/media/presenter.mp4", "asset_generated": True, "watermark_free": True}
    monkeypatch.setattr(studio_router, "get_service", lambda db: svc)
    monkeypatch.setattr(studio_router, "talking_presenter_provider", lambda: SimpleNamespace(generate=generate))
    payload = studio_router.PresenterIn(script="Current script", presenter_mode="head", voice="shimmer", captions=True)
    user = UserContext(user_id="owner-a", email="owner@example.test", role="admin")
    if not matching:
        with pytest.raises(studio_router.HTTPException) as exc:
            studio_router.prepare_talking_presenter_preview(project["id"], payload, user, None)
        assert exc.value.status_code == 422
        assert "Generate Presenter Voice first" in str(exc.value.detail)
        assert calls == []
        return

    from pathlib import Path
    from app.core.nova.creative_studio import providers as studio_providers, presenter_media
    monkeypatch.setattr(studio_providers, "_resolve_creative_media_url", lambda url: Path("/tmp/presenter.mp4"))
    monkeypatch.setattr(
        presenter_media,
        "caption_presenter",
        lambda source, cues: (Path("/tmp/presenter-captioned.mp4"), Path("/tmp/presenter.srt")),
    )
    result = studio_router.prepare_talking_presenter_preview(project["id"], payload, user, None)
    assert calls[0].get("audio_url") == audio.url
    assert result.get("source_audio_asset_id") == audio.id
    assert result["publish_ready"] is True



def test_head_presenter_preserves_fresh_video_when_caption_render_hits_memory_limit(monkeypatch):
    monkeypatch.setenv("NOVA_TALKING_PRESENTER_PROVIDER", "d-id")
    from types import SimpleNamespace
    from pathlib import Path
    from app.auth import UserContext
    import importlib

    studio_router = importlib.import_module("app.core.nova.creative_studio.router")
    svc = _svc()
    project = svc.create_project("owner-a", {"title": "Narrated demo", "project_type": "explainer"})
    image = svc._save_text_asset(
        owner_id="owner-a", project_id=project["id"], kind="image", title="Genova portrait",
        content="Genova presenter v2. Photorealistic young Black woman presenter.",
        status="GENERATED", url="/media/genova-v2.png", metadata={},
    )
    audio = svc._save_text_asset(
        owner_id="owner-a", project_id=project["id"], kind="audio", title="Narration",
        content="Current script", status="GENERATED", url="/media/narration.mp3",
        metadata={"provider_result": {"voice": "shimmer", "caption_cues": [{"text": "Current script", "start": 0.0, "end": 1.0}], "presenter_audio_version": 2}},
    )

    monkeypatch.setattr(studio_router, "get_service", lambda db: svc)
    monkeypatch.setattr(
        studio_router,
        "talking_presenter_provider",
        lambda: SimpleNamespace(generate=lambda **kwargs: {
            "status": "GENERATED",
            "url": "/media/fresh-genova-presenter.mp4",
            "asset_generated": True,
            "watermark_free": True,
        }),
    )

    from app.core.nova.creative_studio import providers as studio_providers, presenter_media
    monkeypatch.setattr(studio_providers, "_resolve_creative_media_url", lambda url: Path("/tmp/fresh-genova-presenter.mp4"))
    monkeypatch.setattr(
        presenter_media,
        "caption_presenter",
        lambda source, cues: (_ for _ in ()).throw(RuntimeError("Nova paused video rendering: insufficient server memory headroom. No encoder was started.")),
    )

    result = studio_router.prepare_talking_presenter_preview(
        project["id"],
        studio_router.PresenterIn(script="Current script", presenter_mode="head", voice="shimmer", captions=True),
        UserContext(user_id="owner-a", email="owner@example.test", role="admin"),
        None,
    )

    assert result["url"] == "/media/fresh-genova-presenter.mp4"
    assert result["publish_ready"] is False
    assert result["asset"]["metadata"]["source_image_asset_id"] == image.id
    assert result["asset"]["metadata"]["captions_burned_in"] is False
    assert "insufficient server memory headroom" in result["asset"]["metadata"]["caption_render_error"]
    assert result["source_audio_asset_id"] == audio.id


def test_did_presenter_accepts_saved_studio_audio(monkeypatch):
    from app.core.nova.creative_studio import providers
    monkeypatch.setenv("DID_API_KEY", "test-user:test-secret")
    monkeypatch.setenv("NOVA_TALKING_PRESENTER_PROVIDER", "d-id")
    monkeypatch.setenv("NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED", "true")
    monkeypatch.setenv("AMICOR_PUBLIC_URL", "https://example.test")
    provider = providers.DidTalkingPresenterProvider()
    calls = []
    def request(method, url, *, payload=None):
        calls.append(payload)
        return {"id": "talk-audio", "status": "done", "result_url": "https://example.test/final.mp4"}
    monkeypatch.setattr(provider, "_request_json", request)
    monkeypatch.setattr(provider, "_save_remote_video", lambda url: "/media/final.mp4")
    result = provider.generate(presenter_image_url="/media/portrait.png", script="Current script", audio_url="/media/narration.mp3")
    assert calls[0]["script"] == {"type": "audio", "audio_url": "https://example.test/media/narration.mp3"}
    assert result["asset_generated"] is True



def test_final_promo_has_low_memory_scene_normalization_fallback():
    import inspect
    from app.core.nova.creative_studio.service import CreativeStudioService

    source = inspect.getsource(CreativeStudioService.assemble_final_promo)
    assert "normalized_scene_clips = False" in source
    assert "scene {offset + 1} normalization failed" in source
    assert "normalized scene join failed" in source
    assert "scene_clip_normalize_then_concat" in source



def test_final_promo_memory_recovery_uses_lightweight_normalization():
    import inspect
    from app.core.nova.creative_studio.service import CreativeStudioService

    source = inspect.getsource(CreativeStudioService.assemble_final_promo)
    assert "recovery_deadline = time.monotonic() + 10.0" in source
    assert "160 * 1024 * 1024" in source
    assert "normalize_width, normalize_height = ((540, 960) if vertical else (960, 540))" in source
    assert "normalize_fps = 20" in source
    assert '"-preset", "ultrafast"' in source
    assert '"ref=1:bframes=0:rc-lookahead=0:sync-lookahead=0"' in source



def test_existing_project_can_attach_saved_brand():
    import inspect
    from app.core.nova.creative_studio.service import CreativeStudioService

    source = inspect.getsource(CreativeStudioService.attach_brand_to_project)
    assert "project.brand_profile_id = brand.id" in source
    assert '"Brand profile attached to active project."' in source


def test_final_promo_reuses_publish_ready_presenter_without_encoder(monkeypatch, tmp_path):
    from app.core.nova.creative_studio import service as studio_service
    from app.core.nova.creative_studio.models import CreativeAsset, CreativeProject, CreativeScene
    from app.core.nova.creative_studio.store import CreativeStudioStore

    store = CreativeStudioStore()
    svc = studio_service.CreativeStudioService(store)
    owner = "owner-presenter-final"
    project = CreativeProject(
        id="cproj_presenter_final",
        owner_id=owner,
        title="Presenter final",
        project_type="explainer",
        platform="website",
        objective="demo",
        audience="business",
        tone="professional",
        status="storyboarded",
    )
    store.save_project(project)
    store.save_scene(CreativeScene(
        id="scene1",
        project_id=project.id,
        owner_id=owner,
        index=1,
        heading="Demo",
        description="Demo",
        visual_prompt="Demo scene",
        voiceover_text="Welcome to AMICOR Nova.",
        subtitle_text="Welcome to AMICOR Nova.",
        duration_seconds=5.0,
    ))
    media = tmp_path / "presenter.mp4"
    media.write_bytes(b"publish-ready-presenter")
    presenter = CreativeAsset(
        id="presenter1",
        project_id=project.id,
        owner_id=owner,
        kind="presenter_video",
        title="Genova presenter",
        content="Welcome to AMICOR Nova.",
        status="GENERATED",
        url="/media/nova-creative/presenter.mp4",
        metadata={"publish_ready": True, "subtitle_url": "/media/nova-creative/presenter.srt"},
    )
    store.save_asset(presenter)
    monkeypatch.setattr(studio_service, "_resolve_creative_media_url", lambda url: media)
    monkeypatch.setattr(studio_service, "run_encoder", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("encoder must not run")))

    result = svc.assemble_final_promo(owner, project.id)

    assert result["url"] == presenter.url
    assert result["asset"]["metadata"]["final_promo"] is True
    assert result["asset"]["metadata"]["render_mode"] == "publish_ready_presenter_passthrough"
    assert result["asset"]["metadata"]["subtitle_url"] == "/media/nova-creative/presenter.srt"


def test_final_promo_reuses_legacy_did_preview_without_encoder(monkeypatch, tmp_path):
    from app.core.nova.creative_studio import service as studio_service
    from app.core.nova.creative_studio.models import CreativeAsset, CreativeProject, CreativeScene
    from app.core.nova.creative_studio.store import CreativeStudioStore

    store = CreativeStudioStore()
    svc = studio_service.CreativeStudioService(store)
    owner = "owner-legacy-did"
    project = CreativeProject(
        id="cproj_legacy_did",
        owner_id=owner,
        title="Legacy D-ID demo",
        project_type="explainer",
        platform="website",
        objective="demo",
        audience="business",
        tone="professional",
        status="storyboarded",
    )
    store.save_project(project)
    store.save_scene(CreativeScene(
        id="scene1",
        project_id=project.id,
        owner_id=owner,
        index=1,
        heading="Demo",
        description="Demo",
        visual_prompt="Demo scene",
        voiceover_text="Welcome to AMICOR Nova.",
        subtitle_text="Welcome to AMICOR Nova.",
        duration_seconds=5.0,
    ))
    media = tmp_path / "legacy-presenter.mp4"
    media.write_bytes(b"legacy-did-presenter")
    presenter = CreativeAsset(
        id="presenter-legacy",
        project_id=project.id,
        owner_id=owner,
        kind="presenter_video",
        title="Talking presenter preview",
        content="Welcome to AMICOR Nova.",
        status="GENERATED",
        url="/media/nova-creative/legacy-presenter.mp4",
        metadata={
            "quality_state": "PREVIEW_ONLY",
            "publish_ready": False,
            "presenter_mode": "head",
            "captions_burned_in": False,
            "captions_sidecar_ready": True,
            "subtitle_url": "/media/nova-creative/legacy-presenter.srt",
            "provider_result": {"provider": "d-id", "watermark_free": False},
        },
    )
    store.save_asset(presenter)
    monkeypatch.setattr(studio_service, "_resolve_creative_media_url", lambda url: media)
    monkeypatch.setattr(
        studio_service,
        "run_encoder",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("encoder must not run")),
    )

    result = svc.assemble_final_promo(owner, project.id)

    assert result["url"] == presenter.url
    metadata = result["asset"]["metadata"]
    assert metadata["final_promo"] is True
    assert metadata["render_mode"] == "legacy_did_demo_passthrough"
    assert metadata["demo_ready"] is True
    assert metadata["provider_watermark_preserved"] is True
    assert metadata["subtitle_url"] == "/media/nova-creative/legacy-presenter.srt"
