import asyncio,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
def test_provider_evidence_is_server_fetched(tmp_path,monkeypatch):
 import services.state_store as store
 import services.research_contracts as rc
 from domain.evidence import SourceRecord
 old=store.DB_PATH;store.DB_PATH=tmp_path/'x.db'
 class Client:
  def __init__(self,*a,**k):pass
  def search(self,p,q):return [SourceRecord(p,'T',(),2024,None,'https://openalex.org/W1','now',q)]
 monkeypatch.setattr(rc,'LiteratureClient',Client)
 async def go():
  await store.init_db();p=await rc.create_contract('T','Q?','I');v=await rc.verify_provider_evidence(p['id'],'openalex','query','https://openalex.org/W1');assert v['artifacts'][0]['status']=='verified';return v
 try:assert asyncio.run(go())['status']=='ready_for_review'
 finally:store.DB_PATH=old
