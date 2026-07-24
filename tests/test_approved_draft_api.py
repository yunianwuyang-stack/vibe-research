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
   return path, SourceRecord(provider,title,tuple(authors),year,doi,url,'now',query)
  def search(self,provider,query):
   _, record=self._write(provider,query);return [record]
  def replay_snapshot(self,provider,query):
   import hashlib
   path, record=self._write(provider,query)
   return [record], hashlib.sha256(path.read_bytes()).hexdigest()
 return Client


def test_draft_requires_approved_evidence_and_persists_editable_outputs(tmp_path,monkeypatch):
 import services.state_store as store
 import services.research_contracts as contracts
 import services.approved_drafts as drafts
 import services.claim_evidence as claim_evidence
 import services.hypothesis_lifecycle as hypothesis
 import services.scientific_narrative as narrative
 import services.adversarial_review as adversarial
 workspace=tmp_path/'workspaces'
 workspace.mkdir()
 old_db=store.DB_PATH
 old_paths={
  'drafts':drafts.WORKSPACES_DIR,
  'contracts':contracts.WORKSPACES_DIR,
  'claim':claim_evidence.WORKSPACES_DIR,
  'hypothesis':hypothesis.WORKSPACES_DIR,
  'adversarial':adversarial.WORKSPACES_DIR,
 }
 store.DB_PATH=tmp_path/'draft.db'
 for module in (drafts,contracts,claim_evidence,hypothesis,adversarial):
  module.WORKSPACES_DIR=workspace
 monkeypatch.setattr(contracts,'LiteratureClient',_snapshot_client('Approved source',['Author'],2024,'10.1234/approved','https://doi.org/10.1234/approved'))
 async def go():
  await store.init_db()
  project=await contracts.create_contract('Study','Does it work?','peer reviewed')
  try:await drafts.generate(project['id'])
  except Exception as exc:assert getattr(exc,'status_code',None)==409
  else:raise AssertionError('draft generated without approved evidence')
  project=await contracts.save_provider_evidence(project['id'],'openalex','query','https://doi.org/10.1234/approved')
  card=project['evidence_cards'][0]
  project=await contracts.review_evidence_card(project['id'],card['id'],'researcher','approved','checked')
  try:await drafts.generate(project['id'])
  except Exception as exc:assert getattr(exc,'status_code',None)==409
  else:raise AssertionError('draft generated without approved claim support')
  project=await contracts.review_claim_support(project['id'],card['id'],'researcher','approved','full text supports claim')
  await narrative.save_map(project['id'],{
   'question':'Does it work?',
   'tension':'Prior findings disagree',
   'mechanism':'A measurable pathway',
   'hypotheses':['H1 predicts a difference'],
   'claims':['C1'],
   'competing_explanations':['selection bias'],
   'boundaries':['peer-reviewed studies'],
   'limitations':['small evidence base'],
  })
  await narrative.approve_map(project['id'],'researcher')
  graph=await claim_evidence.create_link(project['id'],{
   'claim_id':'C1',
   'evidence_card_id':card['id'],
   'relation':'supports',
   'passage':'The source reports a measurable pathway.',
   'locator':'p.1',
  })
  link_id=graph['links'][0]['id']
  graph=await claim_evidence.review_link(project['id'],link_id,'researcher','approved','passage supports claim')
  assert graph['gate']['passed'] is True
  version=await hypothesis.create(project['id'],{
   'statement':'Treatment changes the measured outcome',
   'mechanism':'A measurable pathway',
   'prediction':'Treatment mean exceeds control mean',
   'falsification_criteria':'No difference after three seeded replications',
   'boundary_conditions':'numeric observations only',
  },'researcher','register baseline hypothesis')
  await hypothesis.transition(project['id'],version['id'],'freeze','researcher','lock for draft generation')
  draft=await drafts.generate(project['id'])
  assert 'approved-citations-only' in draft['content'] and 'Approved source' in draft['content']
  assert (workspace/project['id']/draft['path']).is_file()
  assert (workspace/project['id']/'paper'/'main.tex').is_file()
  saved=await drafts.save(project['id'],draft['content']+'\nResearcher edit. [claim:C1]\n')
  assert saved['ok']
 try:asyncio.run(go())
 finally:
  store.DB_PATH=old_db
  drafts.WORKSPACES_DIR=old_paths['drafts']
  contracts.WORKSPACES_DIR=old_paths['contracts']
  claim_evidence.WORKSPACES_DIR=old_paths['claim']
  hypothesis.WORKSPACES_DIR=old_paths['hypothesis']
  adversarial.WORKSPACES_DIR=old_paths['adversarial']
