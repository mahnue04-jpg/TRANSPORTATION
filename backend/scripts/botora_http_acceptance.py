"""Isolated API acceptance with public data and an explicit synthetic auth identity.

Never accesses the hosted runtime, an application database, paid services, or
real credentials. Authentication overrides are confined to this script.
"""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.nova.work_revenue import prospect_review_api as api

p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--sources');p.add_argument('--query');p.add_argument('--resume',action='store_true');args=p.parse_args()
directory=Path(args.directory).resolve();directory.mkdir(mode=0o700,parents=True,exist_ok=True)
os.environ['APP_ENV']='test';os.environ['AMICOR_ENVIRONMENT']='test'
os.environ['NOVA_PROSPECT_REVIEW_DEVELOPMENT_ENABLED']='true'
os.environ['NOVA_PROSPECT_REVIEW_DIRECTORY']=str(directory/'private-jobs')
app=FastAPI();app.include_router(api.router)
app.dependency_overrides[api.require_work_revenue_owner]=lambda:SimpleNamespace(organization_id='isolated-botora-acceptance',user_id='synthetic-owner')
with TestClient(app) as client:
    if args.resume:
        saved=json.loads((directory/'acceptance.json').read_text());job=saved['job_id']
    else:
        if args.query:
            body={'request_key':'botora-search-api-acceptance-1113','query':args.query,'limit':4}
            path='/prospect-review/discover';action='discover-public-business-candidates'
        else:
            sources=json.loads(Path(args.sources).read_text())
            body={'request_key':'botora-public-api-acceptance-1113','sources':sources}
            path='/prospect-review/jobs';action='review-public-prospect-sources'
        r=client.post(path,json=body,headers={'X-Nova-Owner-Action':action})
        assert r.status_code==200,r.text
        saved=r.json();job=saved['job_id']
        replay=client.post(path,json=body,headers={'X-Nova-Owner-Action':action})
        assert replay.status_code==200 and replay.json()['replayed']
    status=client.get('/prospect-review/jobs/'+job);assert status.status_code==200,status.text
    csv=client.get('/prospect-review/jobs/'+job+'/review.csv');assert csv.status_code==200,csv.text
    (directory/'operations-api-review.csv').write_bytes(csv.content)
    result={**status.json(),'authentication_evidence':'SYNTHETIC_DEPENDENCY_OVERRIDE_NOT_LIVE_AUTH',
            'transport':'IN_PROCESS_FASTAPI_HTTP_ACCEPTANCE_NOT_HOSTED',
            'fresh_process_retrieval_verified':args.resume,'download_status':csv.status_code}
    (directory/'acceptance.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result[k] for k in ['job_id','status','authentication_evidence','transport','fresh_process_retrieval_verified','download_status']}))
    print(json.dumps({'records':len(result['records']),'source_failures':result['source_failures'],'outreach_sent':result['outreach_sent']}))
