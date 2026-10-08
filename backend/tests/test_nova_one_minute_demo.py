from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_one_minute_demo_static_contract():
    html = (ROOT / "static" / "nova-one-minute-demo" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-one-minute-demo" / "demo.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "nova-one-minute-demo" / "demo.css").read_text(encoding="utf-8")

    assert "60-Second Product Demo" in html
    assert 'id="narration"' in html
    assert "/media/nova-creative/nova-bb9d59169aef4733ba8c07d1b0d418f6.mp3" in html
    assert 'id="genova-video"' in html
    assert "/media/nova-creative/nova-da25e10f80924d6ca99e62a04c9eb346.mp4" in html
    assert 'id="caption-bar"' in html
    assert 'id="demo-frame"' in html

    assert 'route: "/nova/today"' in js
    assert 'route: "/nova/workspace"' in js
    assert 'route: "/nova/anonymous-operations"' in js
    assert 'route: "/nova/work"' in js
    assert 'route: "/nova/government"' in js
    assert 'route: "/nova/creative"' in js
    assert "audio.addEventListener(\"timeupdate\", update)" in js
    assert "video.play()" in js
    assert "caption.textContent = cue.text" in js
    assert "presenter-box" in css
    assert "object-fit: contain" in css
    assert "height: 72%" in css


def test_one_minute_demo_route_and_creative_link_are_wired():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    creative = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")

    assert '@app.get("/nova/one-minute-demo")' in main
    assert "nova-one-minute-demo" in main
    assert 'href="/nova/one-minute-demo"' in creative


def test_one_minute_demo_supports_full_recording_export() -> None:
    html = (ROOT / "static" / "nova-one-minute-demo" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-one-minute-demo" / "demo.js").read_text(encoding="utf-8")
    assert 'id="record-demo"' in html
    assert "navigator.mediaDevices.getDisplayMedia" in js
    assert "MediaRecorder" in js
    assert "AMICOR-Nova-60-second-master-demo.webm" in js
    assert 'audio.addEventListener("ended", stopAfterDemo)' in js


def test_one_minute_demo_mutes_embedded_nova_voice() -> None:
    html = (ROOT / "static" / "nova-one-minute-demo" / "index.html").read_text(encoding="utf-8")
    demo_js = (ROOT / "static" / "nova-one-minute-demo" / "demo.js").read_text(encoding="utf-8")
    voice_js = (ROOT / "static" / "ux" / "novaVoiceControls.js").read_text(encoding="utf-8")

    assert 'src="/nova?nova_demo_embed=1"' in html
    assert '"nova_demo_embed=1"' in demo_js
    assert 'params.get("nova_demo_embed") === "1"' in voice_js
    assert 'data-nova-demo-voice-muted' in voice_js
    assert 'if (demoEmbed)' in voice_js


def test_one_minute_demo_has_public_website_cta_and_search_metadata() -> None:
    html = (ROOT / "static" / "nova-one-minute-demo" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "nova-one-minute-demo" / "demo.js").read_text(encoding="utf-8")
    assert "https://getamicor.com" in html
    assert "Visit getamicor.com" in html
    assert 'id="demo-end-cta"' in html
    assert '<meta name="description"' in html
    assert '<link rel="canonical"' in html
    assert '"@type":"VideoObject"' in html
    assert 'endCta.classList.toggle("hidden", t < 56.5)' in js
