from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'runtime'/'python'/'python.exe'

def free_port():
 with socket.socket() as value:value.bind(('127.0.0.1',0));return value.getsockname()[1]

def request(port,token,path,method='GET',body=None):
 data=json.dumps(body).encode() if body is not None else None
 req=Request(f'http://127.0.0.1:{port}{path}',data=data,method=method,headers={'X-Vibe-Session-Token':token,'Content-Type':'application/json'})
 try:
  with urlopen(req,timeout=20) as response:return response.status,json.loads(response.read())
 except HTTPError as error:return error.code,json.loads(error.read())

def server(port,token,appdata):
 env={**os.environ,'PYTHONPATH':str(ROOT/'backend'),'VIBE_LOCAL_SESSION_TOKEN':token,'VIBE_DESKTOP':'1','VIBE_RUNTIME_ROOT':str(ROOT/'runtime'),'APPDATA':str(appdata),'API_PORT':str(port),'PYTHONUTF8':'1'}
 process=subprocess.Popen([str(PYTHON),'-m','uvicorn','main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],cwd=ROOT/'backend',env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 for _ in range(60):
  try:
   if request(port,token,'/api/health')[0]==200:return process
  except Exception:time.sleep(.1)
 process.kill();raise AssertionError('backend failed to start')

def stop(process):
 process.terminate()
 try:process.wait(10)
 except subprocess.TimeoutExpired:process.kill()

def test_http_golden_path_persists_across_process_restart(tmp_path,monkeypatch):
 # Real HTTP process for persistence/API boundaries; integrity-hashed provider cache avoids network flakiness.
 token='golden-http-token';port=free_port();appdata=tmp_path/'appdata';process=server(port,token,appdata)
 try:
  status,project=request(port,token,'/api/research-projects','POST',{'title':'HTTP project','research_question':'Does open science improve reproducibility?','inclusion_criteria':'peer reviewed'})
  assert status==200
  cache=appdata/'VibeResearch'/'workspaces'/'literature-cache';cache.mkdir(parents=True,exist_ok=True);query='open science';provider='openalex'
  records=[{'title':'Open science evidence','authors':['A Author'],'year':2024,'doi':'10.1234/http','url':'https://doi.org/10.1234/http'}]
  raw=json.dumps(records,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();envelope={'provider':provider,'query':query,'retrieved_at':'2026-01-01T00:00:00Z','records':records,'content_sha256':hashlib.sha256(raw).hexdigest()}
  cache_file=cache/f'{provider}-{hashlib.sha256(query.encode()).hexdigest()}.json'
  cache_file.write_text(json.dumps(envelope),encoding='utf-8')
  snapshot_sha256=hashlib.sha256(cache_file.read_bytes()).hexdigest()
  status,saved=request(port,token,f"/api/research-projects/{project['id']}/evidence-cards",'POST',{'provider':provider,'query':query,'source_url':records[0]['url'],'snapshot_sha256':snapshot_sha256})
  assert status==200,saved;card=saved['evidence_cards'][0]
  assert request(port,token,f"/api/research-projects/{project['id']}/draft",'POST')[0]==409
  assert request(port,token,f"/api/research-projects/{project['id']}/evidence-cards/{card['id']}/review",'POST',{'actor':'researcher','decision':'approved','reason':'metadata checked'})[0]==200
  assert request(port,token,f"/api/research-projects/{project['id']}/draft",'POST')[0]==409
  assert request(port,token,f"/api/research-projects/{project['id']}/evidence-cards/{card['id']}/claim-support",'POST',{'actor':'researcher','decision':'approved','reason':'full text supports claim'})[0]==200
  narrative={'question':project['research_question'],'tension':'Prior findings conflict','mechanism':'Open practices change verification conditions','hypotheses':['H1 predicts improved reproducibility'],'claims':['C1'],'competing_explanations':['selection into open practices'],'boundaries':['publicly observable projects'],'limitations':['metadata cannot measure every practice']}
  assert request(port,token,f"/api/research-projects/{project['id']}/narrative",'PUT',narrative)[0]==200
  assert request(port,token,f"/api/research-projects/{project['id']}/narrative/approve",'POST',{'actor':'researcher'})[0]==200
  status,graph=request(port,token,f"/api/research-projects/{project['id']}/claim-evidence-links",'POST',{'claim_id':'C1','evidence_card_id':card['id'],'relation':'supports','passage':'Open practices improve verification conditions.','locator':'p.1'})
  assert status==200,graph
  link_id=graph['links'][0]['id']
  status,graph=request(port,token,f"/api/research-projects/{project['id']}/claim-evidence-links/{link_id}/review",'POST',{'actor':'researcher','decision':'approved','reason':'passage supports claim'})
  assert status==200 and graph['gate']['passed'] is True
  status,project_with_hypothesis=request(port,token,f"/api/research-projects/{project['id']}/hypotheses",'POST',{
   'statement':'Open science improves reproducibility under public verification',
   'mechanism':'Open practices change verification conditions',
   'prediction':'Public projects show higher replication success',
   'falsification_criteria':'No improvement after three independent replications',
   'boundary_conditions':'publicly observable projects only',
   'actor':'researcher',
   'change_reason':'register primary hypothesis for draft generation',
  })
  assert status==200,project_with_hypothesis
  version_id=project_with_hypothesis['hypotheses'][0]['id']
  status,project_after_freeze=request(port,token,f"/api/research-projects/{project['id']}/hypotheses/{version_id}/freeze",'POST',{'actor':'researcher','reason':'lock for draft generation'})
  assert status==200,project_after_freeze
  status,draft=request(port,token,f"/api/research-projects/{project['id']}/draft",'POST');assert status==200 and 'approved-citations-only' in draft['content']
 finally:stop(process)
 port=free_port();process=server(port,token,appdata)
 try:
  status,projects=request(port,token,'/api/research-projects');assert status==200 and projects[0]['id']==project['id']
  status,draft=request(port,token,f"/api/research-projects/{project['id']}/draft");assert status==200 and 'Open science evidence' in draft['content']
 finally:stop(process)
