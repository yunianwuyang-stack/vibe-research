"""Production literature search endpoints with explicit provider failures."""
import asyncio
from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from infrastructure.literature import HttpTransport,LiteratureClient,ProviderUnavailable
from config import WORKSPACES_DIR
router=APIRouter(prefix="/api/literature",tags=["literature"])
class Search(BaseModel):provider:str=Field(pattern="^(openalex|crossref|datacite|arxiv|semantic_scholar)$");query:str=Field(min_length=3,max_length=500)
@router.post('/search')
async def search(body:Search):
 client=LiteratureClient(HttpTransport(),WORKSPACES_DIR/'literature-cache',min_interval_seconds=.2,timeout_seconds=15)
 try:records=await asyncio.to_thread(client.search,body.provider,body.query)
 except ProviderUnavailable as error:raise HTTPException(503,detail={"provider":body.provider,"status":"unavailable","reason":str(error)})
 try:_,snapshot_sha256=await asyncio.to_thread(client.replay_snapshot,body.provider,body.query)
 except ProviderUnavailable as error:raise HTTPException(503,detail={"provider":body.provider,"status":"unavailable","reason":str(error)})
 return {"provider":body.provider,"query":body.query,"snapshot_sha256":snapshot_sha256,"records":[r.__dict__|{"status":"needs_review","provenance":f"{r.provider}:{r.doi or r.url}","snapshot_sha256":snapshot_sha256} for r in records]}
