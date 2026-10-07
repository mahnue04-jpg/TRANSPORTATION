from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_master_demo_stage_static_contract():
    html = (ROOT / "static" / "nova-master-demo" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-master-demo" / "master-demo.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "nova-master-demo" / "master-demo.css").read_text(encoding="utf-8")

    assert "30-Minute Master Product Demo Stage" in html
    assert 'id="presenter-video"' in html
    assert "/media/nova-creative/nova-e35c88123a07412a97129aaf662bb57f.mp4" in html
    assert 'id="product-frame"' in html
    assert 'id="caption-bar"' in html

    assert "var TOTAL_SECONDS = 30 * 60;" in js
    assert 'route: "/nova/today"' in js
    assert 'route: "/nova/workspace"' in js
    assert 'route: "/nova/anonymous-operations"' in js
    assert 'route: "/nova/work"' in js
    assert 'route: "/nova/communications"' in js
    assert 'route: "/nova/government"' in js
    assert 'route: "/nova/business"' in js
    assert 'route: "/nova/accounting"' in js
    assert 'route: "/nova/creative"' in js
    assert "Unfinished features are not presented as live products." in js

    assert ".presenter-panel" in css
    assert ".caption-bar" in css
    assert "aspect-ratio: 16 / 9" in css


def test_master_demo_route_and_creative_link_are_wired():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    creative = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")

    assert '@app.get("/nova/master-demo")' in main
    assert 'nova-master-demo' in main
    assert 'href="/nova/master-demo"' in creative
