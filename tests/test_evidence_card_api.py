from __future__ import annotations
import asyncio, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))

def _snapshot_client(title, authors, year, doi, url):
 import hashlib, json
 from domain.evidence import SourceRecord
 class Client:
  def __init__(self,*a,**k):
   self.cache=Path(a[1])
  def _write(self,provider,query):
   records=[{"title":title,"authors":list(authors),"year":year,"doi":doi,"url":url}]
   self.cache.mkdir(parents=True,exist_ok=True)
   raw=json.dumps(records,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
   path=self.cache/f"{provider}-{hashlib.sha256(query.encode()).hexdigest()}.json"
   path.write_text(json.dumps({"provider":provider,"query":query,"retrieved_at":"now","records":records,"content_sha256":hashlib.sha256(raw).hexdigest()},ensure_ascii=False),encoding='utf-8')
   record=SourceRecord(provider,title,tuple(authors),year,doi,url,'2026-01-01T00:00:00Z',query)
   return path, record, hashlib.sha256(path.read_bytes()).hexdigest()
  def search(self,provider,query):
   _, record, _ = self._write(provider,query)
   return [record]
  def replay_snapshot(self,provider,query):
   path, record, digest = self._write(provider,query)
   return [record], digest
 return Client

def test_evidence_cards_deduplicate_across_providers_and_require_human_review(tmp_path,monkeypatch):
 import services.state_store as store
 import services.research_contracts as contracts
 old=store.DB_PATH;store.DB_PATH=tmp_path/'evidence.db'
 workspace=tmp_path/'workspaces';workspace.mkdir()
 monkeypatch.setattr(contracts,'WORKSPACES_DIR',workspace)
 monkeypatch.setattr(contracts,'LiteratureClient',_snapshot_client('Same paper',['A Author'],2024,'10.1234/test','https://doi.org/10.1234/test'))
 async def go():
  await store.init_db();project=await contracts.create_contract('P','Question?','peer reviewed')
  project=await contracts.save_provider_evidence(project['id'],'openalex','question','https://doi.org/10.1234/test')
  project=await contracts.save_provider_evidence(project['id'],'crossref','question','https://doi.org/10.1234/test')
  assert len(project['evidence_cards'])==1 and len(project['evidence_cards'][0]['provenance'])==2
  card=project['evidence_cards'][0];assert card['citation_status']=='needs_review' and card['claim_support_status']=='needs_review'
  project=await contracts.review_evidence_card(project['id'],card['id'],'researcher','approved','metadata checked')
  assert project['evidence_cards'][0]['citation_status']=='approved'
  assert project['evidence_cards'][0]['claim_support_status']=='needs_review'
  machine_card=project['evidence_cards'][0]
  assert machine_card.get('citation_machine_verdict')=='PASS'
  assert machine_card.get('citation_machine_layer') in {'offline_snapshot','doi','metadata','live_doi'}
  assert machine_card.get('citation_machine_artifact_path','').startswith('citation_checks/')
  artifact=workspace/project['id']/machine_card['citation_machine_artifact_path']
  assert artifact.is_file() and artifact.stat().st_size>=50
  project=await contracts.review_claim_support(project['id'],card['id'],'researcher','approved','full text supports claim')
  assert project['evidence_cards'][0]['claim_support_status']=='approved'
  assert (await contracts.list_contracts())[0]['id']==project['id']
 try:asyncio.run(go())
 finally:store.DB_PATH=old

def test_evidence_card_rejects_invalid_doi(tmp_path,monkeypatch):
 import services.state_store as store
 import services.research_contracts as contracts
 old=store.DB_PATH;store.DB_PATH=tmp_path/'invalid.db'
 workspace=tmp_path/'workspaces';workspace.mkdir()
 monkeypatch.setattr(contracts,'WORKSPACES_DIR',workspace)
 # Starts with 10. so SourceRecord accepts it, but fails the product DOI regex (needs 4-9 digits after 10.).
 monkeypatch.setattr(contracts,'LiteratureClient',_snapshot_client('Bad',[],2024,'10.12/invalid','https://example.org/bad'))
 async def go():
  await store.init_db();project=await contracts.create_contract('P','Question?','criteria')
  try:await contracts.save_provider_evidence(project['id'],'openalex','query','https://example.org/bad')
  except Exception as exc:assert getattr(exc,'status_code',None)==422
  else:raise AssertionError('invalid DOI accepted')
 try:asyncio.run(go())
 finally:store.DB_PATH=old
