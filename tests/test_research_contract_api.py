from __future__ import annotations
import asyncio, hashlib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
def test_contract_registers_byte_verified_but_not_provider_verified_evidence(tmp_path):
 import services.state_store as state_store
 import services.research_contracts as contracts
 old=state_store.DB_PATH;state_store.DB_PATH=tmp_path/"research.db"
 async def go():
  await state_store.init_db();p=await contracts.create_contract("Question","Mechanism?","peer-reviewed studies")
  content="provider response excerpt";digest=hashlib.sha256(content.encode()).hexdigest()
  try:await contracts.add_evidence(p["id"],"literature","z"*64,"openalex:W123",content)
  except Exception as x:assert x.status_code==422
  else:raise AssertionError("non-hex digest accepted")
  try:await contracts.add_evidence(p["id"],"literature",digest,"fictional:W123",content)
  except Exception as x:assert x.status_code==422
  else:raise AssertionError("fictional provider accepted")
  p=await contracts.add_evidence(p["id"],"literature",digest,"openalex:W123",content)
  assert p["status"]=="needs_evidence" and p["artifacts"][0]["status"]=="needs_review"
  try:await contracts.approve(p["id"],"reviewer",True,"review")
  except Exception as x:assert x.status_code==409
  else:raise AssertionError("unverified provider evidence approved")
 try:asyncio.run(go())
 finally:state_store.DB_PATH=old
