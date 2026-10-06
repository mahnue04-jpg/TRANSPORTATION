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
    ass=video.with_suffix('.ass').read_text()
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
