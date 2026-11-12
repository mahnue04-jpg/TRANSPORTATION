"""Application-level checks. Run under backend pytest with providers disabled."""
import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
from app.core.nova.creative_studio.store import CreativeStudioStore

SCRIPT = 'One apple. Add one more. Now there are two. Add one more apple. Count one, two, three! Great counting!'

@pytest.fixture
def studio(tmp_path, monkeypatch):
    service_module = importlib.import_module('app.core.nova.creative_studio.service')
    providers = importlib.import_module('app.core.nova.creative_studio.providers')
    def forbidden(*a, **kw): raise AssertionError('No provider may be called')
    for name in ['image_provider', 'voice_provider', 'video_provider']:
        monkeypatch.setattr(service_module, name, forbidden)
    root = lambda: (tmp_path, '/media/test')
    resolve = lambda url: tmp_path / Path(url).name if url else None
    for module in [service_module, providers]:
        monkeypatch.setattr(module, '_creative_media_root_and_prefix', root)
        monkeypatch.setattr(module, '_resolve_creative_media_url', resolve)
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project('owner', {'title':'Count to three','project_type':'explainer',
        'platform':'YouTube','audience':'Children ages 4–6','duration_target':30})
    return service, project['id']


def test_explainer_all_planners_keep_saved_narration(studio):
    service, pid = studio
    for name in ['generate_script','generate_caption','generate_storyboard','generate_image_prompt']:
        with pytest.raises(CreativeStudioError, match='Save the exact lesson narration'):
            getattr(service, name)('owner', pid)
    service._save_text_asset(owner_id='owner', project_id=pid, kind='presenter_script',
        title='Reviewed lesson', content=SCRIPT)
    pack=service.generate_script('owner',pid)['pack']
    assert pack['voiceover_script']==SCRIPT
    story=service.generate_storyboard('owner',pid)['assembly']
    assert ' '.join(s['voiceover_text'] for s in story['scenes'])==SCRIPT
    assert len(story['scenes'])==6
    assert sum(s['duration_seconds'] for s in story['scenes'])==pytest.approx(30)
    assert not story['timing_verified']
    assert 'getamicor.com' not in str(service.generate_caption('owner',pid))
    assert 'busywork' not in str(service.generate_image_prompt('owner',pid)).lower()


def test_authenticated_mp4_upload_and_download_roundtrip(studio, tmp_path, monkeypatch):
    service, pid=studio
    router_module=importlib.import_module('app.core.nova.creative_studio.router')
    app=FastAPI(); app.include_router(router_module.router)
    monkeypatch.setattr(router_module,'get_service',lambda db:service)
    user=SimpleNamespace(user_id='owner', email='studio-test@example.invalid')
    app.dependency_overrides[router_module.get_current_user_context]=lambda:user
    app.dependency_overrides[router_module.require_nova_access]=lambda:None
    app.dependency_overrides[router_module.get_db]=lambda:None
    clip=tmp_path/'fixture.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:s=160x160:r=10',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=24000','-t','0.5','-threads','1',
        '-c:v','libx264','-c:a','aac',str(clip)],check=True)
    data=clip.read_bytes(); client=TestClient(app)
    url='/api/nova/creative/projects/'+pid+'/finished-video-upload'
    response=client.post(url,files={'file':('../../unsafe.mp4',data,'video/mp4')})
    assert response.status_code==200,response.text
    result=response.json(); asset=result['asset']
    assert not result['paid_request_submitted']
    assert not asset['metadata']['publish_ready']
    download=client.get('/api/nova/creative/projects/'+pid+'/assets/'+asset['id']+'/file')
    assert download.status_code==200
    assert download.content==data
    duplicate=client.post(url,files={'file':('again.mp4',data,'video/mp4')})
    assert duplicate.json()['reused']
    assert duplicate.json()['asset']['id']==asset['id']
    assert client.post(url,files={'file':('broken.mp4',b'broken','video/mp4')}).status_code==422
    user.user_id='other'
    assert client.get('/api/nova/creative/projects/'+pid+'/assets/'+asset['id']+'/file').status_code==404
    assert client.post(url,files={'file':('other.mp4',data,'video/mp4')}).status_code==404
    app.dependency_overrides.pop(router_module.get_current_user_context)
    assert client.post(url,files={'file':('unauth.mp4',data,'video/mp4')}).status_code in {401,403}
