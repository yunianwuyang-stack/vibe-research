"""Database-backed Golden Path with explicit, non-forgeable gates."""
from __future__ import annotations
import json,uuid
from fastapi import HTTPException
from application.golden_path import GOLDEN_PATH
from services.state_store import get_db

def _step(name):return next((x for x in GOLDEN_PATH if x.name==name),None)
async def start(project_id:str)->dict:
 db=await get_db()
 try:
  p=await (await db.execute("SELECT status FROM research_projects WHERE id=?",(project_id,))).fetchone()
  if not p:raise HTTPException(404,"Research project not found")
  run=uuid.uuid4().hex;await db.execute("INSERT INTO research_runs (id,project_id,status,current_step) VALUES (?,?,?,?)",(run,project_id,"paused","contract"))
  for step in GOLDEN_PATH:await db.execute("INSERT INTO research_run_steps (run_id,name,status,input_json,gate_json) VALUES (?,?,?,?,?)",(run,step.name,"pending","{}",json.dumps({"required":list(step.gates)})))
  await db.commit();return await read(run)
 finally:await db.close()
async def read(run_id:str)->dict:
 db=await get_db()
 try:
  run=await (await db.execute("SELECT * FROM research_runs WHERE id=?",(run_id,))).fetchone()
  if not run:raise HTTPException(404,"Research run not found")
  rows=await (await db.execute("SELECT * FROM research_run_steps WHERE run_id=? ORDER BY id",(run_id,))).fetchall()
  return {**dict(run),"steps":[{**dict(x),"input":json.loads(x["input_json"]),"output":json.loads(x["output_json"]),"artifacts":json.loads(x["artifact_json"]),"provenance":json.loads(x["provenance_json"]),"gate":json.loads(x["gate_json"])} for x in rows]}
 finally:await db.close()


def _step_payload(row) -> dict:
  return {
    **dict(row),
    "input": json.loads(row["input_json"]),
    "output": json.loads(row["output_json"]),
    "artifacts": json.loads(row["artifact_json"]),
    "provenance": json.loads(row["provenance_json"]),
    "gate": json.loads(row["gate_json"]),
  }


async def _read_with_db(db, run_id: str) -> dict:
  run = await (await db.execute("SELECT * FROM research_runs WHERE id=?", (run_id,))).fetchone()
  if not run:
    raise HTTPException(404, "Research run not found")
  rows = await (
    await db.execute("SELECT * FROM research_run_steps WHERE run_id=? ORDER BY id", (run_id,))
  ).fetchall()
  return {**dict(run), "steps": [_step_payload(x) for x in rows]}


async def list_for_project(project_id: str) -> dict:
  """Restore durable Golden Path runs after process/UI reload (Unicode-safe)."""
  db = await get_db()
  try:
    project = await (
      await db.execute("SELECT id FROM research_projects WHERE id=?", (project_id,))
    ).fetchone()
    if not project:
      raise HTTPException(404, "Research project not found")
    rows = await (
      await db.execute(
        "SELECT id,project_id,status,current_step,created_at,updated_at FROM research_runs "
        "WHERE project_id=? ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC, id DESC",
        (project_id,),
      )
    ).fetchall()
    summaries = [dict(row) for row in rows]
    active = None
    # Prefer in-flight runs so workbench can resume after restart.
    priority = ("running", "paused", "blocked")
    preferred = next((item for status in priority for item in summaries if item["status"] == status), None)
    if preferred is None and summaries:
      preferred = summaries[0]
    if preferred is not None:
      active = await _read_with_db(db, preferred["id"])
    return {
      "project_id": project_id,
      "runs": summaries,
      "active": active,
      "count": len(summaries),
    }
  finally:
    await db.close()


async def advance(run_id:str,name:str,input_data:dict,artifacts:list[dict],provenance:list[dict],gate_passed:bool,failure_reason:str|None=None)->dict:
 step=_step(name)
 if not step:raise HTTPException(422,"Unknown Golden Path step")
 db=await get_db()
 try:
  run=await (await db.execute("SELECT * FROM research_runs WHERE id=?",(run_id,))).fetchone()
  if not run:raise HTTPException(404,"Research run not found")
  if run["current_step"]!=name:raise HTTPException(409,"Step is not current")
  # Client booleans are never authority. Every completed step must name
  # immutable artifacts and provenance; approval additionally needs a human event.
  if gate_passed and (not artifacts or not provenance):
   raise HTTPException(409,"Artifacts and provenance are required; client gate flag is insufficient")
  if gate_passed:
   artifact_ids=[str(x.get("id", "")) for x in artifacts]
   if not all(artifact_ids): raise HTTPException(409,"Artifacts require persisted identifiers")
   marks=','.join('?' for _ in artifact_ids)
   rows=await (await db.execute(f"SELECT id,provenance FROM research_artifacts WHERE project_id=? AND status='verified' AND id IN ({marks})",(run["project_id"],*artifact_ids))).fetchall()
   if len(rows)!=len(set(artifact_ids)): raise HTTPException(409,"Only server-verified project artifacts may pass a gate")
   known={row["provenance"] for row in rows}
   if not all(str(x.get("source", x.get("provenance", ""))) in known for x in provenance): raise HTTPException(409,"Provenance must match verified artifact records")
  if name == "approval" and gate_passed:
   approval = await (await db.execute("SELECT 1 FROM research_events WHERE project_id=? AND event_type='approval_recorded' AND actor != 'system' LIMIT 1",(run["project_id"],))).fetchone()
   if not approval: raise HTTPException(409,"Human approval record is required")
   from services.adversarial_review import current_inputs_sha256
   review_hash = await current_inputs_sha256(run["project_id"])
   review = await (await db.execute("SELECT 1 FROM adversarial_reviews WHERE project_id=? AND mode='deterministic' AND status='completed' AND verdict='pass' AND inputs_sha256=? LIMIT 1",(run["project_id"],review_hash))).fetchone()
   if not review: raise HTTPException(409,"Current deterministic adversarial review is required")
  if name == "adversarial_review" and gate_passed:
   from services.adversarial_review import current_inputs_sha256
   review_hash = await current_inputs_sha256(run["project_id"])
   review = await (await db.execute("SELECT 1 FROM adversarial_reviews WHERE project_id=? AND mode='deterministic' AND status='completed' AND verdict='pass' AND inputs_sha256=? LIMIT 1",(run["project_id"],review_hash))).fetchone()
   if not review: raise HTTPException(409,"Current deterministic adversarial review is required")
  prior=step.stale_dependencies
  if prior:
   x=await (await db.execute("SELECT status FROM research_run_steps WHERE run_id=? AND name=?",(run_id,prior[0]))).fetchone()
   if not x or x["status"]!="completed":raise HTTPException(409,"Required prior step is incomplete")
  status="completed" if gate_passed else "blocked"; output={"status":status,"next":None if name==GOLDEN_PATH[-1].name else GOLDEN_PATH[[s.name for s in GOLDEN_PATH].index(name)+1].name}
  await db.execute("UPDATE research_run_steps SET status=?,input_json=?,output_json=?,artifact_json=?,provenance_json=?,failure_reason=?,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND name=?",(status,json.dumps(input_data),json.dumps(output),json.dumps(artifacts),json.dumps(provenance),failure_reason,run_id,name))
  if not gate_passed:await db.execute("UPDATE research_runs SET status='blocked',updated_at=CURRENT_TIMESTAMP WHERE id=?",(run_id,))
  else:
   nxt=output["next"];await db.execute("UPDATE research_runs SET status=?,current_step=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",("completed" if not nxt else "paused",nxt,run_id))
  await db.commit();return await read(run_id)
 finally:await db.close()
async def retry(run_id:str, name:str)->dict:
 db=await get_db()
 try:
  run=await (await db.execute("SELECT * FROM research_runs WHERE id=?",(run_id,))).fetchone()
  if not run:raise HTTPException(404,"Research run not found")
  row=await (await db.execute("SELECT status FROM research_run_steps WHERE run_id=? AND name=?",(run_id,name))).fetchone()
  if not row or row["status"]!="blocked":raise HTTPException(409,"Only blocked step can retry")
  await db.execute("UPDATE research_run_steps SET status='pending',failure_reason=NULL,updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND name=?",(run_id,name))
  await db.execute("UPDATE research_runs SET status='paused',current_step=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(name,run_id));await db.commit();return await read(run_id)
 finally:await db.close()

async def resume(run_id:str)->dict:
 db=await get_db()
 try:
  run=await (await db.execute("SELECT * FROM research_runs WHERE id=?",(run_id,))).fetchone()
  if not run:raise HTTPException(404,"Research run not found")
  if run["status"]!="paused":raise HTTPException(409,"Only paused run can resume")
  await db.execute("UPDATE research_runs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",(run_id,));await db.commit();return await read(run_id)
 finally:await db.close()

async def cancel(run_id:str,reason:str)->dict:
 db=await get_db()
 try:
  n=await db.execute("UPDATE research_runs SET status='cancelled',updated_at=CURRENT_TIMESTAMP WHERE id=?",(run_id,))
  if n.rowcount==0:raise HTTPException(404,"Research run not found")
  await db.execute("UPDATE research_run_steps SET failure_reason=? WHERE run_id=? AND status='pending'",(reason,run_id));await db.commit();return await read(run_id)
 finally:await db.close()
