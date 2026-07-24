import asyncio,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
def test_router_returns_provider_provenance(monkeypatch,tmp_path):
 import routers.literature as router
 class Fake:
  def __init__(self,*a,**k):pass
  def search(self,p,q):
   from domain.evidence import SourceRecord
   return [SourceRecord(p,"Title",(),2024,"10.1234/x","https://doi.org/10.1234/x","now",q)]
  def replay_snapshot(self,p,q):
   from domain.evidence import SourceRecord
   records=[SourceRecord(p,"Title",(),2024,"10.1234/x","https://doi.org/10.1234/x","now",q)]
   return records,"a"*64
 monkeypatch.setattr(router,'LiteratureClient',Fake)
 async def go():return await router.search(router.Search(provider='openalex',query='causal test'))
 response=asyncio.run(go());assert response['records'][0]['provenance']=='openalex:10.1234/x' and response['records'][0]['status']=='needs_review'
 assert response['snapshot_sha256']=='a'*64
