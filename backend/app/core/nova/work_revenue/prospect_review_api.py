"""Development-only owner research/review API; no production storage or outreach."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlsplit

from app.auth import UserContext
from .owner_auth import require_work_revenue_owner
from .prospect_research import run_assignment, verify_saved_run
from .prospect_discovery import run_discovery, SearchUnavailable
from .operations_prospect_package import build_package, prepare_queue

router = APIRouter(prefix="/prospect-review",tags=["nova-prospect-review-development"],
                   dependencies=[Depends(require_work_revenue_owner)])


class Source(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    url: str = Field(min_length=10,max_length=2000)

    @field_validator('url')
    @classmethod
    def public_https_shape(cls,value):
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Use an official HTTPS source URL without credentials')
        return value


class Assignment(BaseModel):
    request_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    sources: list[Source] = Field(min_length=1,max_length=25)


class DiscoveryAssignment(BaseModel):
    request_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    query: str = Field(min_length=10,max_length=300)
    limit: int = Field(default=5,ge=1,le=10)
    exclude_domains: list[str] = Field(default_factory=list,max_length=500)


def owner_root(owner):
    # Reject production even if the development flag is accidentally set.
    envs=[os.getenv('APP_ENV','').lower(),os.getenv('AMICOR_ENVIRONMENT','').lower()]
    if 'production' in envs or not any(e in {'development','test'} for e in envs):
        raise HTTPException(503,'Prospect review is available only in isolated development')
    if os.getenv('NOVA_PROSPECT_REVIEW_DEVELOPMENT_ENABLED')!='true':
        raise HTTPException(503,'Development prospect review is disabled')
    org=str(getattr(owner,'organization_id','') or '').strip()
    uid=str(getattr(owner,'user_id','') or '').strip()
    if not org or org.lower()=='global' or not uid:
        raise HTTPException(403,'Specific owner and organization required')
    configured=os.getenv('NOVA_PROSPECT_REVIEW_DIRECTORY','')
    root=Path(configured)
    if not configured or not root.is_absolute():
        raise HTTPException(503,'Private development output directory is not configured')
    root.mkdir(parents=True,mode=0o700,exist_ok=True)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise HTTPException(503,'Development output directory must be private')
    key=hashlib.sha256(json.dumps([org,uid]).encode()).hexdigest()
    bucket=root/key
    bucket.mkdir(mode=0o700,exist_ok=True)
    if bucket.is_symlink() or bucket.stat().st_mode & 0o077:
        raise HTTPException(503,'Owner output directory must be private')
    return bucket


def saved_job(owner,job_id):
    if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise HTTPException(404,'Research job not found')
    directory=owner_root(owner)/job_id
    if directory.is_symlink():raise HTTPException(404,'Research job not found')
    if not (directory/'manifest.json').is_file():raise HTTPException(404,'Research job not found')
    try:verify_saved_run(directory)
    except (ValueError,KeyError,OSError):raise HTTPException(409,'Saved evidence integrity check failed')
    return directory,json.loads((directory/'manifest.json').read_text())


def view(job_id,m,replayed=False):
    return {'job_id':job_id,'status':'AWAITING_OWNER_REVIEW' if m['source_count'] else 'NO_SOURCE_RECORDS',
            'replayed':replayed,'independent_discovery':m.get('independent_business_discovery',False),'owner_review':'PENDING','outreach_sent':0,
            'records':m['records'],'source_failures':m['failures'],'operations':m['operations'],
            'summary':{'retrieved_sources':len(m['records']),
                       'workflow_candidates':sum(r.get('status')=='WORKFLOW_FIT_REQUIRES_QUALIFICATION' for r in m['records']),
                       'insufficient_evidence':sum(r.get('status')=='INSUFFICIENT_EVIDENCE' for r in m['records']),
                       'source_failures':len(m['failures']),'confirmed_interested_buyers':0},
            'handoff':{'status':'HOLD_FOR_LAUNCH_AND_QUALIFICATION',
                       'required':['Signed Botora agreement','Owner launch authorization','Approved campaign material',
                                   'Verified need, buyer, budget and timing','Prospect permission for introduction']}}


@router.get('/readiness')
def readiness(owner:UserContext=Depends(require_work_revenue_owner)):
    owner_root(owner)
    return {'enabled':True,'execution':'ISOLATED_DEVELOPMENT','independent_discovery':True,'search_provider':'duckduckgo-html'}


@router.post('/discover')
def discover_job(body:DiscoveryAssignment,owner:UserContext=Depends(require_work_revenue_owner),
                 action:str|None=Header(default=None,alias='X-Nova-Owner-Action')):
    bucket=owner_root(owner)
    if action!='discover-public-business-candidates':raise HTTPException(403,'Explicit business search action required')
    job_id=hashlib.sha256(json.dumps(['discovery',body.model_dump()],sort_keys=True).encode()).hexdigest()[:32]
    directory=bucket/job_id
    if directory.exists():
        if not (directory/'manifest.json').exists():raise HTTPException(409,'Research job is still running or interrupted')
        _,m=saved_job(owner,job_id);return view(job_id,m,True)
    excluded=set(body.exclude_domains)
    # Compare with this owner's actual saved rows; never invent the missing historic list.
    for file in list(bucket.glob('*/manifest.json'))[:2000]:
        try:
            existing=json.loads(file.read_text())
            excluded.update(r['domain'] for r in existing.get('records',[]) if r.get('domain'))
        except (OSError,ValueError,KeyError):continue
    try:m=run_discovery(body.query,directory,limit=body.limit,exclude_domains=sorted(excluded))
    except SearchUnavailable as exc:raise HTTPException(503,str(exc)) from exc
    except FileExistsError:raise HTTPException(409,'Research job already started')
    return view(job_id,m)


@router.post('/jobs')
def create_job(body:Assignment,owner:UserContext=Depends(require_work_revenue_owner),
               action:str|None=Header(default=None,alias='X-Nova-Owner-Action')):
    bucket=owner_root(owner)
    if action!='review-public-prospect-sources':raise HTTPException(403,'Explicit research action required')
    seeds=[s.model_dump() for s in body.sources]
    # Request identity includes content: a changed source list creates separate work.
    job_id=hashlib.sha256(json.dumps([body.request_key,seeds],sort_keys=True).encode()).hexdigest()[:32]
    directory=bucket/job_id
    if directory.exists():
        if not (directory/'manifest.json').exists():raise HTTPException(409,'Research job is still running or interrupted; inspect before retry')
        _,m=saved_job(owner,job_id)
        return view(job_id,m,True)
    try:m=run_assignment(seeds,directory)
    except FileExistsError:raise HTTPException(409,'Research job already started')
    return view(job_id,m)


@router.get('/jobs')
def list_saved_jobs(owner:UserContext=Depends(require_work_revenue_owner)):
    bucket=owner_root(owner)
    jobs=[];unavailable=0
    for directory in sorted(bucket.iterdir(),key=lambda p:p.name)[:2000]:
        if not re.fullmatch(r'[a-f0-9]{32}',directory.name):continue
        try:
            _,manifest=saved_job(owner,directory.name)
            jobs.append({'job_id':directory.name,'record_count':len(manifest['records']),
                         'businesses':[r['business'] for r in manifest['records'][:3]],
                         'owner_review':'PENDING','outreach_sent':0})
        except HTTPException:
            unavailable+=1
        if len(jobs)>=100:break
    return {'jobs':jobs,'unavailable_count':unavailable,'limit':100,
            'storage':'ISOLATED_LOCAL_FILES_NOT_VERIFIED_HOSTED_STORAGE'}


@router.get('/jobs/{job_id}')
def get_job(job_id:str,owner:UserContext=Depends(require_work_revenue_owner)):
    _,m=saved_job(owner,job_id)
    return view(job_id,m)


@router.get('/jobs/{job_id}/review.csv')
def download_job(job_id:str,owner:UserContext=Depends(require_work_revenue_owner)):
    directory,_=saved_job(owner,job_id)
    return Response((directory/'operations-review.csv').read_bytes(),media_type='text/csv',
                    headers={'Content-Disposition':'attachment; filename="nova-prospect-review.csv"','Cache-Control':'no-store'})


@router.get('/jobs/{job_id}/preparation')
def preparation(job_id:str,owner:UserContext=Depends(require_work_revenue_owner)):
    _,manifest=saved_job(owner,job_id)
    return prepare_queue(manifest)


@router.get('/jobs/{job_id}/work-package.zip')
def work_package(job_id:str,owner:UserContext=Depends(require_work_revenue_owner)):
    import tempfile
    directory,_=saved_job(owner,job_id)
    with tempfile.TemporaryDirectory(prefix='review-package-',dir=directory) as temp:
        target=Path(temp)/'review-package.zip'
        build_package(directory,target)
        raw=target.read_bytes()
    return Response(raw,media_type='application/zip',headers={
        'Content-Disposition':'attachment; filename="nova-supervised-work-package.zip"','Cache-Control':'no-store'})
