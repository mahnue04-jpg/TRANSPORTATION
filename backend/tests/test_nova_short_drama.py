"""Dialogue correctness and real FFmpeg assembly; never call paid providers."""
from copy import deepcopy
from types import SimpleNamespace
import subprocess
import math
from array import array
import wave
import pytest
from app.core.nova.creative_studio.drama import SAMPLE, parse_plan, srt_time
from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
from app.core.nova.creative_studio.store import CreativeStudioStore

@pytest.fixture
def drama():
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project('owner', {'title':'The Envelope', 'project_type':'short_drama', 'platform':'TikTok', 'duration_target':30})
    service.save_drama_plan('owner', project['id'], deepcopy(SAMPLE))
    return service, project['id']

@pytest.mark.parametrize('change', ['unknown_speaker','same_voice','same_name','one_speaker'])
def test_rejects_ambiguous_dialogue(change):
    payload = deepcopy(SAMPLE)
    if change == 'unknown_speaker': payload['dialogue'] = 'Stranger: Hello\nMaya: Hi'
    if change == 'same_voice': payload['characters'][1]['voice'] = payload['characters'][0]['voice']
    if change == 'same_name': payload['characters'][1]['name'] = payload['characters'][0]['name']
    if change == 'one_speaker': payload['dialogue'] = 'Maya: Hello\nMaya: Hi'
    with pytest.raises(CreativeStudioError): parse_plan(payload)


def test_plan_tenant_and_protection(drama):
    service, pid = drama
    with pytest.raises(CreativeStudioError): service.save_drama_plan('other', pid, SAMPLE)
    detail = service.get_project('owner', pid)
    assert [r['subtitle_text'] for r in detail['scenes']] == SAMPLE['dialogue'].splitlines()
    assert len(service.save_drama_plan('owner', pid, SAMPLE)['scenes']) == 6
    for generator in [service.generate_script, service.generate_storyboard]:
        with pytest.raises(CreativeStudioError): generator('owner', pid)
    service._save_text_asset(owner_id='owner', project_id=pid, kind='audio', title='started', content='', status='ERROR')
    changed = deepcopy(SAMPLE); changed['setting'] = 'Another lobby'
    with pytest.raises(CreativeStudioError): service.save_drama_plan('owner', pid, changed)


def test_distinct_voices_resume_and_failure(drama, monkeypatch, tmp_path):
    import app.core.nova.creative_studio.drama as module
    service, pid = drama
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 3: return {'asset_generated':False, 'message':'Provider disabled'}
        path = tmp_path / f'{len(calls)}.mp3'; path.write_bytes(b'fake audio test fixture')
        return {'asset_generated':True, 'url':str(path)}
    monkeypatch.setattr(module, 'voice_provider', lambda: SimpleNamespace(generate=generate))
    monkeypatch.setattr(module, '_resolve_creative_media_url', lambda url: __import__('pathlib').Path(url) if url else None)
    with pytest.raises(CreativeStudioError): service.generate_drama_voices('owner', pid)
    assert [r['voice'] for r in calls[:2]] == ['onyx','nova']
    assert service.store.list_jobs(pid,'owner')[-1].status == 'ERROR'
    result = service.generate_drama_voices('owner', pid)
    assert result['status'] == 'GENERATED'
    assert len(calls) == 7  # completed first two lines reused, failed third retried
    assert len([a for a in service.store.list_assets(pid,'owner') if a.kind=='audio']) == 6


def test_missing_media_is_not_completed_video(drama):
    service, pid = drama
    with pytest.raises(CreativeStudioError): service.assemble_drama('owner', pid)
    assert service.store.list_jobs(pid,'owner')[-1].status == 'ERROR'
    assert not any(a.kind=='video' and a.url for a in service.store.list_assets(pid,'owner'))


def test_real_ffmpeg_dialogue_order_captions_and_duration(monkeypatch, tmp_path):
    import imageio_ffmpeg
    import app.core.nova.creative_studio.drama as module
    from pathlib import Path
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project('owner', {'title':'Test render', 'project_type':'short_drama', 'platform':'TikTok'})
    pid = project['id']; payload=deepcopy(SAMPLE)
    payload['dialogue'] = 'Eli: Hello.\nMaya: Welcome.'
    service.save_drama_plan('owner', pid, payload)
    plan = service._drama_plan('owner',pid)[1]
    monkeypatch.setattr(module, '_resolve_creative_media_url', lambda url: Path(url) if url else None)
    monkeypatch.setattr(module, '_creative_media_root_and_prefix', lambda: (tmp_path, '/media/test'))
    clip = tmp_path/'clip.mp4'
    subprocess.run([ffmpeg,'-y','-f','lavfi','-i','color=blue:s=180x320:r=25','-t','0.4','-c:v','libx264',str(clip)],check=True,capture_output=True)
    for i in [1,2]:
        audio = tmp_path/f'{i}.wav'
        with wave.open(str(audio),'w') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000); out.writeframes(array('h', (int(8000 * math.sin(2 * math.pi * 440 * n / 24000)) for n in range(12000*i))).tobytes())
        service._save_text_asset(owner_id='owner',project_id=pid,kind='audio',title='test',content='',url=str(audio),metadata={'drama_revision':plan['revision'],'line_index':i})
        service._save_text_asset(owner_id='owner',project_id=pid,kind='video',title='test',content='',url=str(clip),metadata={'provider_result':{'provider':'runway_video','brief':{'scene_index':i}}})
    result = service.assemble_drama('owner', pid)
    meta = result['asset']['metadata']
    assert [r['speaker'] for r in meta['timeline']] == ['Eli','Maya']
    assert meta['timeline'][1]['start'] == pytest.approx(0.75)
    assert meta['duration_seconds'] == pytest.approx(2.0)
    assert meta['captions_burned_in'] and not meta['lip_sync_verified'] and not meta['publish_ready']
    rendered = list(tmp_path.glob('nova-drama-*.mp4'))[0]
    assert rendered.stat().st_size > 1024
    decoded = subprocess.run([ffmpeg, '-v', 'error', '-i', str(rendered), '-vn', '-f', 's16le', '-ac', '1', '-ar', '24000', '-'], check=True, capture_output=True).stdout
    samples = array('h'); samples.frombytes(decoded)
    assert max(abs(sample) for sample in samples) > 1000  # audible audio is muxed into the video
    assert '00:00:00,750 --> 00:00:02,000' in list(tmp_path.glob('*.srt'))[0].read_text()
    assert srt_time(61.025) == '00:01:01,025'


def test_http_plan_roundtrip_and_persisted_jobs(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
    from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
    from app.db.session import engine
    import importlib
    router = importlib.import_module("app.core.nova.creative_studio.router")
    ensure_auth_schema(); seed_default_users(); ensure_nova_creative_schema(engine)
    monkeypatch.setattr(router, '_run_drama_background', lambda *args: None)
    client = TestClient(app)
    login = client.post('/api/auth/login', json={'email':'dispatcher@amicor.local','password':SEED_PASSWORD})
    headers = {'Authorization': 'Bearer '+login.json()['access_token']}
    root='/api/nova/creative'
    project=client.post(root+'/projects',headers=headers,json={'title':'HTTP drama','project_type':'short_drama'}).json()
    path=root+'/projects/'+project['id']
    assert client.post(path+'/drama/plan',headers=headers,json=SAMPLE).status_code == 200
    assert client.post(path+'/drama/plan',json=SAMPLE).status_code in {401,403}
    assert client.post(path+'/drama/unknown',headers=headers).status_code == 404
    result=client.post(path+'/drama/voices',headers=headers).json()
    assert result['status']=='PROCESSING'
    job_id=result['job']['id']
    jobs=client.get(path,headers=headers).json()['jobs']
    assert next(row for row in jobs if row['id']==job_id)['status']=='QUEUED'
    router._drama_workers.discard(job_id)


def test_drama_controls_exist_in_page():
    from pathlib import Path
    import re
    root=Path(__file__).resolve().parents[1]/'static'/'nova-creative'
    html=(root/'index.html').read_text()
    script=(root/'creative.js').read_text()
    ids=set(re.findall(r'id="([^"]+)"',html))
    used=set(re.findall(r'\$\("(drama-[^"]+)"\)',script))
    assert used - {'drama-name-', 'drama-description-', 'drama-voice-', 'drama-'} <= ids
    assert {'drama-plan','drama-motion','drama-voices','drama-render'} <= ids


def test_drama_captions_use_saved_story_instead_of_marketing_template(drama, monkeypatch):
    import app.core.nova.creative_studio.service as module
    service, pid = drama
    monkeypatch.setattr(module, 'generate_content_pack', lambda **kwargs: pytest.fail('Drama must not use marketing template'))
    result = service.generate_caption('owner', pid)
    assert result['job']['status'] == 'GENERATED'
    assert SAMPLE['setting'] in result['pack']['long_caption']
    assert SAMPLE['dialogue'].splitlines()[0] in result['pack']['short_caption']
    assert 'AI assistant' not in result['pack']['long_caption']
    assert '#Suspense' in result['pack']['hashtags']
    assert '#BusinessProductivity' not in result['pack']['hashtags']
    assert 'voiceover_script' not in result['pack'] and 'image_prompt' not in result['pack']
    assert all(asset['metadata']['short_drama'] for asset in result['assets'])
    assert len(service.store.list_scenes(pid, 'owner')) == 6
    with pytest.raises(CreativeStudioError): service.generate_caption('other', pid)
