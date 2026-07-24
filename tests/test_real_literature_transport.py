from __future__ import annotations
import io,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
from infrastructure.literature import HttpTransport,LiteratureClient,ProviderUnavailable,FixtureTransport
class Response:
 status=200
 headers={}
 def __init__(self,p):self.p=p
 def read(self):return json.dumps(self.p).encode()
 def __enter__(self):return self
 def __exit__(self,*x):pass
def test_openalex_http_transport_records_request_and_cache_provenance(tmp_path):
 seen=[]
 def opener(req,timeout):
  seen.append((req.full_url,req.headers.get("User-agent"),timeout));return Response({"results":[{"title":"Real work","authorships":[],"publication_year":2024,"doi":"https://doi.org/10.1/X","id":"https://openalex.org/W1"}]})
 client=LiteratureClient(HttpTransport(opener=opener),tmp_path,timeout_seconds=3)
 found=client.search("openalex","causal inference")
 assert found[0].doi=="10.1/x" and "openalex.org" in seen[0][0] and "VibeResearch" in seen[0][1]
 cached=next(tmp_path.glob("openalex-*.json"));saved=json.loads(cached.read_text());assert saved["query"]=="causal inference" and len(saved["content_sha256"])==64
 assert client.search("openalex","causal inference")[0].title=="Real work" and len(seen)==1
 saved["records"][0]["title"]="tampered";cached.write_text(json.dumps(saved),encoding="utf-8")
 refreshed=client.search("openalex","causal inference");assert refreshed[0].title=="Real work" and len(seen)==2
 assert cached.with_suffix(cached.suffix+".invalid").is_file()
def test_provider_error_isolated_not_fake():
 def down(*_a,**_kw):raise TimeoutError("down")
 try:HttpTransport(retries=0,opener=down).get_json("crossref","q",1)
 except ProviderUnavailable:pass
 else:raise AssertionError("network failure was not explicit")

def test_network_failure_replays_only_verified_same_query(tmp_path):
 good=LiteratureClient(FixtureTransport({"openalex":[{"title":"Cached","authors":[],"year":2024,"doi":None,"url":"https://openalex.org/W1"}]}),tmp_path)
 assert good.search("openalex","same query")[0].title=="Cached"
 cache=next(tmp_path.glob("openalex-*.json"));cache.rename(tmp_path/("openalex-recording.json"))
 down=LiteratureClient(FixtureTransport({}),tmp_path)
 assert down.search("openalex","same query")[0].title=="Cached"
 try:down.search("openalex","different query")
 except ProviderUnavailable:pass
 else:raise AssertionError("different query replayed")

def test_arxiv_atom_transport_extracts_real_fields():
 atom="""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1234.5678</id><title>A real preprint</title><published>2024-01-01T00:00:00Z</published><author><name>Ada</name></author></entry></feed>"""
 class AtomResponse(Response):
  def read(self):return atom.encode()
 items=HttpTransport(opener=lambda *_a,**_kw:AtomResponse({})).get_json("arxiv","causality",1)
 assert items==[{"title":"A real preprint","authors":["Ada"],"year":"2024","doi":None,"url":"http://arxiv.org/abs/1234.5678"}]
