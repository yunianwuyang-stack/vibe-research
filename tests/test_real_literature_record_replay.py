import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
from infrastructure.literature import RecordingHttpTransport,ReplayTransport,ProviderUnavailable
class R:
 status=200;headers={}
 def __enter__(self):return self
 def __exit__(self,*x):pass
 def read(self):return json.dumps({"results":[{"title":"Evidence","authorships":[],"publication_year":2024,"id":"https://openalex.org/W1"}]}).encode()
def test_recorded_http_response_replays_and_tamper_is_rejected(tmp_path):
 items=RecordingHttpTransport(tmp_path,opener=lambda *_a,**_kw:R()).get_json("openalex","question",1);assert items[0]["title"]=="Evidence"
 assert ReplayTransport(tmp_path).get_json("openalex","question",1)==items
 path=next(tmp_path.glob("*.json"));saved=json.loads(path.read_text());saved["records"][0]["title"]="tampered";path.write_text(json.dumps(saved))
 try:ReplayTransport(tmp_path).get_json("openalex","question",1)
 except ProviderUnavailable:pass
 else:raise AssertionError("tampered replay accepted")
