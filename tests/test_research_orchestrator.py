import asyncio,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
def test_run_is_explicitly_gated_and_cancelable(tmp_path):
 import services.state_store as store
 from services import research_contracts as projects,research_orchestrator as runs
 old=store.DB_PATH;store.DB_PATH=tmp_path/"r.db"
 async def go():
  await store.init_db();p=await projects.create_contract("T","Q","I");r=await runs.start(p["id"]);assert len(r["steps"])==10 and r["status"]=="paused"
  try: await runs.advance(r["id"],"contract",{"question":"Q"},[],[],True)
  except Exception as x: assert x.status_code==409
  else: raise AssertionError("empty artifacts completed a step")
  try: await runs.advance(r["id"],"contract",{"question":"Q"},[{"id":"forged"}],[{"source":"forged"}],True)
  except Exception as x: assert x.status_code==409
  else: raise AssertionError("forged artifacts completed a step")
  r=await runs.advance(r["id"],"contract",{"question":"Q"},[],[],False,"needs human contract")
  assert r["status"]=="blocked" and r["steps"][0]["status"]=="blocked"
  r=await runs.retry(r["id"],"contract");assert r["status"]=="paused" and r["current_step"]=="contract"
  r=await runs.resume(r["id"]);assert r["status"]=="running"
  await store.init_db();r=await runs.read(r["id"]);assert r["status"]=="paused"
  r=await runs.cancel(r["id"],"human cancelled");assert r["status"]=="cancelled"
 try:asyncio.run(go())
 finally:store.DB_PATH=old
