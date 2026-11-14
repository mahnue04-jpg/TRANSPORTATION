"""Bounded public search followed by primary-page screening; no outreach.

Search results and snippets are discovery pointers, never buying-intent proof.
No paid-provider fallback or challenge bypass is performed.
"""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlencode,urlsplit,parse_qs
from urllib.request import Request,build_opener
from .prospect_research import NoRedirect,run_assignment,_private_write

class SearchUnavailable(RuntimeError):pass

class SearchLinks(HTMLParser):
    def __init__(self):
        super().__init__();self.link=None;self.text=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and 'result__a' in a.get('class','').split():
            self.link=a.get('href');self.text=[]
    def handle_data(self,data):
        if self.link is not None:self.text.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.link is not None:
            self.rows.append({'title':' '.join(' '.join(self.text).split()),'url':html.unescape(self.link)})
            self.link=None

EXCLUDED_HOSTS={'facebook.com','instagram.com','linkedin.com','yelp.com','tripadvisor.com',
                'duckduckgo.com','google.com','bing.com','wikipedia.org','youtube.com'}

def parse_candidates(markup,*,limit,exclude_domains):
    if re.search(r'anomaly\.js|anomaly-modal|g-recaptcha|verify you are human',markup,re.I):
        raise SearchUnavailable('Search provider requested verification; stopped without bypass')
    p=SearchLinks();p.feed(markup);out=[];seen=set(exclude_domains)|EXCLUDED_HOSTS
    for row in p.rows:
        u=row['url'];parsed=urlsplit(u if not u.startswith('//') else 'https:'+u)
        if (parsed.hostname or '').endswith('duckduckgo.com'):
            u=parse_qs(parsed.query).get('uddg',[''])[0];parsed=urlsplit(u)
        host=(parsed.hostname or '').lower().removeprefix('www.')
        if parsed.scheme!='https' or not host or parsed.username or parsed.password:continue
        if any(host==h or host.endswith('.'+h) for h in seen):continue
        # Directory listings are not individual prospective buyers.
        if re.search(r'/travel-agents/by/|/directory/|/best-\d+',parsed.path,re.I):continue
        title=row['title'];parts=re.split(r'\s*[|—]\s*',title)
        label=parts[1] if len(parts)>1 and re.match(r'^contact',parts[0],re.I) else parts[0]
        label=re.sub(r'^(?:contact(?: us)?|travel consulting)\s*[-:]\s*','',label,flags=re.I)
        out.append({'name':label[:120] or host,'url':u,'search_title':title})
        seen.add(host)
        if len(out)>=limit:break
    return out

def search_businesses(query,*,limit=8,exclude_domains=()):
    query=str(query).strip()
    if not 10<=len(query)<=300 or not 1<=limit<=10:raise ValueError('Use a specific public business query and limit 1–10')
    # No profile, email, company documents or owner facts are sent in this query.
    url='https://html.duckduckgo.com/html/?'+urlencode({'q':query})
    req=Request(url,headers={'User-Agent':'AMICOR-Nova-Research/0.1 (read-only)'})
    try:
        with build_opener(NoRedirect()).open(req,timeout=15) as response:
            raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise SearchUnavailable('Search response exceeded limit')
    except SearchUnavailable:raise
    except Exception as exc:raise SearchUnavailable('Search provider unavailable; no fallback attempted') from exc
    candidates=parse_candidates(raw.decode('utf-8',errors='replace'),limit=limit,
                                exclude_domains={str(h).lower().removeprefix('www.') for h in exclude_domains})
    if not candidates:raise SearchUnavailable('Search returned no usable business source pages')
    return candidates

def run_discovery(query,output_dir,*,limit=8,exclude_domains=()):
    candidates=search_businesses(query,limit=limit,exclude_domains=exclude_domains)
    manifest=run_assignment([{'name':c['name'],'url':c['url']} for c in candidates],output_dir)
    manifest['input']='NOVA_PUBLIC_BUSINESS_SEARCH'
    manifest['independent_business_discovery']=True
    manifest['discovery']={'provider':'duckduckgo-html','query':query,'candidates_found':len(candidates),
                           'candidates':candidates,'excluded_domains':list(exclude_domains),
                           'search_titles_are_provisional':True,'historical_139_overlap':'UNKNOWN'}
    # The source-review manifest exists already; replace it atomically, retaining mode.
    from pathlib import Path
    root=Path(output_dir);temporary=root/'manifest.discovery.tmp'
    _private_write(temporary,json.dumps(manifest,indent=2).encode())
    temporary.replace(root/'manifest.json')
    return manifest
