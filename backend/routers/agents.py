from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from services.agent_bundle import build_adapter_manifest
from services.agent_adapters import CliAdapter,AdapterError
from services import agent_tasks, agent_collaboration
from config import WORKSPACES_DIR
router=APIRouter(prefix='/api/agents',tags=['agents'])
class Run(BaseModel):adapter:str=Field(pattern='^(codex|claude)$');prompt:str=Field(min_length=1);workspace:str=Field(min_length=1)
class StartTask(BaseModel):project_id:str=Field(min_length=1);adapter:str=Field(pattern='^(codex|claude)$');prompt:str=Field(min_length=1,max_length=20000);timeout_seconds:float=Field(default=120,gt=0,le=1800)
class StartCollaboration(BaseModel):
 project_id:str=Field(min_length=1)
 goal:str=Field(min_length=3,max_length=20000)
 roles:list[str]=Field(default_factory=lambda:["executor","reviewer","editor_ai"])
 cli_adapters:list[str]=Field(default_factory=list)
 timeout_seconds:float=Field(default=120,gt=0,le=1800)
@router.get('/manifest')
async def adapter_manifest():
 from services.llm_client import get_env_for_subprocess
 configured=await get_env_for_subprocess()
 return build_adapter_manifest(configured_overrides={
  'codex':configured.get('CODEX_BIN',''),
  'claude':configured.get('CLAUDE_BIN',''),
 })
@router.post('/run')
async def run(body:Run):
 raise HTTPException(410,detail='Use persistent /api/agents/tasks; synchronous execution cannot be cancelled or recovered')
@router.get('/tasks')
async def tasks(project_id:str):return await agent_tasks.list_tasks(project_id)
@router.post('/tasks')
async def start_task(body:StartTask):return await agent_tasks.start(body.project_id,body.adapter,body.prompt,body.timeout_seconds)
@router.get('/tasks/{task_id}')
async def get_task(task_id:str):return await agent_tasks._read(task_id)
@router.post('/tasks/{task_id}/cancel')
async def cancel_task(task_id:str):return await agent_tasks.cancel(task_id)
@router.post('/tasks/{task_id}/retry')
async def retry_task(task_id:str):return await agent_tasks.retry(task_id)
@router.get('/collaborations')
async def collaborations(project_id:str):return await agent_collaboration.list_collaborations(project_id)
@router.post('/collaborations')
async def start_collaboration(body:StartCollaboration):
 return await agent_collaboration.start(
  body.project_id,
  body.goal,
  roles=body.roles,
  cli_adapters=body.cli_adapters,
  timeout_seconds=body.timeout_seconds,
 )
@router.get('/collaborations/{collab_id}')
async def get_collaboration(collab_id:str):return await agent_collaboration.get_collaboration(collab_id)
