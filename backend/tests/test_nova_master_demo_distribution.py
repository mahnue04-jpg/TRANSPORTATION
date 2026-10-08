from pathlib import Path

from app.core.nova.work_revenue.materials import MASTER_DEMO_URL, generate_drafts


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_master_demo_is_featured_across_primary_nova_surfaces() -> None:
    expected = 'href="/nova/one-minute-demo"'
    for rel in [
        "static/nova-home/index.html",
        "static/nova-work/index.html",
        "static/nova-today/index.html",
        "static/nova-workspace/index.html",
        "static/marketing/nova.html",
        "static/marketing/business.html",
    ]:
        assert expected in _read(rel), rel


def test_master_demo_has_native_share_controls() -> None:
    html = _read("static/nova-one-minute-demo/index.html")
    js = _read("static/nova-one-minute-demo/demo.js")
    assert 'id="share-demo"' in html
    assert 'id="copy-demo-link"' in html
    assert "navigator.share" in js
    assert "navigator.clipboard.writeText" in js
    assert '"/nova/one-minute-demo"' in js


def test_job_materials_include_product_demo_without_client_claims() -> None:
    assert MASTER_DEMO_URL.endswith("/nova/one-minute-demo")
    drafts = generate_drafts(
        {
            "opportunity_title": "AI operations contractor",
            "company_name": "Example Client",
            "description": "Prepare digital operations materials.",
        }
    )
    bodies = "\n".join(row["body"] for row in drafts)
    assert MASTER_DEMO_URL in bodies
    assert "prior client work" in bodies.lower() or "fabricated" in bodies.lower()
