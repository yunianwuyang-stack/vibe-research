from __future__ import annotations
import os, subprocess, sys, time, json, urllib.error, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def request(url,method="GET",data=None,token="r01-test-token"):
 req=urllib.request.Request(url,data=data,method=method,headers={"X-Vibe-Session-Token":token,"Content-Type":"application/json"})
 try:
  with urllib.request.urlopen(req,timeout=3) as r:return r.status,r.read().decode()
 except urllib.error.HTTPError as e:return e.code,e.read().decode()
def test_uvicorn_process_health_and_contract_persist_across_restart(tmp_path):
 port=18991;env={**os.environ,"PYTHONPATH":str(ROOT/"backend"),"VIBE_LOCAL_SESSION_TOKEN":"r01-test-token","VIBE_DESKTOP":"1","API_PORT":str(port),"APPDATA":str(tmp_path)}
 def launch():return subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(port)],cwd=ROOT/"backend",env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 p=launch()
 try:
  for _ in range(40):
   try:
    if request(f"http://127.0.0.1:{port}/api/health")[0]==200:break
   except urllib.error.URLError:time.sleep(.1)
  else:raise AssertionError(p.stdout.read())
  assert request(f"http://127.0.0.1:{port}/api/health")[0]==200
  status, body=request(f"http://127.0.0.1:{port}/api/research-projects", "POST", json.dumps({"title":"E2E","research_question":"Q?","inclusion_criteria":"I"}).encode())
  assert status==200; project=json.loads(body); project_id=project["id"]
  status, body=request(f"http://127.0.0.1:{port}/api/research-runs/projects/{project_id}", "POST", b"{}")
  assert status==200; run_id=json.loads(body)["id"]
  assert request(f"http://127.0.0.1:{port}/api/research-runs/capability-graph")[0]==200
 finally:p.terminate();p.wait(timeout=8)
 p=launch()
 try:
  for _ in range(40):
   try:
    if request(f"http://127.0.0.1:{port}/api/health")[0]==200:break
   except urllib.error.URLError:time.sleep(.1)
  else:raise AssertionError(p.stdout.read())
  assert request(f"http://127.0.0.1:{port}/api/health")[0]==200
  status, body=request(f"http://127.0.0.1:{port}/api/research-projects/{project_id}")
  assert status==200 and json.loads(body)["id"]==project_id
  status, body=request(f"http://127.0.0.1:{port}/api/research-runs/{run_id}")
  assert status==200 and json.loads(body)["status"]=="paused"
 finally:p.terminate();p.wait(timeout=8)
