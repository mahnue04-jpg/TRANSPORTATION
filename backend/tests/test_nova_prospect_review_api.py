from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from app.core.nova.work_revenue import prospect_review_api as api
from app.core.nova.work_revenue import prospect_research as research


@pytest.fixture
def harness(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_ENV','test');monkeypatch.setenv('AMICOR_ENVIRONMENT','test')
    monkeypatch.setenv('NOVA_PROSPECT_REVIEW_DEVELOPMENT_ENABLED','true')
    monkeypatch.setenv('NOVA_PROSPECT_REVIEW_DIRECTORY',str(tmp_path/'private'))
    app=FastAPI();app.include_router(api.router)
    # Synthetic authenticated identity for HTTP/ownership tests, NOT live sign-in proof.
    who={'org':'test-org','owner':'owner-a'}
    app.dependency_overrides[api.require_work_revenue_owner]=lambda:SimpleNamespace(organization_id=who['org'],user_id=who['owner'])
    return app,TestClient(app),who


def request():return {'request_key':'research-001','sources':[{'name':'Fixture','url':'https://example.com/contact'}]}
HEADERS={'X-Nova-Owner-Action':'review-public-prospect-sources'}


def test_http_job_replay_restart_ownership_and_download(harness,monkeypatch):
    app,client,who=harness;calls=[]
    def fetch(*args):
        calls.append(1);return b'public fixture','<p>Custom travel quote consultation</p>'
    monkeypatch.setattr(research,'fetch_source',fetch)
    first=client.post('/prospect-review/jobs',json=request(),headers=HEADERS)
    assert first.status_code==200
    data=first.json();job=data['job_id'];assert data['status']=='AWAITING_OWNER_REVIEW'
    again=client.post('/prospect-review/jobs',json=request(),headers=HEADERS)
    assert again.json()['replayed'] and len(calls)==1
    fresh=TestClient(app)
    assert fresh.get(f'/prospect-review/jobs/{job}').json()['owner_review']=='PENDING'
    out=fresh.get(f'/prospect-review/jobs/{job}/review.csv')
    assert out.status_code==200 and b'Fixture' in out.content
    prep=fresh.get(f'/prospect-review/jobs/{job}/preparation')
    assert prep.status_code==200 and prep.json()['drafts'][0]['can_send'] is False
    package=fresh.get(f'/prospect-review/jobs/{job}/work-package.zip')
    assert package.status_code==200 and package.content.startswith(b'PK')
    assert data['handoff']['status']=='HOLD_FOR_LAUNCH_AND_QUALIFICATION'
    who['owner']='owner-b'
    assert client.get(f'/prospect-review/jobs/{job}').status_code==404
    assert client.get(f'/prospect-review/jobs/{job}/review.csv').status_code==404
    assert client.get(f'/prospect-review/jobs/{job}/work-package.zip').status_code==404


def test_production_and_missing_action_are_blocked(harness,monkeypatch):
    _,client,_=harness
    assert client.post('/prospect-review/jobs',json=request()).status_code==403
    monkeypatch.setenv('APP_ENV','production')
    assert client.post('/prospect-review/jobs',json=request(),headers=HEADERS).status_code==503


def test_actual_owner_dependency_required(harness):
    app,client,_=harness
    def denied():raise HTTPException(401,'Sign in required')
    app.dependency_overrides[api.require_work_revenue_owner]=denied
    assert client.post('/prospect-review/jobs',json=request(),headers=HEADERS).status_code==401


def test_no_source_failure_fabricates_success(harness,monkeypatch):
    _,client,_=harness
    monkeypatch.setattr(research,'fetch_source',lambda *a:(_ for _ in ()).throw(ValueError('blocked')))
    result=client.post('/prospect-review/jobs',json=request(),headers=HEADERS).json()
    assert result['status']=='NO_SOURCE_RECORDS' and result['operations']['output_rows']==0
    assert len(result['source_failures'])==1 and result['outreach_sent']==0


def test_credentials_in_source_url_are_rejected_before_storage(harness):
    _,client,_=harness
    body=request();body['sources'][0]['url']='https://user:secret@example.com'
    assert client.post('/prospect-review/jobs',json=body,headers=HEADERS).status_code==422


def test_search_provider_failure_does_not_create_ready_job(harness,monkeypatch):
    _,client,_=harness
    def failed(*a,**k):raise api.SearchUnavailable('Search unavailable')
    monkeypatch.setattr(api,'run_discovery',failed)
    body={'request_key':'discovery-001','query':'travel agencies Minnesota'}
    assert client.post('/prospect-review/discover',json=body,headers={'X-Nova-Owner-Action':'discover-public-business-candidates'}).status_code==503


def test_saved_list_survives_client_reset_and_excludes_other_owner_and_corruption(harness,monkeypatch):
    app,client,who=harness
    monkeypatch.setattr(research,'fetch_source',lambda *a:(b'fixture','<p>Custom travel consultation</p>'))
    job=client.post('/prospect-review/jobs',json=request(),headers=HEADERS).json()['job_id']
    fresh=TestClient(app)
    listing=fresh.get('/prospect-review/jobs')
    assert listing.status_code==200 and listing.json()['jobs'][0]['job_id']==job
    assert listing.json()['jobs'][0]['owner_review']=='PENDING'
    who['owner']='other-owner'
    assert fresh.get('/prospect-review/jobs').json()['jobs']==[]
    who['owner']='owner-a'
    directory,_=api.saved_job(SimpleNamespace(organization_id='test-org',user_id='owner-a'),job)
    (directory/'operations-review.csv').write_text('corrupt')
    result=fresh.get('/prospect-review/jobs').json()
    assert result['jobs']==[] and result['unavailable_count']==1
