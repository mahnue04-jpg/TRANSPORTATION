"""Offline tests; no paid generation."""
import pytest
from app.core.nova.creative_studio import providers, flags, service as services
from app.core.nova.creative_studio.kling import FalKlingVideoProvider, MODEL
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore
TASK = {'request_id':'request-123','status_url':'https://queue.fal.run/fal-ai/kling-video/requests/request-123/status','response_url':'https://queue.fal.run/fal-ai/kling-video/requests/request-123'}
@pytest.fixture
def kling(monkeypatch):
    for key,value in {'NOVA_CREATIVE_VIDEO_PROVIDER':'kling','FAL_KEY':'test-only','NOVA_CREATIVE_VIDEO_LIVE_ENABLED':'true','NOVA_CREATIVE_KLING_LIVE_ENABLED':'true'}.items():
        monkeypatch.setenv(key,value)
    return FalKlingVideoProvider()

def test_provider_activation(monkeypatch):
    monkeypatch.delenv('NOVA_CREATIVE_VIDEO_PROVIDER',raising=False)
    assert isinstance(providers.video_provider(),providers.RunwayVideoProvider)
    monkeypatch.setenv('NOVA_CREATIVE_VIDEO_PROVIDER','kling')
    monkeypatch.setenv('RUNWAYML_API_SECRET','test-only')
    monkeypatch.delenv('FAL_KEY',raising=False)
    assert not flags.video_provider_configured()
    assert providers.video_provider().status().status=='CONFIG_REQUIRED'
    monkeypatch.setenv('FAL_KEY','test-only')
    monkeypatch.setenv('NOVA_CREATIVE_VIDEO_LIVE_ENABLED','true')
    monkeypatch.delenv('NOVA_CREATIVE_KLING_LIVE_ENABLED',raising=False)
    assert providers.video_provider().status().status=='DISABLED'

def test_submit_and_resume(kling,monkeypatch):
    calls=[]
    def request(method,url,*,payload=None):
        calls.append((method,url,payload))
        return TASK if method=='POST' else {'status':'COMPLETED'} if url.endswith('/status') else {'video':{'url':'https://fal.media/test.mp4'}}
    monkeypatch.setattr(kling,'_request_json',request)
    monkeypatch.setattr(kling,'_save_remote_video',lambda url:'/media/nova-creative/test.mp4')
    first=kling.generate(brief={'prompt_image_url':'data:image/png;base64,aGVsbG8=','prompt_text':'Envelope','persist_task_before_poll':True})
    assert first['status']=='PROCESSING' and len(calls)==1
    assert calls[0][1].endswith(MODEL) and calls[0][2]['duration']=='5'
    result=kling.generate(brief={'resume_task_id':first['task_id']})
    assert result['status']=='GENERATED' and result['asset_generated']
    assert result['provider']=='fal_kling_video'
    assert len([c for c in calls if c[0]=='POST'])==1

@pytest.mark.parametrize('failure',['poll','save'])
def test_recovery_preserves_task(kling,monkeypatch,failure):
    token=kling._encode_task(TASK)
    def request(method,url,**kw):
        if failure=='poll': raise RuntimeError('offline')
        return {'status':'COMPLETED'} if url.endswith('/status') else {'video':{'url':'https://fal.media/test.mp4'}}
    monkeypatch.setattr(kling,'_request_json',request)
    monkeypatch.setattr(kling,'_save_remote_video',lambda url: (_ for _ in ()).throw(RuntimeError('disk')))
    result=kling.generate(brief={'resume_task_id':token})
    assert result['status']=='PROCESSING' and result['task_id']==token

def test_provider_failure(kling,monkeypatch):
    monkeypatch.setattr(kling,'_request_json',lambda *a,**kw:{'status':'COMPLETED','error':'failure'})
    result=kling.generate(brief={'resume_task_id':kling._encode_task(TASK)})
    assert result['status']=='ERROR' and not result['asset_generated']

@pytest.mark.parametrize('url',['http://queue.fal.run/fal-ai/kling-video/requests/request-123/status','https://attacker.invalid/fal-ai/kling-video/requests/request-123/status'])
def test_validate_urls(kling,url):
    with pytest.raises(ValueError): kling._encode_task(dict(TASK,status_url=url))

def test_reject_foreign_task(kling,monkeypatch):
    monkeypatch.setattr(kling,'_request_json',lambda *a,**kw:pytest.fail('no network'))
    assert kling.generate(brief={'resume_task_id':'runway-id'})['status']=='ERROR'

def test_scene_preserves_old_pending_provider(kling,monkeypatch):
    svc=CreativeStudioService(CreativeStudioStore())
    p=svc.create_project('owner',{'title':'Hotel','project_type':'short_video'})
    svc.generate_storyboard('owner',p['id'])
    pending=svc._save_text_asset(owner_id='owner',project_id=p['id'],kind='video',title='Pending',content='',status='PROCESSING',metadata={'provider_result':{'status':'PROCESSING','task_id':'runway-id','brief':{'scene_index':1}}})
    monkeypatch.setattr(services,'video_provider',lambda:kling)
    monkeypatch.setattr(kling,'generate',lambda **kw:pytest.fail('no submission'))
    result=svc.request_video_generation('owner',p['id'])
    assert result['provider']['status']=='ERROR'
    assert any(a.id==pending.id and a.status=='PROCESSING' for a in svc.store.list_assets(p['id'],'owner'))
