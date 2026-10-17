from pathlib import Path
from types import SimpleNamespace
import pytest
from app.core.nova.creative_studio.presenter_media import caption_cues, srt_text, caption_presenter


def test_alignment_keeps_reviewed_brand_and_every_script_word():
    script = 'Welcome to AMICOR Nova. We prepare reports for your review.'
    heard = 'Welcome to Amacore Nova We prepare reports for your review'.split()
    words = [{'word':w,'start':i*.4,'end':(i+1)*.4} for i,w in enumerate(heard)]
    cues = caption_cues(script, words, 4.)
    assert ' '.join(c['text'] for c in cues) == script
    assert all(a['end'] <= b['start'] for a,b in zip(cues,cues[1:]))
    assert cues[-1]['end'] == 4.
    assert 'AMICOR Nova.' in srt_text(cues)


def test_unrelated_speech_cannot_be_silently_captioned_as_reviewed_script():
    with pytest.raises(RuntimeError, match='alignment needs review'):
        caption_cues('We prepare reports for review.', [{'word':'Something','start':0,'end':1}], 1.)


def test_caption_render_retains_original_frame_and_escapes_ass_commands(tmp_path, monkeypatch):
    import app.core.nova.creative_studio.presenter_media as media
    calls=[]
    monkeypatch.setattr(media, '_encode', lambda args, *rest: calls.append(args))
    video = tmp_path / 'nova-example.mp4'
    output, srt = caption_presenter(video, [{'start':0,'end':1,'text':r'Review {\\pos(0,0)} everything.'}])
    ass=video.with_suffix('.ass').read_text(encoding="utf-8")
    assert r'{\\pos(0,0)}' not in ass
    assert 'pad=512:640' in calls[0][calls[0].index('-vf')+1]
    assert 'fontsdir=' in calls[0][calls[0].index('-vf')+1]
    assert '-c:a' in calls[0]
    assert srt.is_file()
    assert output.name.endswith('-captioned.mp4')


def test_loudness_analysis_accepts_ffmpeg_progress_after_measurements(tmp_path, monkeypatch):
    import app.core.nova.creative_studio.presenter_media as media
    calls=[]
    def encoder(args, *rest):
        calls.append(args)
        return SimpleNamespace(stderr='log\n{"input_i":"-23","input_tp":"-6","input_lra":"2","input_thresh":"-33","target_offset":"0"}\nsize=123 time=1')
    monkeypatch.setattr(media, '_encode', encoder)
    out, meta = media.normalize_narration(tmp_path/'quiet.mp3')
    assert meta['original_lufs'] == '-23'
    assert meta['target_lufs'] == -16
    assert 'measured_I=-23' in calls[1][calls[1].index('-af')+1]


def test_presenter_provider_uses_selected_voice_and_measured_speech_captions(tmp_path, monkeypatch):
    from app.core.nova.creative_studio import providers, presenter_media
    calls=[]
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    monkeypatch.setenv('NOVA_CREATIVE_VOICE_LIVE_ENABLED','true')
    monkeypatch.setenv('NOVA_CREATIVE_VOICE_ASSET_DIR',str(tmp_path))
    monkeypatch.setenv('NOVA_CREATIVE_VOICE_MODEL','gpt-4o-mini-tts')
    def speech(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=b'test audio')
    transcript={'duration':2.,'words':[{'word':'Hello','start':0.,'end':.5},{'word':'Genova','start':.5,'end':2.}]}
    client=SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=speech),transcriptions=SimpleNamespace(create=lambda **kwargs: transcript)))
    monkeypatch.setattr(providers,'get_client',lambda: client)
    monkeypatch.setattr(presenter_media,'normalize_narration',lambda path:(path,{'target_lufs':-16}))
    result=providers.OpenAIVoiceProvider().generate(script='Hello Genova.',voice='coral',presenter=True)
    assert calls[0]['voice'] == 'coral'
    assert 'young adult woman' in calls[0]['instructions']
    assert 'unmistakably feminine voice' in calls[0]['instructions']
    assert ' '.join(c['text'] for c in result['caption_cues']) == 'Hello Genova.'
    assert result['presenter_audio_version'] == 2



def test_presenter_voice_preserves_original_audio_when_normalization_hits_memory_limit(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app.core.nova.creative_studio import providers

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_ASSET_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.setattr(
        providers,
        "get_client",
        lambda: SimpleNamespace(
            audio=SimpleNamespace(
                speech=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(content=b"fake-mp3-bytes")
                ),
                transcriptions=SimpleNamespace(
                    create=lambda **kwargs: {
                        "duration": 1.0,
                        "words": [{"word": "Hello", "start": 0.0, "end": 0.5}, {"word": "Genova.", "start": 0.5, "end": 1.0}],
                    }
                ),
            )
        ),
    )
    import app.core.nova.creative_studio.presenter_media as media
    monkeypatch.setattr(
        media,
        "normalize_narration",
        lambda path: (_ for _ in ()).throw(RuntimeError("Presenter media processing failed: Nova paused video rendering: insufficient server memory headroom. No encoder was started.")),
    )

    result = providers.OpenAIVoiceProvider().generate(
        script="Hello Genova.",
        voice="shimmer",
        presenter=True,
    )

    assert result["status"] == "GENERATED"
    assert result["url"].endswith(".mp3")
    assert "-clear.mp3" not in result["url"]
    assert result["loudness"]["normalization_skipped"] is True
    assert "insufficient server memory headroom" in result["loudness"]["normalization_error"]
    assert result["presenter_audio_version"] == 2
    assert " ".join(cue["text"] for cue in result["caption_cues"]) == "Hello Genova."


def test_full_body_demo_saves_looped_video_with_audio_and_captions(tmp_path, monkeypatch):
    from PIL import Image
    from app.core.nova.creative_studio import presenter_media as media
    from app.core.nova.creative_studio.full_body_demo import assemble_full_body_demo, demo_cues

    config = tmp_path / "empty-fontconfig.xml"
    config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig></fontconfig>')
    monkeypatch.setenv("FONTCONFIG_FILE", str(config))
    presenter = tmp_path / "presenter.mp4"
    narration = tmp_path / "narration.mp3"
    media._encode([
        "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1",
        "-an", "-t", "1", "-c:v", "libx264", "-threads", "1", str(presenter),
    ])
    media._encode([
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-t", "2", "-c:a", "libmp3lame", str(narration),
    ])
    js = (Path(__file__).resolve().parents[1] / "static" / "nova-one-minute-demo" / "demo.js").read_text(encoding="utf-8")
    cues = demo_cues(js)
    assert cues[0]["text"].startswith("Meet AMICOR Nova")
    assert cues[-1]["text"] == "Start with AMICOR Nova today."
    output = tmp_path / "saved.mp4"
    saved = assemble_full_body_demo(presenter, narration, [{"start": 0.2, "end": 1.6, "text": "Hello Genova."}], output)
    assert saved["presenter_mode"] == "full_body"
    assert saved["captions_burned_in"] is True
    assert output.is_file() and output.with_suffix(".vtt").is_file() and output.with_suffix(".srt").is_file()
    assert "Hello Genova." in output.with_suffix(".vtt").read_text(encoding="utf-8")
    import imageio_ffmpeg
    from app.core.nova.creative_studio.media_runtime import run_encoder
    detail = run_encoder(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(output)],
        timeout=30,
        required_headroom=64 * 1024 * 1024,
    )
    assert "Audio:" in detail.stderr
    assert "Video:" in detail.stderr
    frame = tmp_path / "caption.png"
    media._encode(["-ss", "0.8", "-i", str(output), "-frames:v", "1", str(frame)])
    image = Image.open(frame).convert("RGB")
    band = image.crop((0, image.height - 96, image.width, image.height))
    assert sum(1 for pixel in band.getdata() if min(pixel) > 220) > 100
    assert image.size[0] == 320
    assert image.size[1] == 180 + 96


def test_captions_are_visible_without_system_fonts(tmp_path, monkeypatch):
    from PIL import Image
    from app.core.nova.creative_studio import presenter_media as media
    config=tmp_path/'empty-fontconfig.xml'
    config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig></fontconfig>')
    monkeypatch.setenv('FONTCONFIG_FILE',str(config))
    video=tmp_path/'font-test.mp4'
    media._encode(['-f','lavfi','-i','color=c=black:s=512x512:d=1',
                   '-f','lavfi','-i','sine=frequency=440:duration=1','-t','1',
                   '-c:v','libx264','-threads','1','-c:a','aac',str(video)])
    result, _=caption_presenter(video,[{'start':0,'end':1,'text':'Hello Genova.'}])
    frame=tmp_path/'caption.png'
    media._encode(['-ss','0.5','-i',str(result),'-frames:v','1',str(frame)])
    band=Image.open(frame).convert('RGB').crop((0,512,512,640))
    assert sum(1 for p in band.getdata() if min(p)>220)>100
