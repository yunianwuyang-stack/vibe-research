import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
def test_graph_inventories_production_layers_and_golden_path():
 from services.capability_graph import build
 graph=build(); kinds={x["kind"] for x in graph["nodes"]}
 assert {"route","application","domain","service","infrastructure","frontend"} <= kinds
 assert len(graph["golden_path"]["nodes"])==10

def test_registered_graph_api_routes_are_exposed():
 from fastapi.testclient import TestClient
 import os;os.environ['VIBE_LOCAL_SESSION_TOKEN']='graph-token'
 from main import app
 with TestClient(app) as c:
  r=c.get('/api/research-runs/capability-graph',headers={'X-Vibe-Session-Token':'graph-token'})
 assert r.status_code==200 and '/api/research-projects' in r.json()['registered_routes']
